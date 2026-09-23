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

    def test_mobile_assets_and_navigation_are_served(self):
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        with urlopen(self.base + "/mobile.css") as response:
            mobile_css = response.read().decode("utf-8")
        with urlopen(self.base + "/theme.css") as response:
            theme_css = response.read().decode("utf-8")
        with urlopen(self.base + "/tulgalyq-mark.svg") as response:
            logo = response.read().decode("utf-8")
            self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
        self.assertIn('href="/mobile.css"', page)
        self.assertIn('<title>Tulgalyq', page)
        self.assertIn('rel="icon" type="image/svg+xml" href="/tulgalyq-mark.svg"', page)
        self.assertIn('class="brand-symbol" src="/tulgalyq-mark.svg"', page)
        self.assertIn('class="avatar" src="/tulgalyq-mark.svg"', page)
        self.assertIn('<svg', logo)
        self.assertIn('href="/theme.css"', page)
        self.assertIn('id="mobile-menu-toggle"', page)
        self.assertIn('id="theme-toggle"', page)
        self.assertIn('id="primary-nav"', page)
        self.assertIn('id="catalog-search"', page)
        self.assertIn('id="catalog-reset"', page)
        self.assertIn('id="score-details"', page)
        self.assertIn('.score-panel summary', mobile_css)
        self.assertIn('html[data-theme="dark"]', theme_css)
        self.assertIn('grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)', theme_css)
        self.assertIn('grid-template-columns: minmax(0, 1fr) auto;', theme_css)
        self.assertIn('.menu-open .sidebar nav', theme_css)

    def test_full_flow_and_publication_boundary(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в столовой", "topic": "Общепит"})
        task_id = task["id"]
        self.assertEqual(len(task["questions"]), 3)
        self.assertEqual([question["field"] for question in task["questions"]],
                         ["need", "data", "success_criteria"])
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
        _, second_stage = self.api(f"/api/proposals/{proposal_id}/progress", "POST", {"description": "Готов второй этап тестирования"})
        self.api(f"/api/proposals/{proposal_id}/decision", "POST", {"decision": "rejected"})
        self.assertEqual(self.api(f"/api/progress/{second_stage['id']}/confirm", "POST")[0], 404)
        self.assertEqual(self.api("/api/teams")[1][0]["points"], 10)
        self.api(f"/api/proposals/{proposal_id}/decision", "POST", {"decision": "selected"})
        self.assertEqual(self.api(f"/api/progress/{second_stage['id']}/confirm", "POST")[0], 200)
        self.assertEqual(self.api("/api/teams")[1][0]["points"], 20)
        _, pending = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"data": "Анонимные времена заказов"}})
        self.assertEqual(pending["status"], "confirmed")
        self.assertTrue(pending["needs_confirmation"])
        self.assertEqual(pending["preview_score"], 30)
        self.assertEqual(pending["confirmed_score"], 10)
        app.init_db()  # Restart migration must not replace the published snapshot.
        self.assertEqual(self.api(f"/api/tasks/{task_id}?published=1")[1]["fields"]["data"], "")
        self.assertEqual(self.api("/api/tasks")[1][0]["confirmed_score"], 10)
        self.assertEqual(self.api("/api/tasks")[1][0]["fields"]["data"], "")
        self.assertEqual(self.api(f"/api/tasks/{task_id}")[1]["fields"]["data"], "Анонимные времена заказов")
        self.assertEqual(self.api("/api/proposals", "POST", {"task_id": task_id, "team_id": team["id"],
            "idea": "Ещё один вариант предзаказа", "plan": "Изучить очередь и проверить прототип"})[0], 201)
        _, republished = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertFalse(republished["needs_confirmation"])
        self.assertEqual(republished["confirmed_score"], 30)
        self.assertEqual(self.api("/api/tasks")[1][0]["fields"]["data"], "Анонимные времена заказов")

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
        demo_drafts = [app.get_task(f"demo-draft-{index}") for index in range(1, 6)]
        self.assertEqual([task["preview_score"] for task in demo_drafts],
                         sorted({task["preview_score"] for task in demo_drafts}))
        self.assertTrue(all(task["topic"] for task in demo_drafts))

    def test_readiness_boundaries_match_hackathon_case(self):
        for score, level in [(0, "low"), (39, "low"), (40, "medium"),
                             (69, "medium"), (70, "high"), (89, "high"),
                             (90, "priority"), (100, "priority")]:
            self.assertEqual(app.readiness_level(score), level)

    def test_obvious_placeholders_do_not_raise_rating(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно улучшить очередь в школьной столовой"})
        task_id = task["id"]
        _, task = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "title": "аааааааааа", "need": "бла бла бла", "data": "тест", "users": "123456",
            "contact": "Иван",
        }})
        self.assertEqual(task["preview_score"], 0)
        self.assertEqual(task["earned"]["data"], 0)
        self.assertIn("data", task["quality_issues"])
        self.assertIn("contact", task["quality_issues"])
        self.assertIn("data", [item["field"] for item in task["questions"]])
        self.assertEqual(self.api(f"/api/tasks/{task_id}/confirm", "POST")[0], 400)
        _, corrected = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "title": "Уменьшить очередь в столовой", "need": "Сократить время ожидания обеда",
            "data": "Обезличенные замеры времени ожидания", "contact": "@schoolteam",
        }})
        self.assertEqual(corrected["preview_score"], 35)
        self.assertEqual(self.api(f"/api/tasks/{task_id}/confirm", "POST")[1]["confirmed_score"], 35)

    def test_ai_questions_keep_card_under_user_control(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Очередь в школьной столовой слишком длинная"})
        self.api(f"/api/tasks/{task['id']}", "PATCH", {"fields": {"users": "Ученики школы", "data": "тест"}})
        result = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"questions": [
            {"field": "data", "text": "Есть ли замеры времени ожидания?"},
            {"field": "success_criteria", "text": "Как измерить успешное сокращение очереди?"},
            {"field": "expected_result", "text": "Какой результат должна получить школа?"},
        ]})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(app, "urlopen", return_value=BytesIO(json.dumps(result).encode())) as mocked:
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")
        sent = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(json.loads(sent["input"])["fields"]["users"], "Ученики школы")
        self.assertNotIn("users", sent["text"]["format"]["schema"]["properties"]["questions"]["items"]["properties"]["field"]["enum"])
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "openai")
        self.assertEqual(len(answer["questions"]), 3)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "тест")

    def test_bad_ai_response_is_rejected_without_changing_task(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Клиентам трудно выбрать школьный кружок"})
        invalid = {"output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps({"questions": [{"field": "data", "text": "Есть ли данные?"}]})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(app, "urlopen", return_value=BytesIO(json.dumps(invalid).encode())):
            self.assertEqual(self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")[0], 400)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "")

    def test_proposal_requires_valid_prototype_address(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        self.api(f"/api/tasks/{task['id']}", "PATCH", {"fields": {
            "title": "Очередь в столовой", "need": "Сократить ожидание обеда"}})
        self.api(f"/api/tasks/{task['id']}/confirm", "POST")
        _, team = self.api("/api/teams", "POST", {"name": "Проверка адресов"})
        payload = {"task_id": task["id"], "team_id": team["id"],
                   "idea": "Электронный предзаказ", "plan": "Измерить очередь и собрать прототип"}
        for url in ("https://", "http://", "http://[ошибка", "javascript:alert(1)"):
            self.assertEqual(self.api("/api/proposals", "POST", {**payload, "prototype_url": url})[0], 400)
        self.assertEqual(self.api("/api/proposals", "POST", {**payload, "prototype_url": "https://example.org/demo"})[0], 201)

    def test_malformed_contact_does_not_break_card_or_catalog(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужна цифровая запись посетителей школы"})
        task_id = task["id"]
        code, card = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "title": "Запись посетителей", "need": "Сократить ожидание в приёмной", "contact": "http://[ошибка"}})
        self.assertEqual(code, 200)
        self.assertIn("contact", card["quality_issues"])
        self.assertEqual(card["earned"]["contact"], 0)
        self.assertEqual(self.api(f"/api/tasks/{task_id}/confirm", "POST")[0], 200)
        self.assertEqual(len(self.api("/api/tasks")[1]), 1)


class MigrationTest(unittest.TestCase):
    def test_old_demo_database_keeps_records(self):
        with TemporaryDirectory() as folder:
            old_path = app.DB_PATH
            app.DB_PATH = Path(folder) / "old.sqlite3"
            try:
                with sqlite3.connect(app.DB_PATH) as db:
                    db.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, raw_description TEXT NOT NULL, topic TEXT NOT NULL, fields_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', confirmed_score INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    db.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, name TEXT NOT NULL, skills TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    db.execute("CREATE TABLE proposals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, team_id TEXT NOT NULL, idea TEXT NOT NULL, plan TEXT NOT NULL, prototype_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    fields = {name: "" for name in app.FIELDS}
                    fields.update(title="Старая задача", need="бла бла")
                    db.execute("INSERT INTO tasks (id, raw_description, topic, fields_json, status, confirmed_score) VALUES ('old-task', 'Длинная очередь на входе', 'Другое', ?, 'confirmed', 10)", (json.dumps(fields),))
                    db.execute("INSERT INTO teams (id, name, skills) VALUES ('old-team', 'Старая команда', 'Дизайн')")
                    db.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan) VALUES ('old-proposal', 'task', 'old-team', 'Идея', 'План')")
                app.init_db()
                with app.connect() as db:
                    team = db.execute("SELECT name, interests, technologies FROM teams WHERE id = 'old-team'").fetchone()
                    proposal = db.execute("SELECT deadline FROM proposals WHERE id = 'old-proposal'").fetchone()
                    published = db.execute("SELECT published_fields_json FROM tasks WHERE id = 'old-task'").fetchone()
                self.assertEqual((team["name"], team["interests"], team["technologies"]), ("Старая команда", "", ""))
                self.assertEqual(proposal["deadline"], "")
                self.assertEqual(json.loads(published["published_fields_json"])["title"], "Старая задача")
                self.assertTrue(app.get_task("old-task")["rating_needs_review"])
            finally:
                app.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
