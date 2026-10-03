"""HTML views for the local knowledge base editor."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote

from .store import FIELDS, revision

LABELS = {
    "id": "ID статьи",
    "status": "Статус",
    "equipment_aliases": "Названия оборудования",
    "topic_terms": "Слова темы",
    "exclude_terms": "Исключающие слова",
    "question_examples": "Варианты вопросов",
    "answer": "Официальный ответ",
}
HINTS = {
    "equipment_aliases": (
        "Название модели обязательно должно быть в вопросе. "
        "Варианты разделяйте знаком |."
    ),
    "topic_terms": "Слова или начала слов через |: например, почист|обслуж|инструкц.",
    "question_examples": (
        "Точные варианты вопросов через |. Регистр и знаки препинания не важны."
    ),
}
TEXT_FIELDS = {
    "answer",
    "question_examples",
    "topic_terms",
    "exclude_terms",
    "equipment_aliases",
}
STYLESHEET = Path(__file__).with_name("admin.css").read_text(encoding="utf-8")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, content: str) -> bytes:
    markup = f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)} · База знаний</title>
    <style>{STYLESHEET}</style>
</head>
<body>
    <header><a href="/">База знаний сервисного бота</a></header>
    <main>{content}</main>
    <footer>Редактор доступен только на этом компьютере</footer>
</body>
</html>"""
    return markup.encode("utf-8")


def article_card(row: dict[str, str]) -> str:
    status = row["status"]
    answer_preview = esc(row["answer"][:180]) or "Ответ ещё не добавлен"
    edit_url = f"/articles/{quote(row['id'])}/edit"

    return f"""
<div class="card">
    <div class="bar">
        <strong>{esc(row["id"])}</strong>
        <span class="badge {esc(status)}">{esc(status)}</span>
    </div>
    <p>{answer_preview}</p>
    <a href="{edit_url}">Редактировать статью →</a>
</div>"""


def question_card(created_at: str, question: str) -> str:
    return f"""
<div class="card">
    <small>{esc(created_at)}</small>
    <p class="question">{esc(question)}</p>
</div>"""


def index_page(
    rows: list[dict[str, str]], saved: str, questions: list[tuple[str, str]]
) -> bytes:
    cards_html = "".join(article_card(row) for row in rows)
    notice_html = (
        f'<p class="ok">Статья {esc(saved)} сохранена. Изменения доступны боту сразу.</p>'
        if saved
        else ""
    )
    queue_html = (
        "".join(
            question_card(created_at, question) for created_at, question in questions
        )
        or '<p class="muted">Пока нет вопросов для разбора.</p>'
    )

    content = f"""
<div class="bar">
    <div>
        <h1>Статьи базы знаний</h1>
        <p class="muted">Бот отвечает только по опубликованным статьям.</p>
    </div>
    <a class="button" href="/articles/new">+ Добавить статью</a>
</div>
{notice_html}
{cards_html}
<h2>Вопросы без ответа</h2>
{queue_html}"""
    return page("Статьи", content)


def form_field(field: str, value: str, *, editing: bool) -> str:
    label = f'<label for="{field}">{LABELS[field]}</label>'

    if field == "status":
        options = "".join(
            f'<option value="{option}" {"selected" if option == value else ""}>'
            f"{option}</option>"
            for option in ("draft", "published", "archived")
        )
        control = f'<select id="{field}" name="{field}">{options}</select>'
    elif field in TEXT_FIELDS:
        css_class = "answer" if field == "answer" else ""
        control = (
            f'<textarea id="{field}" name="{field}" class="{css_class}">'
            f"{esc(value)}</textarea>"
        )
    else:
        attribute = "readonly" if editing else "required"
        control = (
            f'<input id="{field}" name="{field}" value="{esc(value)}" {attribute}>'
        )

    hint = f"<small>{HINTS[field]}</small>" if field in HINTS else ""
    return f"{label}\n{control}\n{hint}"


def form_page(
    row: dict[str, str], original_id: str, csrf_token: str, error: str = ""
) -> bytes:
    title = "Редактировать статью" if original_id else "Новая статья"
    fields_html = "\n".join(
        form_field(field, row[field], editing=bool(original_id)) for field in FIELDS
    )
    warning_html = f'<p class="error">{esc(error)}</p>' if error else ""
    current_revision = revision(row) if original_id else ""

    content = f"""
<a href="/">← К списку</a>
<h1>{title}</h1>
{warning_html}
<p class="muted">
    Сначала сохраните статью как draft, проверьте ответ, затем выберите published.
</p>
<form method="post" action="/articles/save">
    <input type="hidden" name="csrf" value="{csrf_token}">
    <input type="hidden" name="original_id" value="{esc(original_id)}">
    <input type="hidden" name="revision" value="{current_revision}">
    {fields_html}
    <p><button type="submit">Сохранить статью</button></p>
</form>"""
    return page(title, content)
