"""Validated, atomic updates to the operator-owned CSV knowledge base."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from .knowledge import KnowledgeBase


FIELDS = (
    "id", "status", "equipment_aliases", "topic_terms", "exclude_terms",
    "question_examples", "answer",
)
STATUSES = {"draft", "published", "archived"}
ARTICLE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def revision(row: dict[str, str]) -> str:
    payload = json.dumps({field: row.get(field, "") for field in FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_article(values: dict[str, str]) -> dict[str, str]:
    article = {field: values.get(field, "").strip() for field in FIELDS}
    if not ARTICLE_ID.fullmatch(article["id"]):
        raise ValueError("ID: латинские строчные буквы, цифры, _ или -, от 2 до 64 символов")
    if article["status"] not in STATUSES:
        raise ValueError("Выберите корректный статус")
    if article["status"] == "published" and (
        not article["answer"] or not article["topic_terms"]
    ):
        raise ValueError("Для публикации нужны официальный ответ и слова темы")
    if any(len(value) > 4000 for value in article.values()):
        raise ValueError("Поле статьи слишком длинное")
    return article


class ArticleStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def all(self) -> list[dict[str, str]]:
        with self.path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None or set(reader.fieldnames) != set(FIELDS):
                raise ValueError("Некорректные колонки базы знаний")
            rows = list(reader)
        for row in rows:
            if any(value is None for value in row.values()):
                raise ValueError("Некорректная строка базы знаний")
        return rows

    def save(self, values: dict[str, str], original_id: str = "", expected_revision: str = "") -> str:
        article = validate_article(values)

        with self._lock:
            rows = self.all()
            ids = {row["id"] for row in rows}
            if original_id:
                if original_id not in ids:
                    raise ValueError("Редактируемая статья не найдена")
                if article["id"] != original_id:
                    raise ValueError("ID существующей статьи менять нельзя")
                old = next(row for row in rows if row["id"] == original_id)
                if expected_revision and revision(old) != expected_revision:
                    raise ValueError("Статья изменилась. Обновите страницу перед сохранением")
                rows = [article if row["id"] == original_id else row for row in rows]
            else:
                if article["id"] in ids:
                    raise ValueError("Статья с таким ID уже существует")
                rows.append(article)

            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", newline="", encoding="utf-8", dir=self.path.parent,
                    prefix=".articles-", suffix=".csv", delete=False,
                ) as target:
                    temporary_path = Path(target.name)
                    writer = csv.DictWriter(target, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                    target.flush()
                    os.fsync(target.fileno())
                KnowledgeBase(temporary_path).load()
                os.replace(temporary_path, self.path)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
        return article["id"]
