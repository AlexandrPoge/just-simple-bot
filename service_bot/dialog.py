"""Handle Telegram questions and short model-clarification dialogs."""

from __future__ import annotations

import logging
import sqlite3
import time

from .audit import AuditLog
from .google_sheets import GoogleSheetError
from .knowledge import FALLBACK, KnowledgeBase, Result
from .telegram_api import TelegramApi
from .text_matching import normalize

LOGGER = logging.getLogger(__name__)
START_MESSAGE = (
    "Здравствуйте! Задайте вопрос по обслуживанию станции. "
    "Я отвечаю только по базе знаний сервисного отдела."
)
HELP_MESSAGE = (
    "Спросите об обслуживании КАН Ультра, периодичности обслуживания КИТ "
    "или переполнении станции. Если информации нет, я направлю вас в сервисный отдел."
)


class DialogState:
    """Store the pending question while awaiting a station model."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self.pending: dict[int, tuple[float, str]] = {}

    def resolve(self, chat_id: int, text: str, kb: KnowledgeBase) -> str:
        previous = self.pending.pop(chat_id, None)
        if previous is None or time.monotonic() - previous[0] > self.ttl_seconds:
            return text

        reply = normalize(text)
        for prefix in ("это ", "станция ", "станцию ", "модель "):
            if reply.startswith(prefix):
                reply = reply[len(prefix) :]
                break

        aliases = {
            alias for article in kb.load() for alias in article.equipment_aliases
        }
        return previous[1] + " " + reply if reply in aliases else text

    def remember(self, chat_id: int, text: str) -> None:
        if len(self.pending) >= 1000:
            self.pending.clear()
        self.pending[chat_id] = (time.monotonic(), text)


def process_message(
    message: dict,
    api: TelegramApi,
    kb: KnowledgeBase,
    audit: AuditLog,
    dialog: DialogState,
) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return

    text = message.get("text")
    if not isinstance(text, str):
        api.call("sendMessage", {"chat_id": chat_id, "text": FALLBACK})
        return

    words = text.split(maxsplit=1)
    command = words[0].split("@", 1)[0] if words else ""
    if command == "/start":
        dialog.pending.pop(chat_id, None)
        api.call("sendMessage", {"chat_id": chat_id, "text": START_MESSAGE})
        return
    if command == "/help":
        dialog.pending.pop(chat_id, None)
        api.call("sendMessage", {"chat_id": chat_id, "text": HELP_MESSAGE})
        return
    if text.startswith("/"):
        return

    resolved_question = text
    try:
        resolved_question = dialog.resolve(chat_id, text, kb)
        result = kb.answer(resolved_question)
    except (OSError, ValueError, GoogleSheetError):
        LOGGER.exception("База знаний недоступна или некорректна")
        result = Result(FALLBACK, None, "needs_human")

    if result.status == "needs_clarification":
        dialog.remember(chat_id, resolved_question)
    api.call("sendMessage", {"chat_id": chat_id, "text": result.answer})

    try:
        audit.record(chat_id, resolved_question, result)
    except sqlite3.Error:
        LOGGER.exception("Не удалось записать обращение в журнал")
