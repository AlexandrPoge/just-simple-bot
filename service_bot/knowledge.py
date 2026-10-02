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
CLARIFY_MODEL = "Уточните модель станции, чтобы я проверил информацию в базе знаний."


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold().replace("ё", "е")))


def split_terms(value: str) -> tuple[str, ...]:
    return tuple(term for item in value.split("|") if (term := normalize(item)))


def one_typo(left: str, right: str) -> bool:
    """Allow one substitution, insertion, deletion or adjacent transposition."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    shorter, longer = sorted((left, right), key=len)
    return any(shorter == longer[:i] + longer[i + 1:] for i in range(len(longer)))


def word_matches(word: str, stem: str, *, allow_typo: bool = False) -> bool:
    if word.startswith(stem):
        return True
    if not allow_typo or len(stem) < 5:
        return False
    return any(
        one_typo(word[:length], stem)
        for length in (len(stem) - 1, len(stem), len(stem) + 1)
        if length <= len(word)
    )


def contains_term(question: str, term: str, *, allow_typo: bool = False) -> bool:
    # Terms are operator-defined word beginnings or complete phrases.
    words = question.split()
    parts = term.split()
    if len(parts) == 1:
        return any(word_matches(word, term, allow_typo=allow_typo) for word in words)
    return any(
        all(word_matches(words[index + offset], part, allow_typo=allow_typo) for offset, part in enumerate(parts))
        for index in range(len(words) - len(parts) + 1)
    )


def contains_equipment(question: str, alias: str) -> bool:
    words = question.split()
    parts = alias.split()
    return any(
        all(
            word == part or (len(part) >= 5 and one_typo(word, part))
            for word, part in zip(words[index:index + len(parts)], parts)
        )
        for index in range(len(words) - len(parts) + 1)
    )


def conflicting_model_reference(question: str, articles: list[Article]) -> bool:
    """Reject a second model named next to 'station' or joined to a known model."""
    words = question.split()
    if "или" in words or "либо" in words:
        return True
    model_starts = {
        alias.split()[0]
        for article in articles for alias in article.equipment_aliases
    }
    connectors = {"и", "а", "как", "что", "когда", "при", "после", "до", "для", "без", "на", "в", "с"}

    def intent_word(word: str) -> bool:
        return word in connectors or any(
            word_matches(word, term.split()[0], allow_typo=True)
            for item in articles for term in item.topic_terms
        )

    for index, word in enumerate(words[:-1]):
        if word.startswith("станц") and words[index + 1] not in model_starts | connectors:
            # An unknown name after 'station' must not inherit another model's article.
            if any(contains_equipment(question, alias) for article in articles for alias in article.equipment_aliases):
                return True
    for article in articles:
        for alias in article.equipment_aliases:
            parts = alias.split()
            for index in range(len(words) - len(parts) + 1):
                if words[index:index + len(parts)] != parts:
                    continue
                if index >= 2 and words[index - 1] == "и" and not intent_word(words[index - 2]):
                    return True
                if index + len(parts) + 1 >= len(words) or words[index + len(parts)] != "и":
                    continue
                next_word = words[index + len(parts) + 1]
                if intent_word(next_word):
                    continue
                return True
    return False


def negated_topic(question: str, article: Article) -> bool:
    words = question.split()
    for index, word in enumerate(words):
        if any(word_matches(word, term.split()[0], allow_typo=True) for term in article.topic_terms):
            if "не" in words[max(0, index - 3):index]:
                return True
    return False


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
        mentioned_equipment = {
            article.id for article in articles
            if article.equipment_aliases and any(
                contains_equipment(text, alias) for alias in article.equipment_aliases
            )
        }
        # Never use an article for one model when another known model is also named.
        if len(mentioned_equipment) > 1:
            return Result(FALLBACK, None, "needs_human")
        if mentioned_equipment and conflicting_model_reference(text, articles):
            return Result(FALLBACK, None, "needs_human")
        candidates = []
        for article in articles:
            if article.equipment_aliases and not any(
                contains_equipment(text, alias) for alias in article.equipment_aliases
            ):
                continue
            if not (
                text in article.question_examples
                or any(contains_term(text, term, allow_typo=True) for term in article.topic_terms)
            ):
                continue
            if any(contains_term(text, term) for term in article.exclude_terms):
                continue
            if article.equipment_aliases and negated_topic(text, article):
                continue
            candidates.append(article)
        # An ambiguous question is sent to a human instead of selecting arbitrarily.
        if len(candidates) != 1:
            # A model-free maintenance question is ambiguous, not a request for
            # instructions about a particular station. Ask, then match again.
            if (
                not mentioned_equipment
                and re.search(r"\bстанц\w*(?: самостоятельно)?$", text)
                and any(
                    article.equipment_aliases
                    and any(contains_term(text, term, allow_typo=True) for term in article.topic_terms)
                    and not any(contains_term(text, term) for term in article.exclude_terms)
                    for article in articles
                )
            ):
                return Result(CLARIFY_MODEL, None, "needs_clarification")
            return Result(FALLBACK, None, "needs_human")
        article = candidates[0]
        return Result(article.answer, article.id, "answered")
