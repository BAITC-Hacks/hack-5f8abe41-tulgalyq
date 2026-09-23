"""Small end-to-end checks for the dependency-free demo API."""

from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote
import json
import os
import socket
import sqlite3
import unittest
from unittest.mock import patch

import app


class AppTest(unittest.TestCase):
    def setUp(self):
        self.gemini_env = patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENAI_API_KEY": ""})
        self.gemini_env.start()
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
        self.gemini_env.stop()

    def api(self, path, method="GET", payload=None):
        body = json.dumps(payload or {}).encode() if method != "GET" else None
        request = Request(self.base + path, data=body, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_local_env_loader_only_reads_known_settings_and_respects_process_env(self):
        with TemporaryDirectory() as folder:
            Path(folder, ".env").write_text(
                "GEMINI_API_KEY=local-dummy\nOPENAI_MODEL='example-model'\nUNEXPECTED_SETTING=ignored\n",
                encoding="utf-8",
            )
            with patch.object(app, "ROOT", Path(folder)), patch.dict(os.environ, {
                    "GEMINI_API_KEY": "process-dummy", "UNEXPECTED_SETTING": ""
            }):
                os.environ.pop("OPENAI_MODEL", None)
                app.load_local_env()
                self.assertEqual(os.environ["GEMINI_API_KEY"], "process-dummy")
                self.assertEqual(os.environ["OPENAI_MODEL"], "example-model")
                self.assertEqual(os.environ["UNEXPECTED_SETTING"], "")

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
        self.assertIn('id="publish-success"', page)
        self.assertIn('id="publish-new-task"', page)
        self.assertIn('class="ai-safety-note"', page)
        self.assertNotIn('<section class="hero">', page)
        self.assertIn('КОНСТРУКТОР БИЗНЕС-ЗАДАЧ · ШАГ 01 / 03', page)
        self.assertIn('Черновик · требует уточнения · 0–39', page)
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
        self.assertEqual(self.api("/api/tasks?readiness=low")[1][0]["id"], task_id)
        self.assertEqual(task["readiness_level"], "low")
        _, unchanged = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"title": "Быстрая столовая", "need": "Сократить ожидание"}})
        self.assertEqual(unchanged["status"], "confirmed")
        _, team = self.api("/api/teams", "POST", {"name": "Тестовая команда", "skills": "Дизайн"})
        _, proposal = self.api("/api/proposals", "POST", {"task_id": task_id, "team_id": team["id"],
            "idea": "Предзаказ через телефон", "plan": "Сделать прототип и тест",
            "prototype_url": "https://example.org/demo/predzakaz"})
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
            "idea": "Ещё один вариант предзаказа", "plan": "Изучить очередь и проверить прототип",
            "prototype_url": "https://example.org/demo/variant"})[0], 201)
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
        cards = self.api("/api/tasks?sort=rating")[1]
        for card in cards:
            self.assertEqual(set(card["fields"]), set(app.FIELDS))
            self.assertEqual(card["confirmed_score"], app.score_fields(card["fields"])[0])
        self.assertEqual(len(self.api("/api/tasks?topic=" + quote("Образование"))[1]), 1)
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

    def test_business_can_select_multiple_teams_without_auto_assignment(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Школьникам нужен удобный каталог кружков"})
        self.api(f"/api/tasks/{task['id']}/confirm", "POST")
        proposals = []
        for name in ("Исследователи", "Разработчики"):
            _, team = self.api("/api/teams", "POST", {"name": name, "skills": "Дизайн"})
            _, proposal = self.api("/api/proposals", "POST", {"task_id": task["id"], "team_id": team["id"],
                "idea": "Сделаем удобный каталог кружков", "plan": "Изучим потребности и соберём прототип",
                "prototype_url": "https://example.org/demo/kruzhki"})
            proposals.append(proposal["id"])
        self.assertEqual({p["status"] for p in self.api("/api/proposals")[1]}, {"pending"})
        for proposal_id in proposals:
            self.api(f"/api/proposals/{proposal_id}/decision", "POST", {"decision": "selected"})
        self.assertEqual([p["status"] for p in self.api("/api/proposals")[1]], ["selected", "selected"])
        self.api(f"/api/proposals/{proposals[0]}/decision", "POST", {"decision": "rejected"})
        self.assertEqual({p["id"]: p["status"] for p in self.api("/api/proposals")[1]},
                         {proposals[0]: "rejected", proposals[1]: "selected"})

    def test_readiness_boundaries_match_hackathon_case(self):
        self.assertEqual(app.WEIGHTS, {
            "context": 10, "need": 10, "data": 20, "expected_result": 15,
            "success_criteria": 15, "constraints": 10, "users": 10,
            "contact": 5, "interaction_format": 5,
        })
        self.assertEqual(sum(app.WEIGHTS.values()), 100)
        for score, level in [(0, "low"), (39, "low"), (40, "medium"),
                             (69, "medium"), (70, "high"), (89, "high"),
                             (90, "priority"), (100, "priority")]:
            self.assertEqual(app.readiness_level(score), level)

    def test_empty_data_and_vague_success_do_not_earn_points(self):
        for field, answer in (
            ("data", "Данных пока нет"),
            ("need", "Сделать лучше"),
            ("expected_result", "Хороший результат"),
            ("success_criteria", "Мы будем довольны"),
            ("interaction_format", "Будем на связи"),
        ):
            with self.subTest(field=field):
                self.assertIsNotNone(app.quality_issue(field, answer))
                self.assertEqual(app.score_fields({field: answer})[0], 0)
        self.assertIsNone(app.quality_issue("success_criteria", "Среднее ожидание ниже 7 минут"))
        self.assertEqual(app.score_fields({"success_criteria": "Среднее ожидание ниже 7 минут"})[0], 15)

    def test_zero_point_card_requires_confirmation_but_stays_visible(self):
        description = "Нужно сократить очередь в школьной столовой"
        _, task = self.api("/api/tasks", "POST", {"description": description})
        self.assertEqual(self.api("/api/tasks")[1], [])
        _, published = self.api(f"/api/tasks/{task['id']}/confirm", "POST")
        self.assertEqual(published["confirmed_score"], 0)
        self.assertEqual(published["readiness_level"], "low")
        self.assertEqual(self.api("/api/tasks?readiness=low")[1][0]["raw_description"], description)

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
        code, blocked = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertEqual(code, 422)
        self.assertIn("title", blocked["issues"])
        self.assertIn("contact", blocked["issues"])
        self.assertEqual(self.api("/api/tasks")[1], [])
        self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "title": "", "need": "", "data": "", "users": "", "contact": "",
        }})
        _, published_draft = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertEqual(published_draft["confirmed_score"], 0)
        self.assertEqual(self.api("/api/tasks?readiness=low")[1][0]["id"], task_id)
        _, team = self.api("/api/teams", "POST", {"name": "Команда уточнения"})
        self.assertEqual(self.api("/api/proposals", "POST", {"task_id": task_id, "team_id": team["id"],
            "idea": "Уточним проблему очереди", "plan": "Обсудим условия и предложим прототип",
            "prototype_url": "https://example.org/demo/queue"})[0], 201)
        _, corrected = self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "title": "Уменьшить очередь в столовой", "need": "Сократить время ожидания обеда",
            "data": "Обезличенные замеры времени ожидания", "contact": "@schoolteam",
        }})
        self.assertEqual(corrected["preview_score"], 35)
        self.assertEqual(corrected["confirmed_score"], 0)
        self.assertEqual(self.api(f"/api/tasks/{task_id}/confirm", "POST")[1]["confirmed_score"], 35)

    def test_ai_questions_keep_card_under_user_control(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Очередь в школьной столовой слишком длинная"})
        self.api(f"/api/tasks/{task['id']}", "PATCH", {"fields": {"users": "Ученики школы", "data": "тест"}})
        result = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"questions": [
            {"field": "data", "text": "Есть ли замеры времени ожидания?"},
            {"field": "success_criteria", "text": "Как измерить успешное сокращение очереди?"},
            {"field": "expected_result", "text": "Какой результат должна получить школа?"},
        ]})}]}]}
        typed_need = "Сократить ожидание учеников у стойки выдачи"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(app, "urlopen", return_value=BytesIO(json.dumps(result).encode())) as mocked:
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST",
                                    {"answers": {"need": typed_need}})
        sent = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(sent["instructions"], app.AI_INSTRUCTIONS)
        self.assertFalse(sent["store"])
        self.assertEqual(sent["text"]["format"]["type"], "json_schema")
        self.assertEqual(json.loads(sent["input"])["fields"]["users"], "Ученики школы")
        self.assertEqual(json.loads(sent["input"])["fields"]["need"], typed_need)
        self.assertNotIn("users", sent["text"]["format"]["schema"]["properties"]["questions"]["items"]["properties"]["field"]["enum"])
        self.assertNotIn("need", sent["text"]["format"]["schema"]["properties"]["questions"]["items"]["properties"]["field"]["enum"])
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "openai")
        self.assertEqual(len(answer["questions"]), 3)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "тест")
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")

    def test_answer_review_rejects_gibberish_without_saving_and_keeps_blank_optional(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Очередь в школьной столовой слишком длинная"})
        path = f"/api/tasks/{task['id']}/review"
        code, review = self.api(path, "POST", {"answers": [
            {"field": "need", "question": "Что хотите изменить?", "answer": "asdfghjkl"},
            {"field": "data", "question": "Какие данные доступны?", "answer": "1234567"},
            {"field": "success_criteria", "answer": ""},
        ]})
        self.assertEqual(code, 200)
        self.assertEqual(review["source"], "local")
        self.assertEqual(set(review["issues"]), {"need", "data"})
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")
        self.assertEqual(self.api(path, "POST", {"answers": [
            {"field": "need", "answer": "текст"}, {"field": "need", "answer": "повтор"},
        ]})[0], 400)
        self.assertEqual(self.api(path, "POST", {"answers": [
            {"field": "wrong", "answer": "текст"},
        ]})[0], 400)

    def test_gemini_review_checks_semantics_and_does_not_send_contact(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        self.api(f"/api/tasks/{task['id']}", "PATCH", {"fields": {"contact": "@schoolteam"}})
        result = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
            "items": [
                {"field": "need", "ok": False, "feedback": "Опишите, что изменить в очереди столовой."},
                {"field": "data", "ok": True, "feedback": ""},
            ]})}]}}]}
        answers = [
            {"field": "need", "question": "Что нужно изменить?", "answer": "У нас есть красивые баннеры"},
            {"field": "data", "question": "Какие данные доступны?", "answer": "Замеры ожидания за неделю"},
        ]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), \
                patch.object(app, "urlopen", return_value=BytesIO(json.dumps(result).encode())) as mocked:
            code, review = self.api(f"/api/tasks/{task['id']}/review", "POST", {"answers": answers})
        self.assertEqual(code, 200)
        self.assertEqual(review["source"], "gemini")
        self.assertEqual(set(review["issues"]), {"need"})
        sent = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(sent["systemInstruction"]["parts"][0]["text"], app.REVIEW_INSTRUCTIONS)
        self.assertNotIn("contact", sent["contents"][0]["parts"][0]["text"])
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")

    def test_semantic_review_blocks_publication_but_preserves_draft(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        task_id = task["id"]
        self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
            "need": "Сделать логотип для пиццерии", "title": "Очередь в столовой",
        }})
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
            "items": [
                {"field": "title", "ok": True, "feedback": ""},
                {"field": "need", "ok": False, "feedback": "Укажите изменение, связанное с очередью."},
            ]})}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), \
                patch.object(app, "urlopen", return_value=BytesIO(json.dumps(response).encode())):
            code, blocked = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertEqual(code, 422)
        self.assertIn("need", blocked["issues"])
        self.assertEqual(self.api(f"/api/tasks/{task_id}")[1]["status"], "draft")
        self.assertEqual(self.api("/api/tasks")[1], [])
        self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"need": ""}})
        self.assertEqual(self.api(f"/api/tasks/{task_id}/confirm", "POST")[0], 200)

    def test_malformed_review_falls_back_to_local_rules(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
            "items": [{"field": "wrong", "ok": True, "feedback": ""}],
        })}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), \
                patch.object(app, "urlopen", return_value=BytesIO(json.dumps(response).encode())):
            code, review = self.api(f"/api/tasks/{task['id']}/review", "POST", {"answers": [
                {"field": "need", "answer": "Сократить ожидание учеников у стойки выдачи"},
            ]})
        self.assertEqual(code, 200)
        self.assertEqual(review["source"], "local")
        self.assertEqual(review["fallback_reason"], "api_unavailable")

    def test_socket_timeout_returns_local_fallback_instead_of_dropping_connection(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        task_id = task["id"]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}), \
                patch.object(app, "urlopen", side_effect=socket.timeout("read timed out")):
            code, questions = self.api(f"/api/tasks/{task_id}/ai-questions", "POST", {"answers": {}})
            self.assertEqual(code, 200)
            self.assertEqual(questions["source"], "local")
            self.assertEqual(questions["fallback_reason"], "api_unavailable")

            code, review = self.api(f"/api/tasks/{task_id}/review", "POST", {"answers": [
                {"field": "need", "answer": "Сократить ожидание учеников у стойки выдачи"},
            ]})
            self.assertEqual(code, 200)
            self.assertEqual(review["source"], "local")
            self.assertEqual(review["fallback_reason"], "api_unavailable")

            self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {
                "need": "Сократить ожидание учеников у стойки выдачи",
            }})
            code, published = self.api(f"/api/tasks/{task_id}/confirm", "POST")
            self.assertEqual(code, 200)
            self.assertEqual(published["review_fallback_reason"], "api_unavailable")

    def test_openai_review_uses_structured_output_and_local_contact_check(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        response = {"status": "completed", "output": [{"type": "message", "content": [{
            "type": "output_text", "text": json.dumps({"items": [
                {"field": "need", "ok": True, "feedback": ""},
            ]}),
        }]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": ""}), \
                patch.object(app, "urlopen", return_value=BytesIO(json.dumps(response).encode())) as mocked:
            code, review = self.api(f"/api/tasks/{task['id']}/review", "POST", {"answers": [
                {"field": "need", "answer": "Сократить ожидание учеников у стойки выдачи"},
                {"field": "contact", "answer": "неизвестно"},
            ]})
        self.assertEqual(code, 200)
        self.assertEqual(review["source"], "openai")
        self.assertEqual(set(review["issues"]), {"contact"})
        sent = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(sent["text"]["format"]["type"], "json_schema")
        self.assertNotIn("contact", sent["input"])

    def test_gemini_questions_use_server_key_and_do_not_write_business_facts(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Очередь в школьной столовой слишком длинная"})
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "internal", "thought": True}, {"text": json.dumps({
            "questions": [
                {"field": "data", "text": "Какие замеры очереди уже доступны?"},
                {"field": "success_criteria", "text": "Как вы измерите улучшение ожидания?"},
                {"field": "expected_result", "text": "Что команда должна передать в итоге?"},
            ]})}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "OPENAI_API_KEY": "openai-test"}), \
                patch.object(app, "urlopen", return_value=BytesIO(json.dumps(response).encode())) as mocked:
            self.assertEqual(self.api("/api/health")[1]["ai_provider"], "gemini")
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST",
                                    {"answers": {"need": "Сократить ожидание обеда"}})
        sent_request = mocked.call_args.args[0]
        sent = json.loads(sent_request.data)
        self.assertIn("generativelanguage.googleapis.com", sent_request.full_url)
        self.assertEqual(sent_request.get_header("X-goog-api-key"), "test-secret")
        self.assertEqual(sent["systemInstruction"]["parts"][0]["text"], app.AI_INSTRUCTIONS)
        self.assertEqual(sent["generationConfig"]["responseMimeType"], "application/json")
        self.assertNotIn("need", sent["generationConfig"]["responseSchema"]["properties"]["questions"]["items"]["properties"]["field"]["enum"])
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "gemini")
        self.assertEqual(len(answer["questions"]), 3)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")

    def test_gemini_bad_answer_and_auth_error_fall_back(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        invalid = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "OPENAI_API_KEY": ""}):
            with patch.object(app, "urlopen", return_value=BytesIO(json.dumps(invalid).encode())):
                answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")[1]
                self.assertEqual(answer["source"], "local")
                self.assertEqual(answer["fallback_reason"], "api_unavailable")
            with patch.object(app, "urlopen", side_effect=HTTPError(
                    "https://generativelanguage.googleapis.com", 403, "API error", {}, None)):
                answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")[1]
                self.assertEqual(answer["fallback_reason"], "auth_failed")
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "")

    def test_bad_ai_response_falls_back_without_changing_task(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Клиентам трудно выбрать школьный кружок"})
        invalid = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps({"questions": [{"field": "data", "text": "Есть ли данные?"}]})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(app, "urlopen", return_value=BytesIO(json.dumps(invalid).encode())):
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "local")
        self.assertEqual(answer["fallback_reason"], "api_unavailable")
        self.assertEqual(len(answer["questions"]), 3)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["data"], "")

    def test_incomplete_refused_repeated_and_network_ai_answers_use_local_questions(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        repeated = {"questions": [
            {"field": field, "text": "Какие данные доступны для команды?"}
            for field in ("need", "data", "success_criteria")
        ]}
        responses = [
            {"status": "incomplete", "output": []},
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Нет"}]}]},
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(repeated)}]}]},
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            for index, response in enumerate(responses):
                with self.subTest(case=index), patch.object(
                        app, "urlopen", return_value=BytesIO(json.dumps(response).encode())):
                    code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")
                    self.assertEqual(code, 200)
                    self.assertEqual(answer["source"], "local")
                    self.assertEqual(answer["fallback_reason"], "api_unavailable")
            with patch.object(app, "urlopen", side_effect=URLError("offline")):
                self.assertEqual(self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")[1]["source"], "local")
            for http_code, reason in ((401, "auth_failed"), (429, "rate_limited")):
                with self.subTest(http_code=http_code), patch.object(app, "urlopen", side_effect=HTTPError(
                        "https://api.openai.com/v1/responses", http_code, "API error", {}, None)):
                    answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")[1]
                    self.assertEqual(answer["fallback_reason"], reason)
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")

    def test_local_questions_when_key_is_missing(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST",
                                    {"answers": {"need": "Сократить ожидание обеда"}})
        self.assertEqual(code, 200)
        self.assertEqual(answer["source"], "local")
        self.assertEqual(answer["fallback_reason"], "not_configured")
        self.assertNotIn("need", [question["field"] for question in answer["questions"]])
        self.assertEqual(self.api(f"/api/tasks/{task['id']}")[1]["fields"]["need"], "")
        self.assertEqual(self.api(f"/api/tasks/{task['id']}/ai-questions", "POST",
                                  {"answers": {"unknown_field": "x"}})[0], 400)

    def test_platform_web_link_is_not_treated_as_api_key(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        for link in ("https://platform.openai.com/p/not-a-key", "platform.openai.com/p/not-a-key"):
            with self.subTest(link_type=link.startswith("https")), patch.dict(os.environ, {"OPENAI_API_KEY": link}), \
                    patch.object(app, "urlopen") as external_api:
                self.assertEqual(self.api("/api/health")[1],
                                 {"ok": True, "ai_enabled": False, "ai_setup_issue": "web_link"})
                code, answer = self.api(f"/api/tasks/{task['id']}/ai-questions", "POST")
                self.assertEqual(code, 200)
                self.assertEqual(answer["source"], "local")
                self.assertEqual(answer["fallback_reason"], "invalid_configuration")
                external_api.assert_not_called()

    def test_proposal_requires_valid_prototype_address(self):
        _, task = self.api("/api/tasks", "POST", {"description": "Нужно сократить очередь в школьной столовой"})
        self.api(f"/api/tasks/{task['id']}", "PATCH", {"fields": {
            "title": "Очередь в столовой", "need": "Сократить ожидание обеда"}})
        self.api(f"/api/tasks/{task['id']}/confirm", "POST")
        _, team = self.api("/api/teams", "POST", {"name": "Проверка адресов"})
        payload = {"task_id": task["id"], "team_id": team["id"],
                   "idea": "Электронный предзаказ", "plan": "Измерить очередь и собрать прототип"}
        self.assertEqual(self.api("/api/proposals", "POST", payload)[0], 400)
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
        code, review = self.api(f"/api/tasks/{task_id}/confirm", "POST")
        self.assertEqual(code, 422)
        self.assertIn("contact", review["issues"])
        self.api(f"/api/tasks/{task_id}", "PATCH", {"fields": {"contact": ""}})
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
