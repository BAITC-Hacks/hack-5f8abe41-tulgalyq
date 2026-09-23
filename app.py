"""Mission 100: a small, dependency-free hackathon application."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json
import os
import sqlite3
import threading
import uuid


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "mission100.sqlite3"
FIELDS = (
    "title", "context", "need", "users", "data", "constraints",
    "expected_result", "success_criteria", "contact", "interaction_format",
)
WEIGHTS = {
    "context": 10, "need": 10, "data": 20, "expected_result": 15,
    "success_criteria": 15, "constraints": 10, "users": 10,
    "contact": 5, "interaction_format": 5,
}
QUESTION_BANK = (
    ("users", "Для кого именно нужно решение? Кто будет им пользоваться?"),
    ("data", "Какие данные, примеры или материалы вы сможете предоставить команде?"),
    ("success_criteria", "По каким измеримым признакам вы поймёте, что задача решена?"),
    ("expected_result", "Какой конкретный результат должна передать вам команда?"),
    ("constraints", "Какие есть сроки, технические ограничения или условия доступа?"),
    ("interaction_format", "Как команда сможет консультироваться с вами и получать обратную связь?"),
)
DB_LOCK = threading.Lock()


def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            raw_description TEXT NOT NULL,
            topic TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            confirmed_score INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def clean_text(value, max_length=4000):
    if not isinstance(value, str):
        raise ValueError("Все текстовые поля должны быть строками.")
    return value.strip()[:max_length]


def score_fields(fields):
    earned = {name: weight if fields.get(name, "").strip() else 0
              for name, weight in WEIGHTS.items()}
    return sum(earned.values()), earned


def task_from_row(row):
    fields = json.loads(row["fields_json"])
    preview_score, earned = score_fields(fields)
    questions = [
        {"field": field, "text": question}
        for field, question in QUESTION_BANK if not fields.get(field, "").strip()
    ][:3]
    if len(questions) < 3:
        questions += [
            {"field": field, "text": question}
            for field, question in QUESTION_BANK if fields.get(field, "").strip()
        ][:3 - len(questions)]
    return {
        "id": row["id"], "raw_description": row["raw_description"],
        "topic": row["topic"], "fields": fields, "status": row["status"],
        "confirmed_score": row["confirmed_score"],
        "preview_score": preview_score, "earned": earned,
        "questions": questions,
        "missing": [name for name in WEIGHTS if not fields.get(name, "").strip()],
    }


def get_task(task_id):
    with connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return task_from_row(row) if row else None


class Handler(BaseHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 64_000:
            raise ValueError("Некорректный размер запроса.")
        try:
            value = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Ожидался JSON.")
        if not isinstance(value, dict):
            raise ValueError("Ожидался JSON-объект.")
        return value

    def serve_file(self, filename, content_type):
        body = (ROOT / "static" / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.serve_file("index.html", "text/html; charset=utf-8")
        if path == "/style.css":
            return self.serve_file("style.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self.serve_file("app.js", "text/javascript; charset=utf-8")
        if path == "/api/health":
            return self.json_response(200, {"ok": True})
        if path.startswith("/api/tasks/"):
            task = get_task(path.rsplit("/", 1)[-1])
            return self.json_response(200 if task else 404, task or {"error": "Задача не найдена."})
        return self.json_response(404, {"error": "Страница не найдена."})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/tasks":
                raw = clean_text(data.get("description", ""))
                topic = clean_text(data.get("topic", "Другое"), 80)
                if len(raw) < 12:
                    raise ValueError("Опишите задачу хотя бы одним предложением.")
                task_id = str(uuid.uuid4())
                fields = {name: "" for name in FIELDS}
                with DB_LOCK, connect() as db:
                    db.execute(
                        "INSERT INTO tasks (id, raw_description, topic, fields_json) VALUES (?, ?, ?, ?)",
                        (task_id, raw, topic, json.dumps(fields, ensure_ascii=False)),
                    )
                return self.json_response(201, get_task(task_id))
            if path.startswith("/api/tasks/") and path.endswith("/confirm"):
                task_id = path.split("/")[3]
                task = get_task(task_id)
                if not task:
                    return self.json_response(404, {"error": "Задача не найдена."})
                fields = task["fields"]
                if not fields["title"] or not fields["need"]:
                    raise ValueError("Перед подтверждением заполните название и потребность.")
                score, _ = score_fields(fields)
                with DB_LOCK, connect() as db:
                    db.execute("UPDATE tasks SET status = 'confirmed', confirmed_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (score, task_id))
                return self.json_response(200, get_task(task_id))
            return self.json_response(404, {"error": "Действие не найдено."})
        except ValueError as error:
            return self.json_response(400, {"error": str(error)})

    def do_PATCH(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/tasks/"):
            return self.json_response(404, {"error": "Действие не найдено."})
        try:
            data = self.read_json()
            task_id = path.rsplit("/", 1)[-1]
            task = get_task(task_id)
            if not task:
                return self.json_response(404, {"error": "Задача не найдена."})
            changes = data.get("fields", {})
            if not isinstance(changes, dict) or any(name not in FIELDS for name in changes):
                raise ValueError("Неизвестное поле карточки.")
            fields = task["fields"]
            for name, value in changes.items():
                fields[name] = clean_text(value)
            with DB_LOCK, connect() as db:
                db.execute("UPDATE tasks SET fields_json = ?, status = 'draft', confirmed_score = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                           (json.dumps(fields, ensure_ascii=False), task_id))
            return self.json_response(200, get_task(task_id))
        except ValueError as error:
            return self.json_response(400, {"error": str(error)})


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "8000"))
    print("Миссия 100: http://localhost:%d" % port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
