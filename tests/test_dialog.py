import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from service_bot.__main__ import DialogState, process_message
from service_bot.audit import AuditLog
from service_bot.knowledge import CLARIFY_MODEL, FALLBACK, KnowledgeBase


ROOT = Path(__file__).resolve().parents[1]


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audit = AuditLog(Path(self.directory.name) / "audit.sqlite3")
        self.addCleanup(self.audit.connection.close)
        self.api = Mock()
        self.kb = KnowledgeBase(ROOT / "knowledge_base/articles.csv")
        self.dialog = DialogState()

    def send(self, text, chat_id=7):
        process_message(
            {"chat": {"id": chat_id}, "text": text},
            self.api, self.kb, self.audit, self.dialog,
        )
        return self.api.call.call_args.args[1]["text"]

    def test_maintenance_question_then_model_gets_approved_answer(self):
        self.assertEqual(self.send("Как самому обслужить станцию?"), CLARIFY_MODEL)
        self.assertEqual(self.send("КАН Ультра"), self.kb.load()[0].answer)
        self.assertNotIn(7, self.dialog.pending)

    def test_unknown_model_does_not_inherit_kan_article(self):
        self.assertEqual(self.send("Как самому обслужить станцию?"), CLARIFY_MODEL)
        self.assertEqual(self.send("Тверь"), FALLBACK)

    def test_follow_up_from_another_chat_cannot_reuse_context(self):
        self.send("Как самому обслужить станцию?")
        self.assertEqual(self.send("КАН", chat_id=8), FALLBACK)

    def test_expired_context_cannot_be_used(self):
        with patch("service_bot.__main__.time.monotonic", return_value=0):
            self.send("Как самому обслужить станцию?")
        with patch("service_bot.__main__.time.monotonic", return_value=10_000):
            self.assertEqual(self.send("КАН Ультра"), FALLBACK)

    def test_database_failure_sends_fallback(self):
        with patch.object(self.kb, "load", side_effect=OSError("unavailable")):
            self.assertEqual(self.send("Как почистить КАН Ультра?"), FALLBACK)

    def test_empty_message_does_not_crash(self):
        self.assertEqual(self.send("   "), FALLBACK)


if __name__ == "__main__":
    unittest.main()
