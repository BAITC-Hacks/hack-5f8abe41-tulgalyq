"""Mission 100: a small, dependency-free hackathon application."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import sqlite3
import threading
import uuid


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("MISSION100_DB_PATH", str(ROOT / "data" / "mission100.sqlite3")))
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
        db.execute("""CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, skills TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, team_id TEXT NOT NULL,
            idea TEXT NOT NULL, plan TEXT NOT NULL, prototype_url TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES tasks(id), FOREIGN KEY(team_id) REFERENCES teams(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS progress (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', points INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(proposal_id) REFERENCES proposals(id)
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


def ai_questions(task):
    """Ask only questions; never synthesize or save unverified business facts."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise ValueError("AI не настроен: задайте OPENAI_API_KEY на сервере.")
    allowed = [field for field, _ in QUESTION_BANK if not task["fields"].get(field)]
    if len(allowed) < 3:
        allowed = [field for field, _ in QUESTION_BANK]
    schema = {
        "type": "object", "properties": {"questions": {"type": "array", "items": {
            "type": "object", "properties": {
                "field": {"type": "string", "enum": allowed}, "text": {"type": "string"}
            }, "required": ["field", "text"], "additionalProperties": False
        }}}, "required": ["questions"], "additionalProperties": False,
    }
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "instructions": ("Ты редактор бизнес-задач. На русском языке задай ровно 3 разных "
            "конкретных уточняющих вопроса по данному черновику. Спрашивай только о неизвестных "
            "сведениях, которые помогут команде решать задачу. Не утверждай неуказанные факты, "
            "не придумывай данные и не заполняй карточку за бизнес. Каждый вопрос должен "
            "соответствовать своему полю и не повторять другие вопросы."),
        "input": task["raw_description"],
        "text": {"format": {"type": "json_schema", "name": "clarifying_questions", "strict": True, "schema": schema}},
        "store": False,
    }
    request = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        texts = [part["text"] for item in result.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        parsed = json.loads("".join(texts))
        questions = parsed["questions"]
        if len(questions) != 3 or len({q["field"] for q in questions}) != 3:
            raise ValueError("AI вернул некорректные вопросы.")
        if any(q["field"] not in allowed or not isinstance(q["text"], str)
               or not 10 <= len(q["text"].strip()) <= 240 for q in questions):
            raise ValueError("AI вернул некорректные вопросы.")
        return [{"field": q["field"], "text": q["text"].strip()} for q in questions]
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("AI сейчас недоступен. Используйте обычные уточняющие вопросы.") from error


def list_tasks(topic="", sort="newest", readiness=""):
    with connect() as db:
        rows = db.execute("SELECT * FROM tasks WHERE status = 'confirmed' AND (? = '' OR topic = ?) ORDER BY created_at DESC, rowid DESC", (topic, topic)).fetchall()
        counts = dict(db.execute("SELECT task_id, COUNT(*) FROM proposals GROUP BY task_id").fetchall())
    tasks = [task_from_row(row) for row in rows]
    for task in tasks:
        task["proposal_count"] = counts.get(task["id"], 0)
    if readiness == "low":
        tasks = [task for task in tasks if task["confirmed_score"] < 50]
    elif readiness == "medium":
        tasks = [task for task in tasks if 50 <= task["confirmed_score"] < 80]
    elif readiness == "high":
        tasks = [task for task in tasks if task["confirmed_score"] >= 80]
    if sort == "rating":
        tasks.sort(key=lambda task: task["confirmed_score"], reverse=True)
    elif sort == "readiness":
        tasks.sort(key=lambda task: (task["status"] == "confirmed", task["confirmed_score"]), reverse=True)
    return tasks


def list_workspace_tasks():
    """Demo workspace: includes drafts, without implying authenticated ownership."""
    with connect() as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY updated_at DESC, rowid DESC").fetchall()
        counts = dict(db.execute("SELECT task_id, COUNT(*) FROM proposals GROUP BY task_id").fetchall())
    tasks = [task_from_row(row) for row in rows]
    for task in tasks:
        task["proposal_count"] = counts.get(task["id"], 0)
    return tasks


def list_proposals(task_id=None):
    with connect() as db:
        if task_id:
            rows = db.execute("""SELECT p.*, t.name AS team_name, t.skills AS team_skills
                FROM proposals p JOIN teams t ON t.id = p.team_id
                WHERE p.task_id = ? ORDER BY p.created_at DESC""", (task_id,)).fetchall()
        else:
            rows = db.execute("""SELECT p.*, t.name AS team_name, t.skills AS team_skills
                FROM proposals p JOIN teams t ON t.id = p.team_id
                ORDER BY p.created_at DESC""").fetchall()
    return [dict(row) for row in rows]


def seed_demo():
    examples = [
        ("Образование", "Школьникам сложно найти подходящие кружки после уроков.", "Навигатор школьных кружков", "Школа ведёт расписания в разных таблицах.", "Помочь семьям быстро найти подходящий кружок.", "Ученики и родители", "Расписание кружков без персональных данных", "Запуск в одной школе", "Рабочий каталог с записью", "20 тестовых записей", "demo@school.kz", "Онлайн, раз в неделю"),
        ("Общепит", "В столовой образуются длинные очереди в обеденный перерыв.", "Очередь без ожидания", "Пиковая нагрузка с 12 до 14 часов.", "Сократить время ожидания заказа.", "Посетители и кассиры", "Обезличенные времена заказов", "Без замены кассовой системы", "Прототип предзаказа", "Среднее ожидание ниже 7 минут", "demo@cafe.kz", "Онлайн, два созвона"),
        ("Здравоохранение", "Пациенты часто забывают о повторном приёме.", "Напоминания о приёме", "Администратор обзванивает пациентов вручную.", "Снизить количество пропущенных приёмов.", "Пациенты и регистратура", "Синтетическое расписание", "Без медицинских данных", "Прототип напоминаний", "Меньше пропусков на тесте", "demo@clinic.kz", "Онлайн"),
        ("Госуслуги", "Жители не понимают, какие документы брать для обращения.", "Понятный список документов", "Инструкции разбросаны по нескольким страницам.", "Дать точный список до визита.", "Жители и сотрудники центра", "Публичные инструкции", "Только открытые источники", "Поиск по жизненной ситуации", "5 сценариев без ошибок", "demo@city.kz", "Очная консультация"),
        ("Финансы", "Малому бизнесу трудно планировать ежемесячные расходы.", "Прогноз расходов", "Расходы хранятся в таблицах.", "Показать будущий кассовый разрыв.", "Владельцы малого бизнеса", "Синтетические финансовые записи", "Без доступа к банковским счетам", "Дашборд прогноза", "Прогноз на 3 месяца", "demo@finance.kz", "Онлайн"),
    ]
    with DB_LOCK, connect() as db:
        if db.execute("SELECT 1 FROM tasks WHERE id = 'demo-card-1'").fetchone():
            return False
        for index, (topic, raw, *values) in enumerate(examples):
            fields = dict(zip(FIELDS, values))
            for missing in (
                (), ("interaction_format", "contact"),
                ("data", "interaction_format"),
                ("data", "constraints", "users"),
                ("data", "success_criteria", "expected_result", "contact"),
            )[index]:
                fields[missing] = ""
            task_id = f"demo-card-{index + 1}"
            score, _ = score_fields(fields)
            db.execute("INSERT INTO tasks (id, raw_description, topic, fields_json, status, confirmed_score) VALUES (?, ?, ?, ?, 'confirmed', ?)",
                       (task_id, raw, topic, json.dumps(fields, ensure_ascii=False), score))
            db.execute("INSERT INTO tasks (id, raw_description, topic, fields_json) VALUES (?, ?, ?, ?)",
                       (f"demo-draft-{index + 1}", raw, topic, json.dumps({name: "" for name in FIELDS}, ensure_ascii=False)))
            team_id = f"demo-team-{index + 1}"
            db.execute("INSERT INTO teams (id, name, skills) VALUES (?, ?, ?)", (team_id, f"Команда {index + 1}", "Дизайн, разработка, исследование"))
            db.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan, prototype_url) VALUES (?, ?, ?, ?, ?, '')",
                       (f"demo-proposal-{index + 1}", task_id, team_id, f"Сделаем прототип для задачи «{fields['title']}».", "Исследование → прототип → тестирование"))
    return True


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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            return self.serve_file("index.html", "text/html; charset=utf-8")
        if path == "/style.css":
            return self.serve_file("style.css", "text/css; charset=utf-8")
        if path == "/extra.css":
            return self.serve_file("extra.css", "text/css; charset=utf-8")
        if path == "/ai.css":
            return self.serve_file("ai.css", "text/css; charset=utf-8")
        if path == "/workspace.css":
            return self.serve_file("workspace.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self.serve_file("app.js", "text/javascript; charset=utf-8")
        if path == "/api/health":
            return self.json_response(200, {"ok": True, "ai_enabled": bool(os.getenv("OPENAI_API_KEY"))})
        if path == "/api/workspace/tasks":
            return self.json_response(200, list_workspace_tasks())
        if path == "/api/tasks":
            topic = query.get("topic", [""])[0]
            sort = query.get("sort", ["newest"])[0]
            readiness = query.get("readiness", [""])[0]
            if sort not in ("newest", "rating", "readiness") or readiness not in ("", "low", "medium", "high"):
                return self.json_response(400, {"error": "Неизвестный фильтр или сортировка."})
            return self.json_response(200, list_tasks(topic, sort, readiness))
        if path == "/api/proposals":
            return self.json_response(200, list_proposals(query.get("task_id", [None])[0]))
        if path == "/api/teams":
            with connect() as db:
                teams = [dict(row) for row in db.execute("""SELECT t.id, t.name, t.skills, t.created_at,
                    COALESCE(SUM(pr.points), 0) AS points FROM teams t
                    LEFT JOIN proposals p ON p.team_id = t.id
                    LEFT JOIN progress pr ON pr.proposal_id = p.id
                    GROUP BY t.id ORDER BY points DESC, t.name""")]
            return self.json_response(200, teams)
        if path.startswith("/api/proposals/") and path.endswith("/progress"):
            proposal_id = path.split("/")[3]
            with connect() as db:
                rows = db.execute("SELECT * FROM progress WHERE proposal_id = ? ORDER BY created_at DESC", (proposal_id,)).fetchall()
            return self.json_response(200, [dict(row) for row in rows])
        if path.startswith("/api/tasks/"):
            task = get_task(path.rsplit("/", 1)[-1])
            return self.json_response(200 if task else 404, task or {"error": "Задача не найдена."})
        return self.json_response(404, {"error": "Страница не найдена."})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/demo/seed":
                created = seed_demo()
                return self.json_response(200, {"created": created, "tasks": len(list_tasks())})
            if path.startswith("/api/tasks/") and path.endswith("/ai-questions"):
                task_id = path.split("/")[3]
                task = get_task(task_id)
                if not task:
                    return self.json_response(404, {"error": "Задача не найдена."})
                return self.json_response(200, {"questions": ai_questions(task), "source": "openai"})
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
            if path == "/api/teams":
                name = clean_text(data.get("name", ""), 100)
                skills = clean_text(data.get("skills", ""), 500)
                if len(name) < 2:
                    raise ValueError("Укажите название команды.")
                team_id = str(uuid.uuid4())
                with DB_LOCK, connect() as db:
                    db.execute("INSERT INTO teams (id, name, skills) VALUES (?, ?, ?)", (team_id, name, skills))
                return self.json_response(201, {"id": team_id, "name": name, "skills": skills})
            if path == "/api/proposals":
                task_id = clean_text(data.get("task_id", ""), 100)
                team_id = clean_text(data.get("team_id", ""), 100)
                idea = clean_text(data.get("idea", ""))
                plan = clean_text(data.get("plan", ""))
                url = clean_text(data.get("prototype_url", ""), 500)
                if len(idea) < 10 or len(plan) < 10:
                    raise ValueError("Опишите идею и план хотя бы одним предложением.")
                if url and not url.startswith(("https://", "http://")):
                    raise ValueError("Ссылка на прототип должна начинаться с http:// или https://.")
                task = get_task(task_id)
                if not task or task["status"] != "confirmed":
                    return self.json_response(404, {"error": "Опубликованная задача не найдена."})
                proposal_id = str(uuid.uuid4())
                with DB_LOCK, connect() as db:
                    if not db.execute("SELECT 1 FROM teams WHERE id = ?", (team_id,)).fetchone():
                        return self.json_response(404, {"error": "Команда не найдена."})
                    db.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan, prototype_url) VALUES (?, ?, ?, ?, ?, ?)",
                               (proposal_id, task_id, team_id, idea, plan, url))
                return self.json_response(201, {"id": proposal_id})
            if path.startswith("/api/proposals/") and path.endswith("/decision"):
                proposal_id = path.split("/")[3]
                decision = data.get("decision")
                if decision not in ("selected", "rejected", "pending"):
                    raise ValueError("Неизвестное решение.")
                with DB_LOCK, connect() as db:
                    changed = db.execute("UPDATE proposals SET status = ? WHERE id = ?", (decision, proposal_id)).rowcount
                return self.json_response(200 if changed else 404, {"status": decision} if changed else {"error": "Отклик не найден."})
            if path.startswith("/api/proposals/") and path.endswith("/progress"):
                proposal_id = path.split("/")[3]
                description = clean_text(data.get("description", ""))
                if len(description) < 10:
                    raise ValueError("Опишите выполненный этап.")
                with DB_LOCK, connect() as db:
                    proposal = db.execute("SELECT status FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
                    if not proposal or proposal["status"] != "selected":
                        raise ValueError("Этап может отправить только выбранная команда.")
                    progress_id = str(uuid.uuid4())
                    db.execute("INSERT INTO progress (id, proposal_id, description) VALUES (?, ?, ?)", (progress_id, proposal_id, description))
                return self.json_response(201, {"id": progress_id, "status": "pending"})
            if path.startswith("/api/progress/") and path.endswith("/confirm"):
                progress_id = path.split("/")[3]
                with DB_LOCK, connect() as db:
                    changed = db.execute("UPDATE progress SET status = 'confirmed', points = 10 WHERE id = ? AND status = 'pending'", (progress_id,)).rowcount
                return self.json_response(200 if changed else 404, {"status": "confirmed", "points": 10} if changed else {"error": "Этап не найден или уже подтверждён."})
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
            fields = dict(task["fields"])
            for name, value in changes.items():
                fields[name] = clean_text(value)
            if fields == task["fields"]:
                return self.json_response(200, task)
            with DB_LOCK, connect() as db:
                db.execute("UPDATE tasks SET fields_json = ?, status = 'draft', confirmed_score = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                           (json.dumps(fields, ensure_ascii=False), task_id))
            return self.json_response(200, get_task(task_id))
        except ValueError as error:
            return self.json_response(400, {"error": str(error)})


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    print("Миссия 100: http://%s:%d" % (host, port), flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
