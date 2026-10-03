"""Small Telegram Bot API client using the Python standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


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
        except TimeoutError:
            raise RuntimeError("Истекло время ожидания Telegram API") from None

        if not body.get("ok"):
            raise RuntimeError("Telegram API отклонил запрос")
        return body["result"]
