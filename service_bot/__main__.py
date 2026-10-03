"""Configure and run the local Telegram polling application."""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from .admin import start_admin
from .audit import AuditLog
from .dialog import DialogState, process_message
from .google_sheets import GoogleSheetStore, authorized_session
from .knowledge import KnowledgeBase
from .store import ArticleStore
from .telegram_api import TelegramApi

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Проверить токен и соединение, затем выйти"
    )
    parser.add_argument(
        "--no-admin", action="store_true", help="Запустить без локального редактора"
    )
    args = parser.parse_args()

    load_local_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте TELEGRAM_BOT_TOKEN в локальном .env")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    api = TelegramApi(token)
    bot = api.call("getMe", {})
    LOGGER.info("Подключен бот @%s", bot.get("username"))
    if args.check:
        return

    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if sheet_id:
        credentials_path = path_from_config(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json"
        )
        source = GoogleSheetStore(
            sheet_id,
            os.environ.get("GOOGLE_SHEET_TAB", "Knowledge"),
            authorized_session(credentials_path),
        )
        LOGGER.info("Источник базы знаний: Google Таблица")
    else:
        source = ArticleStore(
            path_from_config("KNOWLEDGE_BASE_PATH", "knowledge_base/articles.csv")
        )
        LOGGER.info("Источник базы знаний: локальный CSV")

    kb = KnowledgeBase(source)
    kb.load()
    audit_path = path_from_config("AUDIT_DB_PATH", "data/audit.sqlite3")
    audit = AuditLog(audit_path)
    dialog = DialogState()

    admin = None
    if not args.no_admin:
        port = int(os.environ.get("ADMIN_PORT", "8765"))
        admin = start_admin(source, audit_path, port)
        LOGGER.info("Редактор базы знаний: http://127.0.0.1:%s", admin.server_port)

    offset = 0
    try:
        while True:
            try:
                updates = api.call(
                    "getUpdates",
                    {"offset": offset, "timeout": 25, "allowed_updates": '["message"]'},
                )
                for update in updates:
                    process_message(update.get("message") or {}, api, kb, audit, dialog)
                    offset = update["update_id"] + 1
            except RuntimeError as error:
                LOGGER.error("%s", error)
                time.sleep(3)
    except KeyboardInterrupt:
        LOGGER.info("Бот остановлен")
    finally:
        if admin is not None:
            admin.shutdown()
            admin.server_close()


if __name__ == "__main__":
    main()
