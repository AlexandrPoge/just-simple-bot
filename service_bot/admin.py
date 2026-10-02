"""Loopback-only knowledge base editor for a local demonstration."""

from __future__ import annotations

import html
import secrets
import sqlite3
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .google_sheets import GoogleSheetError
from .store import ArticleStore, FIELDS, revision


LABELS = {
    "id": "ID статьи",
    "status": "Статус",
    "equipment_aliases": "Названия оборудования",
    "topic_terms": "Слова темы",
    "exclude_terms": "Исключающие слова",
    "question_examples": "Варианты вопросов",
    "answer": "Официальный ответ",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, content: str) -> bytes:
    markup = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · База знаний</title><style>
:root{{font-family:system-ui,-apple-system,sans-serif;color:#18312b;background:#f4f7f4}}
*{{box-sizing:border-box}}body{{margin:0}}header{{background:#123b32;color:white;padding:18px 5%}}
header a{{color:white;text-decoration:none;font-weight:700}}main{{max-width:980px;margin:32px auto;padding:0 20px}}
h1{{font-size:2rem}}h2{{margin-top:36px}}.muted{{color:#5e7169}}.bar{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
.button,button{{background:#126c4d;color:white;border:0;border-radius:9px;padding:11px 16px;text-decoration:none;font:inherit;cursor:pointer}}
.card{{background:white;border:1px solid #dbe5df;border-radius:14px;padding:20px;margin:12px 0;box-shadow:0 3px 12px #123b3209}}
.card a{{color:#126c4d}}.badge{{font-size:.8rem;background:#e5f3ec;border-radius:20px;padding:4px 9px}}
.badge.draft{{background:#fff1d8}}.badge.archived{{background:#e9eceb}}label{{display:block;font-weight:650;margin:18px 0 6px}}
input,textarea,select{{width:100%;border:1px solid #b9ccc2;border-radius:8px;padding:10px;font:inherit;background:white}}
textarea{{min-height:90px}}textarea.answer{{min-height:150px}}small{{display:block;color:#5e7169;margin-top:5px}}
.error{{background:#fff0e8;border-left:4px solid #bc5d37;padding:12px;border-radius:6px}}.ok{{background:#e5f3ec;padding:12px;border-radius:6px}}
.question{{white-space:pre-wrap;overflow-wrap:anywhere}}footer{{color:#5e7169;text-align:center;padding:36px}}
</style></head><body><header><a href="/">База знаний сервисного бота</a></header>
<main>{content}</main><footer>Редактор доступен только на этом компьютере</footer></body></html>"""
    return markup.encode("utf-8")


def create_server(source: Path | object, audit_path: Path, port: int = 8765) -> ThreadingHTTPServer:
    store = ArticleStore(source) if isinstance(source, Path) else source
    csrf_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                self._send(HTTPStatus.FORBIDDEN, page("Доступ запрещён", "<h1>Недоступный адрес</h1>"))
                return False
            return True

        def _send(self, status: HTTPStatus, body: bytes, location: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._host_allowed():
                return
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._index(parse_qs(parsed.query).get("saved", [""])[0])
                elif parsed.path == "/articles/new":
                    self._form({field: "" for field in FIELDS}, "")
                elif parsed.path.startswith("/articles/") and parsed.path.endswith("/edit"):
                    article_id = unquote(parsed.path[len("/articles/"):-len("/edit")])
                    row = next((item for item in store.all() if item["id"] == article_id), None)
                    if row is None:
                        self._send(HTTPStatus.NOT_FOUND, page("Не найдено", "<h1>Статья не найдена</h1>"))
                    else:
                        self._form(row, article_id)
                else:
                    self._send(HTTPStatus.NOT_FOUND, page("Не найдено", "<h1>Страница не найдена</h1>"))
            except (OSError, ValueError, sqlite3.Error, GoogleSheetError) as error:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, page("Ошибка", f"<h1>Ошибка</h1><p>{esc(error)}</p>"))

        def _index(self, saved: str) -> None:
            rows = store.all()
            cards = []
            for row in rows:
                status = row["status"]
                cards.append(
                    f'<div class="card"><div class="bar"><strong>{esc(row["id"])}</strong>'
                    f'<span class="badge {esc(status)}">{esc(status)}</span></div>'
                    f'<p>{esc(row["answer"][:180]) or "Ответ ещё не добавлен"}</p>'
                    f'<a href="/articles/{quote(row["id"])}/edit">Редактировать статью →</a></div>'
                )
            notices = f'<p class="ok">Статья {esc(saved)} сохранена. Изменения доступны боту сразу.</p>' if saved else ""
            questions = []
            if audit_path.exists():
                with sqlite3.connect(audit_path) as connection:
                    questions = connection.execute(
                        "SELECT created_at, question FROM questions WHERE status = ? "
                        "ORDER BY id DESC LIMIT 20", ("needs_human",),
                    ).fetchall()
            queue = "".join(
                f'<div class="card"><small>{esc(created_at)}</small><p class="question">{esc(question)}</p></div>'
                for created_at, question in questions
            ) or '<p class="muted">Пока нет вопросов для разбора.</p>'
            content = (
                '<div class="bar"><div><h1>Статьи базы знаний</h1><p class="muted">'
                'Бот отвечает только по опубликованным статьям.</p></div>'
                '<a class="button" href="/articles/new">+ Добавить статью</a></div>'
                + notices + "".join(cards) + '<h2>Вопросы без ответа</h2>' + queue
            )
            self._send(HTTPStatus.OK, page("Статьи", content))

        def _form(self, row: dict[str, str], original_id: str, error: str = "") -> None:
            title = "Редактировать статью" if original_id else "Новая статья"
            fields = []
            for field in FIELDS:
                value = row[field]
                if field == "status":
                    options = "".join(
                        f'<option value="{option}" {"selected" if option == value else ""}>{option}</option>'
                        for option in ("draft", "published", "archived")
                    )
                    fields.append(f'<label for="{field}">{LABELS[field]}</label><select id="{field}" name="{field}">{options}</select>')
                elif field in {"answer", "question_examples", "topic_terms", "exclude_terms", "equipment_aliases"}:
                    fields.append(
                        f'<label for="{field}">{LABELS[field]}</label><textarea id="{field}" name="{field}" '
                        f'class="{"answer" if field == "answer" else ""}">{esc(value)}</textarea>'
                    )
                else:
                    readonly = "readonly" if original_id else "required"
                    fields.append(f'<label for="{field}">{LABELS[field]}</label><input id="{field}" name="{field}" value="{esc(value)}" {readonly}>')
                if field == "equipment_aliases":
                    fields.append("<small>Название модели обязательно должно быть в вопросе. Варианты разделяйте знаком |.</small>")
                elif field == "topic_terms":
                    fields.append("<small>Слова или начала слов через |: например, почист|обслуж|инструкц.</small>")
                elif field == "question_examples":
                    fields.append("<small>Точные варианты вопросов через |. Регистр и знаки препинания не важны.</small>")
            warning = f'<p class="error">{esc(error)}</p>' if error else ""
            content = (
                f'<a href="/">← К списку</a><h1>{title}</h1>{warning}'
                '<p class="muted">Сначала сохраните статью как draft, проверьте ответ, затем выберите published.</p>'
                '<form method="post" action="/articles/save">'
                f'<input type="hidden" name="csrf" value="{csrf_token}">'
                f'<input type="hidden" name="original_id" value="{esc(original_id)}">'
                f'<input type="hidden" name="revision" value="{revision(row) if original_id else ""}">'
                + "".join(fields) + '<p><button type="submit">Сохранить статью</button></p></form>'
            )
            self._send(HTTPStatus.OK if not error else HTTPStatus.BAD_REQUEST, page(title, content))

        def do_POST(self) -> None:
            if not self._host_allowed():
                return
            if self.path != "/articles/save":
                self._send(HTTPStatus.NOT_FOUND, page("Не найдено", "<h1>Страница не найдена</h1>"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 50_000:
                    raise ValueError("Недопустимый размер формы")
                fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
                if fields.get("csrf", [""])[0] != csrf_token:
                    self._send(HTTPStatus.FORBIDDEN, page("Доступ запрещён", "<h1>Недействительная форма</h1>"))
                    return
                values = {field: fields.get(field, [""])[0] for field in FIELDS}
                original_id = fields.get("original_id", [""])[0]
                expected_revision = fields.get("revision", [""])[0]
                try:
                    article_id = store.save(values, original_id, expected_revision)
                except ValueError as error:
                    self._form(values, original_id, str(error))
                    return
                location = "/?saved=" + quote(article_id)
                self._send(HTTPStatus.SEE_OTHER, b"", location)
            except (OSError, ValueError, UnicodeError, GoogleSheetError) as error:
                self._send(HTTPStatus.BAD_REQUEST, page("Ошибка", f"<h1>Ошибка формы</h1><p>{esc(error)}</p>"))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def start_admin(source: Path | object, audit_path: Path, port: int = 8765) -> ThreadingHTTPServer:
    server = create_server(source, audit_path, port)
    threading.Thread(target=server.serve_forever, name="knowledge-admin", daemon=True).start()
    return server
