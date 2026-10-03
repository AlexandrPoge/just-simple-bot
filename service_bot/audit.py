"""Local audit log for unanswered and answered questions."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .knowledge import Result


class AuditLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS questions ("
            "id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, chat_id INTEGER NOT NULL, "
            "question TEXT NOT NULL, status TEXT NOT NULL, article_id TEXT)"
        )
        self.connection.commit()

    def record(self, chat_id: int, question: str, result: Result) -> None:
        self.connection.execute(
            "INSERT INTO questions (created_at, chat_id, question, status, article_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                chat_id,
                question,
                result.status,
                result.article_id,
            ),
        )
        self.connection.commit()
