"""Normalize questions and match words against approved search terms."""

from __future__ import annotations

import re


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
    return any(shorter == longer[:i] + longer[i + 1 :] for i in range(len(longer)))


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
    """Find an operator-defined word beginning or phrase in a question."""
    words = question.split()
    parts = term.split()

    if len(parts) == 1:
        return any(word_matches(word, term, allow_typo=allow_typo) for word in words)

    return any(
        all(
            word_matches(words[index + offset], part, allow_typo=allow_typo)
            for offset, part in enumerate(parts)
        )
        for index in range(len(words) - len(parts) + 1)
    )


def contains_equipment(question: str, alias: str) -> bool:
    """Match a model name, allowing one typo only in long words."""
    words = question.split()
    parts = alias.split()

    return any(
        all(
            word == part or (len(part) >= 5 and one_typo(word, part))
            for word, part in zip(words[index : index + len(parts)], parts)
        )
        for index in range(len(words) - len(parts) + 1)
    )
