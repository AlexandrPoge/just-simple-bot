import unittest
from unittest.mock import patch

from service_bot.telegram_api import TelegramApi


class TelegramApiTests(unittest.TestCase):
    def test_timeout_becomes_retryable_error(self):
        with patch(
            "service_bot.telegram_api.urllib.request.urlopen", side_effect=TimeoutError
        ):
            with self.assertRaisesRegex(RuntimeError, "время ожидания"):
                TelegramApi("test-token").call("getUpdates", {})


if __name__ == "__main__":
    unittest.main()
