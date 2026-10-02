import csv
import tempfile
import unittest
from pathlib import Path

from service_bot.knowledge import FALLBACK, KnowledgeBase


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase(ROOT / "knowledge_base/articles.csv")

    def test_approved_answers_and_rephrasings(self):
        cases = {
            "Как почистить КАН Ультра?": "kan_ultra_maintenance",
            "Есть инструкция по обслуживанию КАН?": "kan_ultra_maintenance",
            "Как часто нужно обслуживать станцию КИТ?": "kit_frequency",
            "Когда делать ТО станции КИТ?": "kit_frequency",
            "У меня переполнена станция. Что делать?": "station_overflow",
            "Станция переполнилась": "station_overflow",
        }
        for question, expected_id in cases.items():
            with self.subTest(question=question):
                result = self.kb.answer(question)
                self.assertEqual(result.article_id, expected_id)
                self.assertEqual(result.status, "answered")

    def test_unknown_and_cross_topic_questions_are_rejected(self):
        for question in (
            "Как почистить станцию Тверь?",
            "Как часто нужно обслуживать КАН Ультра?",
            "Как почистить КИТ?",
            "Как самому обслужить станцию?",
            "Почему станция шумит?",
        ):
            with self.subTest(question=question):
                result = self.kb.answer(question)
                self.assertEqual(result.answer, FALLBACK)
                self.assertEqual(result.status, "needs_human")

    def test_new_published_article_works_without_code_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "articles.csv"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=sorted(KnowledgeBase.REQUIRED))
                writer.writeheader()
                writer.writerow({
                    "id": "tver", "status": "draft", "equipment_aliases": "тверь",
                    "topic_terms": "почист|обслуж", "exclude_terms": "",
                    "question_examples": "Как почистить Тверь?", "answer": "Утверждённая инструкция.",
                })
            kb = KnowledgeBase(path)
            self.assertEqual(kb.answer("Как почистить Тверь?").answer, FALLBACK)
            with path.open("r", newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            rows[0]["status"] = "published"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=sorted(KnowledgeBase.REQUIRED))
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(kb.answer("Как почистить Тверь?").answer, "Утверждённая инструкция.")


if __name__ == "__main__":
    unittest.main()
