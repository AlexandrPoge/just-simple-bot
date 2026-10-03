"""Loopback-only HTTP server for editing the knowledge base."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .admin_views import esc, form_page, index_page, page
from .google_sheets import GoogleSheetError
from .store import FIELDS, ArticleStore


def create_server(
    source: Path | object, audit_path: Path, port: int = 8765
) -> ThreadingHTTPServer:
    store = ArticleStore(source) if isinstance(source, Path) else source
    csrf_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if host not in allowed:
                self._send(
                    HTTPStatus.FORBIDDEN,
                    page("Доступ запрещён", "<h1>Недоступный адрес</h1>"),
                )
                return False
            return True

        def _send(
            self, status: HTTPStatus, body: bytes, location: str | None = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
            )
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
                    saved = parse_qs(parsed.query).get("saved", [""])[0]
                    self._index(saved)
                elif parsed.path == "/articles/new":
                    self._form({field: "" for field in FIELDS}, "")
                elif parsed.path.startswith("/articles/") and parsed.path.endswith(
                    "/edit"
                ):
                    article_id = unquote(parsed.path[len("/articles/") : -len("/edit")])
                    row = next(
                        (item for item in store.all() if item["id"] == article_id),
                        None,
                    )
                    if row is None:
                        self._send(
                            HTTPStatus.NOT_FOUND,
                            page("Не найдено", "<h1>Статья не найдена</h1>"),
                        )
                    else:
                        self._form(row, article_id)
                else:
                    self._send(
                        HTTPStatus.NOT_FOUND,
                        page("Не найдено", "<h1>Страница не найдена</h1>"),
                    )
            except (OSError, ValueError, sqlite3.Error, GoogleSheetError) as error:
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    page("Ошибка", f"<h1>Ошибка</h1><p>{esc(error)}</p>"),
                )

        def _index(self, saved: str) -> None:
            questions = []
            if audit_path.exists():
                with sqlite3.connect(audit_path) as connection:
                    questions = connection.execute(
                        "SELECT created_at, question FROM questions WHERE status = ? "
                        "ORDER BY id DESC LIMIT 20",
                        ("needs_human",),
                    ).fetchall()

            self._send(HTTPStatus.OK, index_page(store.all(), saved, questions))

        def _form(self, row: dict[str, str], original_id: str, error: str = "") -> None:
            status = HTTPStatus.BAD_REQUEST if error else HTTPStatus.OK
            self._send(status, form_page(row, original_id, csrf_token, error))

        def do_POST(self) -> None:
            if not self._host_allowed():
                return
            if self.path != "/articles/save":
                self._send(
                    HTTPStatus.NOT_FOUND,
                    page("Не найдено", "<h1>Страница не найдена</h1>"),
                )
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 50_000:
                    raise ValueError("Недопустимый размер формы")

                fields = parse_qs(
                    self.rfile.read(length).decode("utf-8"), keep_blank_values=True
                )
                if fields.get("csrf", [""])[0] != csrf_token:
                    self._send(
                        HTTPStatus.FORBIDDEN,
                        page("Доступ запрещён", "<h1>Недействительная форма</h1>"),
                    )
                    return

                values = {field: fields.get(field, [""])[0] for field in FIELDS}
                original_id = fields.get("original_id", [""])[0]
                expected_revision = fields.get("revision", [""])[0]
                try:
                    article_id = store.save(values, original_id, expected_revision)
                except ValueError as error:
                    self._form(values, original_id, str(error))
                    return

                self._send(HTTPStatus.SEE_OTHER, b"", "/?saved=" + quote(article_id))
            except (OSError, ValueError, UnicodeError, GoogleSheetError) as error:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    page("Ошибка", f"<h1>Ошибка формы</h1><p>{esc(error)}</p>"),
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def start_admin(
    source: Path | object, audit_path: Path, port: int = 8765
) -> ThreadingHTTPServer:
    server = create_server(source, audit_path, port)
    threading.Thread(
        target=server.serve_forever, name="knowledge-admin", daemon=True
    ).start()
    return server
