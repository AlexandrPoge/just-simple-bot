"""Load published articles and return only their approved answers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .question_rules import (
    article_matches,
    conflicting_model_reference,
    mentions_article_model,
    should_clarify_model,
)
from .text_matching import contains_equipment as contains_equipment
from .text_matching import normalize, split_terms

FALLBACK = (
    "В моей базе знаний нет информации по этому вопросу. "
    "Рекомендую обратиться в сервисный отдел компании для получения точной консультации."
)
CLARIFY_MODEL = "Уточните модель станции, чтобы я проверил информацию в базе знаний."


@dataclass(frozen=True)
class Article:
    id: str
    equipment_aliases: tuple[str, ...]
    topic_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...]
    question_examples: tuple[str, ...]
    answer: str


@dataclass(frozen=True)
class Result:
    answer: str
    article_id: str | None
    status: str


class KnowledgeBase:
    REQUIRED: ClassVar[set[str]] = {
        "id",
        "status",
        "equipment_aliases",
        "topic_terms",
        "exclude_terms",
        "question_examples",
        "answer",
    }

    def __init__(self, source: Path | object):
        self.source = source

    def load(self) -> list[Article]:
        if isinstance(self.source, Path):
            with self.source.open(newline="", encoding="utf-8-sig") as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames or not self.REQUIRED.issubset(
                    reader.fieldnames
                ):
                    raise ValueError("В базе знаний отсутствуют обязательные колонки")
                rows = list(reader)
        else:
            rows = self.source.all()

        articles = []
        seen_ids = set()
        for row in rows:
            status = (row["status"] or "").strip().casefold()
            if status not in {"draft", "published", "archived"}:
                raise ValueError("Недопустимый статус статьи")

            article_id = (row["id"] or "").strip()
            if not article_id or article_id in seen_ids:
                raise ValueError("Пустой или повторяющийся ID статьи")
            seen_ids.add(article_id)

            if status != "published":
                continue

            answer = (row["answer"] or "").strip()
            topic_terms = split_terms(row["topic_terms"] or "")
            if not answer or not topic_terms:
                raise ValueError(f"Опубликованная статья {article_id} неполная")

            articles.append(
                Article(
                    id=article_id,
                    equipment_aliases=split_terms(row["equipment_aliases"] or ""),
                    topic_terms=topic_terms,
                    exclude_terms=split_terms(row["exclude_terms"] or ""),
                    question_examples=split_terms(row["question_examples"] or ""),
                    answer=answer,
                )
            )
        return articles

    def answer(self, question: str) -> Result:
        text = normalize(question)
        if not text:
            return Result(FALLBACK, None, "needs_human")

        # Reload on every question so approved edits take effect immediately.
        articles = self.load()
        mentioned_equipment = {
            article.id for article in articles if mentions_article_model(text, article)
        }

        if len(mentioned_equipment) > 1:
            return Result(FALLBACK, None, "needs_human")
        if mentioned_equipment and conflicting_model_reference(text, articles):
            return Result(FALLBACK, None, "needs_human")

        candidates = [article for article in articles if article_matches(text, article)]
        if len(candidates) == 1:
            article = candidates[0]
            return Result(article.answer, article.id, "answered")

        if not mentioned_equipment and should_clarify_model(text, articles):
            return Result(CLARIFY_MODEL, None, "needs_clarification")
        return Result(FALLBACK, None, "needs_human")
