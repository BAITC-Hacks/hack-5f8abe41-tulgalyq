"""Small end-to-end checks for the dependency-free demo API."""

from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

import app


class AppTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        app.init_db()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB_PATH = self.old_db
        self.temp.cleanup()

    def api(self, path, method="GET", payload=None):
        body = json.dumps(payload or {}).encode() if method != "GET" else None
        request = Request(self.base + path, data=body, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_full_flow_and_publication_boundary(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в столовой", "topic": "Общепит"})
        task_id = task["id"]
        self.assertEqual(len(task["questions"]), 3)
        self.assertEqual(self.api("/api/tasks")[1], [])
        self.assertEqual(self.api("/api/workspace/tasks")[1][0]["status"], "draft")
        _, task = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"title": "Быстрая столовая", "need": "Сократить ожидание"}})
        self.assertEqual(task["preview_score"], 10)
        self.assertEqual(task["confirmed_score"], 0)
        _, task = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertEqual(task["confirmed_score"], 10)
        self.assertEqual(len(self.api("/api/tasks")[1]), 1)
        _, unchanged = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"title": "Быстрая столовая", "need": "Сократить ожидание"}})
        self.assertEqual(unchanged["status"], "confirmed")
        _, team = self.api("/api/teams", "POST", {"name": "Тестовая команда", "skills": "Дизайн"})
        _, proposal = self.api("/api/proposals", "POST", {"task_id": task_id, "team_id": team["id"],
            "idea": "Предзаказ через телефон", "plan": "Сделать прототип и тест"})
        proposal_id = proposal["id"]
        self.assertEqual(len(self.api(f"/api/proposals?task_id={task_id}")[1]), 1)
        self.assertEqual(self.api(f"/api/proposals/{proposal_id}/progress", "POST", {"description": "Готов первый прототип"})[0], 400)
        self.api(f"/api/proposals/{proposal_id}/decision", "POST", {"decision": "selected"})
        _, stage = self.api(f"/api/proposals/{proposal_id}/progress", "POST", {"description": "Готов первый прототип"})
        _, confirmed = self.api(f"/api/progress/{stage['id']}/confirm", "POST")
        self.assertEqual(confirmed["points"], 10)
        self.assertEqual(self.api("/api/teams")[1][0]["points"], 10)
        self.assertEqual(self.api(f"/api/progress/{stage['id']}/confirm", "POST")[0], 404)
        self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"data": "Анонимные времена заказов"}})
        self.assertEqual(self.api("/api/tasks")[1], [])

    def test_demo_seed_is_idempotent_and_has_rating_range(self):
        self.api("/api/tasks", "POST", {"description": "Наша отдельная настоящая задача"})
        _, result = self.api("/api/demo/seed", "POST")
        self.assertTrue(result["created"])
        self.assertEqual(result["tasks"], 5)
        self.assertFalse(self.api("/api/demo/seed", "POST")[1]["created"])
        ratings = [task["confirmed_score"] for task in self.api("/api/tasks?sort=rating")[1]]
        self.assertEqual(ratings, [task["confirmed_score"] for task in self.api("/api/tasks")[1]])
        self.assertEqual(len(ratings), 5)
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertLess(ratings[-1], ratings[0])
        self.assertEqual(len(self.api("/api/tasks?readiness=low")[1]), 1)
        self.assertEqual(len(self.api("/api/tasks?readiness=medium")[1]), 1)
        self.assertEqual(len(self.api("/api/tasks?readiness=high")[1]), 1)
        self.assertEqual(len(self.api("/api/tasks?readiness=priority")[1]), 2)
        self.assertEqual(len(self.api("/api/teams")[1]), 5)
        self.assertEqual(len(self.api("/api/proposals")[1]), 5)
        self.assertTrue(all(team["interests"] and team["technologies"] for team in self.api("/api/teams")[1]))
        self.assertTrue(all(item["deadline"] and item["prototype_url"] for item in self.api("/api/proposals")[1]))
        code, matches = self.api("/api/teams/demo-team-1/recommendations")
        self.assertEqual(code, 200)
        self.assertEqual(matches[0]["task_id"], "demo-card-1")
        self.assertIn("образование", matches[0]["matched_terms"])
        self.assertEqual(self.api("/api/teams/unknown/recommendations")[0], 404)
        self.assertEqual(len(self.api("/api/tasks")[1]), 5)
        workspace = self.api("/api/workspace/tasks")[1]
        self.assertEqual(len(workspace), 11)
        self.assertEqual(sum(task["status"] == "draft" for task in workspace), 6)

    def test_readiness_boundaries_match_hackathon_case(self):
        for score, level in [(0, "low"), (39, "low"), (40, "medium"),
                             (69, "medium"), (70, "high"), (89, "high"),
                             (90, "priority"), (100, "priority")]:
            self.assertEqual(app.readiness_level(score), level)

    def test_ai_questions_keep_card_under_user_control(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Очередь в школьной столовой слишком длинная"})
        result = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"questions": [
            {"field": "users", "text": "Для каких учеников возникает эта очередь?"},
            {"field": "data", "text": "Есть ли замеры времени ожидания?"},
            {"field": "success_criteria", "text": "Как измерить успешное сокращение очереди?"},
        ]})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(app, "urlopen", return_value=BytesIO(json.dumps(result).encode())):
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "openai")
        self.assertEqual(len(answer["questions"]), 3)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "")


class MigrationTest(unittest.TestCase):
    def test_old_demo_database_keeps_records(self):
        with TemporaryDirectory() as folder:
            old_path = app.DB_PATH
            app.DB_PATH = Path(folder) / "old.sqlite3"
            try:
                with sqlite3.connect(app.DB_PATH) as db:
                    db.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, name TEXT NOT NULL, skills TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    db.execute("CREATE TABLE proposals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, team_id TEXT NOT NULL, idea TEXT NOT NULL, plan TEXT NOT NULL, prototype_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    db.execute("INSERT INTO teams (id, name, skills) VALUES ('old-team', 'Старая команда', 'Дизайн')")
                    db.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan) VALUES ('old-proposal', 'task', 'old-team', 'Идея', 'План')")
                app.init_db()
                with app.connect() as db:
                    team = db.execute("SELECT name, interests, technologies FROM teams WHERE id = 'old-team'").fetchone()
                    proposal = db.execute("SELECT deadline FROM proposals WHERE id = 'old-proposal'").fetchone()
                self.assertEqual((team["name"], team["interests"], team["technologies"]), ("Старая команда", "", ""))
                self.assertEqual(proposal["deadline"], "")
            finally:
                app.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
