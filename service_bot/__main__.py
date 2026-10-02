"""Minimal Telegram polling adapter using the standard library."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .audit import AuditLog
from .admin import start_admin
from .google_sheets import GoogleSheetError, GoogleSheetStore, authorized_session
from .knowledge import FALLBACK, KnowledgeBase, Result
from .store import ArticleStore


ROOT = Path(__file__).resolve().parents[1]


def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def path_from_config(key: str, default: str) -> Path:
    path = Path(os.environ.get(key, default))
    return path if path.is_absolute() else ROOT / path


class TelegramApi:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, data: dict) -> dict:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(self.base_url + method, data=payload)
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Telegram API вернул HTTP {error.code}") from None
        except urllib.error.URLError:
            raise RuntimeError("Не удалось связаться с Telegram API") from None
        if not body.get("ok"):
            raise RuntimeError("Telegram API отклонил запрос")
        return body["result"]


def process_message(message: dict, api: TelegramApi, kb: KnowledgeBase, audit: AuditLog) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return
    text = message.get("text")
    if not isinstance(text, str):
        api.call("sendMessage", {"chat_id": chat_id, "text": FALLBACK})
        return
    command = text.split(maxsplit=1)[0].split("@", 1)[0]
    if command == "/start":
        api.call("sendMessage", {"chat_id": chat_id, "text": "Здравствуйте! Задайте вопрос по обслуживанию станции. Я отвечаю только по базе знаний сервисного отдела."})
        return
    if command == "/help":
        api.call("sendMessage", {"chat_id": chat_id, "text": "Спросите об обслуживании КАН Ультра, периодичности обслуживания КИТ или переполнении станции. Если информации нет, я направлю вас в сервисный отдел."})
        return
    if text.startswith("/"):
        return
    try:
        result = kb.answer(text)
    except (OSError, ValueError, GoogleSheetError):
        logging.exception("База знаний недоступна или некорректна")
        result = Result(FALLBACK, None, "needs_human")
    api.call("sendMessage", {"chat_id": chat_id, "text": result.answer})
    try:
        audit.record(chat_id, text, result)
    except sqlite3.Error:
        logging.exception("Не удалось записать обращение в журнал")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Проверить токен и соединение, затем выйти")
    parser.add_argument("--no-admin", action="store_true", help="Запустить без локального редактора")
    args = parser.parse_args()
    load_local_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте TELEGRAM_BOT_TOKEN в локальном .env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api = TelegramApi(token)
    bot = api.call("getMe", {})
    logging.info("Подключен бот @%s", bot.get("username"))
    if args.check:
        return
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if sheet_id:
        credentials_path = path_from_config("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json")
        source = GoogleSheetStore(
            sheet_id,
            os.environ.get("GOOGLE_SHEET_TAB", "Knowledge"),
            authorized_session(credentials_path),
        )
        logging.info("Источник базы знаний: Google Таблица")
    else:
        source = ArticleStore(path_from_config("KNOWLEDGE_BASE_PATH", "knowledge_base/articles.csv"))
        logging.info("Источник базы знаний: локальный CSV")
    kb = KnowledgeBase(source)
    kb.load()
    audit_path = path_from_config("AUDIT_DB_PATH", "data/audit.sqlite3")
    audit = AuditLog(audit_path)
    admin = None
    if not args.no_admin:
        port = int(os.environ.get("ADMIN_PORT", "8765"))
        admin = start_admin(source, audit_path, port)
        logging.info("Редактор базы знаний: http://127.0.0.1:%s", admin.server_port)
    offset = 0
    try:
        while True:
            try:
                updates = api.call("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": '["message"]'})
                for update in updates:
                    process_message(update.get("message") or {}, api, kb, audit)
                    offset = update["update_id"] + 1
            except RuntimeError as error:
                logging.error("%s", error)
                time.sleep(3)
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
    finally:
        if admin is not None:
            admin.shutdown()
            admin.server_close()


if __name__ == "__main__":
    main()
