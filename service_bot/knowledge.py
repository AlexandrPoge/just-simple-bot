"""Strict retrieval of approved answers from the configured knowledge source."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


FALLBACK = (
    "В моей базе знаний нет информации по этому вопросу. "
    "Рекомендую обратиться в сервисный отдел компании для получения точной консультации."
)


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold().replace("ё", "е")))


def split_terms(value: str) -> tuple[str, ...]:
    return tuple(term for item in value.split("|") if (term := normalize(item)))


def contains_term(question: str, term: str) -> bool:
    # Terms are operator-defined word beginnings or complete phrases.
    words = question.split()
    parts = term.split()
    if len(parts) == 1:
        return any(word.startswith(term) for word in words)
    return any(
        all(words[index + offset].startswith(part) for offset, part in enumerate(parts))
        for index in range(len(words) - len(parts) + 1)
    )


def contains_equipment(question: str, alias: str) -> bool:
    words = question.split()
    parts = alias.split()
    return any(words[index:index + len(parts)] == parts for index in range(len(words) - len(parts) + 1))


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
    REQUIRED = {
        "id", "status", "equipment_aliases", "topic_terms",
        "exclude_terms", "question_examples", "answer",
    }

    def __init__(self, source: Path | object):
        self.source = source

    def load(self) -> list[Article]:
        if isinstance(self.source, Path):
            with self.source.open(newline="", encoding="utf-8-sig") as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames or not self.REQUIRED.issubset(reader.fieldnames):
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
        articles = self.load()  # Source changes take effect on the next question.
        candidates = []
        for article in articles:
            if article.equipment_aliases and not any(
                contains_equipment(text, alias) for alias in article.equipment_aliases
            ):
                continue
            if not (
                text in article.question_examples
                or any(contains_term(text, term) for term in article.topic_terms)
            ):
                continue
            if any(contains_term(text, term) for term in article.exclude_terms):
                continue
            candidates.append(article)
        # An ambiguous question is sent to a human instead of selecting arbitrarily.
        if len(candidates) != 1:
            return Result(FALLBACK, None, "needs_human")
        article = candidates[0]
        return Result(article.answer, article.id, "answered")
