import unittest
from unittest.mock import patch

from service_bot.__main__ import TelegramApi


class TelegramApiTests(unittest.TestCase):
    def test_timeout_becomes_retryable_error(self):
        with patch("service_bot.__main__.urllib.request.urlopen", side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, "время ожидания"):
                TelegramApi("test-token").call("getUpdates", {})


if __name__ == "__main__":
    unittest.main()
