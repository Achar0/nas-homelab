import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news_db  # noqa: E402

DAY = 86400
NOW = 1_800_000_000


def item(i, published=NOW, topic="tech"):
    return {"id": f"id{i}", "title": f"Story {i}", "summary": "s", "link": f"https://x/{i}", "source": "S",
            "topic": topic, "lang": "en", "published": published}


class NewsDb(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "news.db")
        news_db.init(self.path)

    def test_store_is_idempotent_and_keeps_first_seen(self):
        news_db.store(self.path, [item(1)], NOW)
        news_db.store(self.path, [item(1), item(2)], NOW + 900)
        rows = news_db.history(self.path, opened_only=False, since=0)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["id"]: r["first_seen"] for r in rows}["id1"], NOW)

    def test_mark_opened(self):
        news_db.store(self.path, [item(1), item(2)], NOW)
        self.assertTrue(news_db.mark_opened(self.path, "id2", NOW + 60))
        self.assertTrue(news_db.mark_opened(self.path, "id2", NOW + 120))
        self.assertFalse(news_db.mark_opened(self.path, "nope", NOW))
        opened = news_db.history(self.path, opened_only=True, since=0)
        self.assertEqual([(r["id"], r["open_count"], r["opened_at"]) for r in opened], [("id2", 2, NOW + 120)])

    def test_prune_keeps_opened_longer(self):
        news_db.store(self.path, [item(1), item(2)], NOW)
        news_db.mark_opened(self.path, "id2", NOW)
        news_db.prune(self.path, NOW + 31 * DAY)
        self.assertEqual([r["id"] for r in news_db.history(self.path, opened_only=False, since=0)], ["id2"])
        news_db.prune(self.path, NOW + 91 * DAY)
        self.assertEqual(news_db.history(self.path, opened_only=False, since=0), [])

    def test_history_newest_opened_first(self):
        news_db.store(self.path, [item(1), item(2), item(3)], NOW)
        news_db.mark_opened(self.path, "id1", NOW + 10)
        news_db.mark_opened(self.path, "id3", NOW + 20)
        self.assertEqual([r["id"] for r in news_db.history(self.path, opened_only=True, since=0)], ["id3", "id1"])
        self.assertEqual(news_db.history(self.path, opened_only=True, since=NOW + 15)[0]["id"], "id3")


if __name__ == "__main__":
    unittest.main()
