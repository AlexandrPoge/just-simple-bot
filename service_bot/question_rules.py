"""Apply safety checks before selecting an approved answer."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .text_matching import contains_equipment, contains_term, word_matches

if TYPE_CHECKING:
    from .knowledge import Article


MODEL_CONNECTORS = {
    "и",
    "а",
    "как",
    "что",
    "когда",
    "при",
    "после",
    "до",
    "для",
    "без",
    "на",
    "в",
    "с",
}


def mentions_article_model(question: str, article: Article) -> bool:
    return bool(article.equipment_aliases) and any(
        contains_equipment(question, alias) for alias in article.equipment_aliases
    )


def _looks_like_intent(word: str, articles: list[Article]) -> bool:
    return word in MODEL_CONNECTORS or any(
        word_matches(word, term.split()[0], allow_typo=True)
        for article in articles
        for term in article.topic_terms
    )


def _mentions_unknown_model_after_station(
    words: list[str], articles: list[Article]
) -> bool:
    model_starts = {
        alias.split()[0] for article in articles for alias in article.equipment_aliases
    }
    for index, word in enumerate(words[:-1]):
        if word.startswith("станц") and words[index + 1] not in (
            model_starts | MODEL_CONNECTORS
        ):
            return True
    return False


def _joins_another_model(words: list[str], articles: list[Article]) -> bool:
    for article in articles:
        for alias in article.equipment_aliases:
            parts = alias.split()
            for index in range(len(words) - len(parts) + 1):
                if words[index : index + len(parts)] != parts:
                    continue

                if (
                    index >= 2
                    and words[index - 1] == "и"
                    and not _looks_like_intent(words[index - 2], articles)
                ):
                    return True

                if (
                    index + len(parts) + 1 >= len(words)
                    or words[index + len(parts)] != "и"
                ):
                    continue

                next_word = words[index + len(parts) + 1]
                if not _looks_like_intent(next_word, articles):
                    return True
    return False


def conflicting_model_reference(question: str, articles: list[Article]) -> bool:
    """Reject a second model named next to 'station' or joined to a known model."""
    words = question.split()
    if "или" in words or "либо" in words:
        return True

    known_model_present = any(
        contains_equipment(question, alias)
        for article in articles
        for alias in article.equipment_aliases
    )
    if known_model_present and _mentions_unknown_model_after_station(words, articles):
        return True

    return _joins_another_model(words, articles)


def negated_topic(question: str, article: Article) -> bool:
    words = question.split()
    for index, word in enumerate(words):
        topic_mentioned = any(
            word_matches(word, term.split()[0], allow_typo=True)
            for term in article.topic_terms
        )
        if topic_mentioned and "не" in words[max(0, index - 3) : index]:
            return True
    return False


def article_matches(question: str, article: Article) -> bool:
    if article.equipment_aliases and not mentions_article_model(question, article):
        return False

    topic_matches = question in article.question_examples or any(
        contains_term(question, term, allow_typo=True) for term in article.topic_terms
    )
    if not topic_matches:
        return False

    if any(contains_term(question, term) for term in article.exclude_terms):
        return False

    return not (article.equipment_aliases and negated_topic(question, article))


def should_clarify_model(question: str, articles: list[Article]) -> bool:
    if not re.search(r"\bстанц\w*(?: самостоятельно)?$", question):
        return False

    return any(
        article.equipment_aliases
        and any(
            contains_term(question, term, allow_typo=True)
            for term in article.topic_terms
        )
        and not any(contains_term(question, term) for term in article.exclude_terms)
        for article in articles
    )
