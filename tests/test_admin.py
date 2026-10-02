import csv
import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from service_bot.admin import create_server
from service_bot.audit import AuditLog
from service_bot.knowledge import FALLBACK, KnowledgeBase, Result
from service_bot.store import ArticleStore, FIELDS


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.kb_path = Path(self.temporary.name) / "articles.csv"
        with self.kb_path.open("w", newline="", encoding="utf-8") as target:
            csv.DictWriter(target, fieldnames=FIELDS).writeheader()

    def test_operator_can_publish_article_without_code_change(self):
        store = ArticleStore(self.kb_path)
        article = {
            "id": "tver", "status": "draft", "equipment_aliases": "Тверь",
            "topic_terms": "почист|обслуж", "exclude_terms": "",
            "question_examples": "Как почистить Тверь?", "answer": "Утверждённая инструкция.",
        }
        store.save(article)
        kb = KnowledgeBase(self.kb_path)
        self.assertEqual(kb.answer("Как почистить Тверь?").answer, FALLBACK)
        article["status"] = "published"
        store.save(article, "tver")
        self.assertEqual(kb.answer("Как почистить Тверь?").answer, "Утверждённая инструкция.")

        self.assertEqual(kb.answer("Нужен ролик для Тверь").answer, FALLBACK)
        article["question_examples"] += "|Нужен ролик для Тверь"
        store.save(article, "tver")
        self.assertEqual(kb.answer("Нужен ролик для Тверь").answer, "Утверждённая инструкция.")

    def test_local_form_requires_token_and_escapes_questions(self):
        audit_path = Path(self.temporary.name) / "audit.sqlite3"
        AuditLog(audit_path).record(1, "<script>alert(1)</script>", Result(FALLBACK, None, "needs_human"))
        server = create_server(self.kb_path, audit_path, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        self.addCleanup(conn.close)
        conn.request("GET", "/articles/new")
        response = conn.getresponse()
        form = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        token = re.search(r'name="csrf" value="([^"]+)"', form).group(1)

        values = {
            "id": "tver", "status": "published", "equipment_aliases": "Тверь",
            "topic_terms": "почист", "exclude_terms": "",
            "question_examples": "Как почистить Тверь?", "answer": "Ответ из базы",
            "original_id": "",
        }
        conn.request("POST", "/articles/save", urlencode(values), {"Content-Type": "application/x-www-form-urlencoded"})
        forbidden = conn.getresponse()
        forbidden.read()
        self.assertEqual(forbidden.status, 403)
        self.assertEqual(ArticleStore(self.kb_path).all(), [])

        values["csrf"] = token
        conn.request("POST", "/articles/save", urlencode(values), {"Content-Type": "application/x-www-form-urlencoded"})
        saved = conn.getresponse()
        saved.read()
        self.assertEqual(saved.status, 303)
        self.assertEqual(KnowledgeBase(self.kb_path).answer("Как почистить Тверь?").answer, "Ответ из базы")
        conn.request("GET", "/")
        index = conn.getresponse().read().decode("utf-8")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", index)
        self.assertNotIn("<script>alert(1)</script>", index)


if __name__ == "__main__":
    unittest.main()
