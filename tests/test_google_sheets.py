import unittest
from urllib.parse import unquote, urlsplit

from service_bot.google_sheets import GoogleSheetError, GoogleSheetStore
from service_bot.knowledge import KnowledgeBase
from service_bot.store import FIELDS, revision


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self):
        self.rows = [list(FIELDS), [
            "kan", "published", "кан", "почист|обслуж", "как часто",
            "Как почистить КАН?", "Ссылка на утверждённую инструкцию",
        ]]
        self.fail = False

    def request(self, method, url, json=None, timeout=None):
        if self.fail:
            raise ConnectionError("Google API недоступен")
        encoded = urlsplit(url).path.split("/values/", 1)[1]
        cell_range = unquote(encoded).split("!", 1)[1]
        if cell_range.endswith(":append"):
            cell_range = cell_range.removesuffix(":append")
        if method == "GET" and cell_range == "A1:G":
            return FakeResponse({"values": self.rows})
        if method == "GET":
            row_number = int(cell_range.split(":", 1)[0][1:])
            return FakeResponse({"values": [self.rows[row_number - 1]]})
        if method == "PUT":
            row_number = int(cell_range.split(":", 1)[0][1:])
            self.rows[row_number - 1] = json["values"][0]
            return FakeResponse({})
        if method == "POST":
            self.rows.append(json["values"][0])
            return FakeResponse({})
        raise AssertionError((method, cell_range))


class GoogleSheetsTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.store = GoogleSheetStore("A" * 30, "Knowledge", self.session)
        self.kb = KnowledgeBase(self.store)

    def test_manager_and_local_editor_share_one_source(self):
        self.assertEqual(self.kb.answer("Как почистить КАН?").article_id, "kan")
        current = self.store.all()[0]
        original_revision = revision(current)

        # A manager edits the same sheet while the local form is still open.
        self.session.rows[1][-1] = "Обновлённый менеджером ответ"
        self.assertEqual(self.kb.answer("Как почистить КАН?").answer, "Обновлённый менеджером ответ")
        with self.assertRaisesRegex(ValueError, "Обновите страницу"):
            self.store.save({**current, "answer": "Старый вариант"}, "kan", original_revision)

        fresh = self.store.all()[0]
        self.store.save({**fresh, "question_examples": fresh["question_examples"] + "|Нужен ролик для КАН"}, "kan", revision(fresh))
        self.assertEqual(self.kb.answer("Нужен ролик для КАН").answer, "Обновлённый менеджером ответ")

    def test_new_article_is_added_to_sheet(self):
        self.store.save({
            "id": "kit", "status": "published", "equipment_aliases": "кит",
            "topic_terms": "част|периодич", "exclude_terms": "",
            "question_examples": "Как часто обслуживать КИТ?",
            "answer": "Рекомендуем проводить обслуживание станции КИТ один раз в год.",
        })
        self.assertEqual(self.kb.answer("Как часто обслуживать КИТ?").article_id, "kit")

    def test_source_failure_never_uses_stale_csv(self):
        self.session.fail = True
        with self.assertRaises(GoogleSheetError):
            self.kb.answer("Как почистить КАН?")


if __name__ == "__main__":
    unittest.main()
