"""A private Google Sheet as the shared knowledge base for operators and the bot."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from urllib.parse import quote

from .store import FIELDS, revision, validate_article


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,200}$")


class GoogleSheetError(RuntimeError):
    """A safe, non-secret-bearing error from the Google Sheets source."""


def authorized_session(credentials_path: Path):
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as error:
        raise GoogleSheetError("Установите зависимости из requirements-google.txt") from error
    if not credentials_path.is_file():
        raise GoogleSheetError("Файл сервисного аккаунта Google не найден")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=[SHEETS_SCOPE],
        )
        return AuthorizedSession(credentials)
    except (OSError, ValueError) as error:
        raise GoogleSheetError("Не удалось прочитать ключ сервисного аккаунта Google") from error


class GoogleSheetStore:
    def __init__(self, spreadsheet_id: str, tab_name: str, session):
        if not SHEET_ID.fullmatch(spreadsheet_id):
            raise ValueError("Некорректный ID Google Таблицы")
        if not tab_name or len(tab_name) > 100 or any(char in tab_name for char in "\r\n!:"):
            raise ValueError("Некорректное имя листа Google Таблицы")
        self.spreadsheet_id = spreadsheet_id
        self.tab_name = tab_name
        self.session = session
        self._lock = threading.Lock()
        self.base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/"

    def _a1(self, cell_range: str) -> str:
        return f"'{self.tab_name.replace(chr(39), chr(39) * 2)}'!{cell_range}"

    def _request(self, method: str, cell_range: str, values: list[list[str]] | None = None, append: bool = False) -> dict:
        address = self.base_url + quote(self._a1(cell_range), safe="")
        if append:
            address += ":append"
        if values is not None:
            address += "?valueInputOption=RAW"
        payload = {"values": values} if values is not None else None
        try:
            response = self.session.request(method, address, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Некорректный ответ Google Sheets API")
            return data
        except Exception as error:
            raise GoogleSheetError("Не удалось получить данные из Google Таблицы или сохранить их") from error

    def _indexed_rows(self) -> list[tuple[int, dict[str, str]]]:
        raw = self._request("GET", "A1:G").get("values", [])
        if not raw or raw[0] != list(FIELDS):
            raise GoogleSheetError("В первой строке Google Таблицы должны быть заголовки базы знаний")
        result = []
        ids = set()
        for number, cells in enumerate(raw[1:], start=2):
            if len(cells) > len(FIELDS):
                raise GoogleSheetError("В Google Таблице обнаружены лишние колонки")
            if not any(str(cell).strip() for cell in cells):
                continue
            row = dict(zip(FIELDS, [str(cell) for cell in cells] + [""] * (len(FIELDS) - len(cells))))
            if row["id"] in ids:
                raise GoogleSheetError("В Google Таблице повторяется ID статьи")
            ids.add(row["id"])
            try:
                validate_article(row)
            except ValueError as error:
                raise GoogleSheetError(f"Некорректная статья в строке {number}: {error}") from error
            result.append((number, row))
        return result

    def all(self) -> list[dict[str, str]]:
        return [row for _, row in self._indexed_rows()]

    def save(self, values: dict[str, str], original_id: str = "", expected_revision: str = "") -> str:
        article = validate_article(values)
        with self._lock:
            rows = self._indexed_rows()
            found = next(((number, row) for number, row in rows if row["id"] == article["id"]), None)
            payload = [[article[field] for field in FIELDS]]
            if original_id:
                if article["id"] != original_id or found is None:
                    raise ValueError("Редактируемая статья не найдена")
                number, current = found
                if not expected_revision or revision(current) != expected_revision:
                    raise ValueError("Статья изменилась. Обновите страницу перед сохранением")
                last_check = self._request("GET", f"A{number}:G{number}").get("values", [])
                latest = dict(zip(FIELDS, [str(cell) for cell in last_check[0]] + [""] * (len(FIELDS) - len(last_check[0])))) if last_check else {}
                if revision(latest) != expected_revision:
                    raise ValueError("Статья изменилась. Обновите страницу перед сохранением")
                self._request("PUT", f"A{number}:G{number}", payload)
            else:
                if found is not None:
                    raise ValueError("Статья с таким ID уже существует")
                self._request("POST", "A1:G", payload, append=True)
        return article["id"]
