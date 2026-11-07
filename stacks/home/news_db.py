"""Local news archive (SQLite in data/news.db).

Every story the carousel showed is kept for 30 days; stories whose link you opened are kept
for 90 days (counted from the last time you opened them). Nothing leaves the NAS.
"""
import contextlib
import sqlite3

KEEP_DAYS = 30
KEEP_OPENED_DAYS = 90
COLUMNS = ("id", "title", "summary", "link", "source", "topic", "lang", "published", "first_seen", "opened_at", "open_count")


@contextlib.contextmanager
def _db(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:          # commit on success, roll back on error
            yield conn
    finally:
        conn.close()


def init(path):
    with _db(path) as c:
        c.execute("pragma journal_mode=wal")
        c.execute("""create table if not exists news (
            id text primary key, title text not null, summary text, link text not null, source text,
            topic text, lang text, published integer, first_seen integer not null,
            opened_at integer, open_count integer not null default 0)""")
        c.execute("create index if not exists news_opened on news(opened_at)")


def store(path, items, now):
    with _db(path) as c:
        c.executemany(
            "insert or ignore into news (id, title, summary, link, source, topic, lang, published, first_seen) "
            "values (:id, :title, :summary, :link, :source, :topic, :lang, :published, :now)",
            [{**i, "now": int(now)} for i in items])


def mark_opened(path, item_id, now):
    with _db(path) as c:
        cur = c.execute("update news set opened_at = ?, open_count = open_count + 1 where id = ?", (int(now), item_id))
        return cur.rowcount == 1


def prune(path, now):
    with _db(path) as c:
        c.execute("delete from news where opened_at is null and first_seen < ?", (int(now - KEEP_DAYS * 86400),))
        c.execute("delete from news where opened_at is not null and opened_at < ?", (int(now - KEEP_OPENED_DAYS * 86400),))


def history(path, opened_only, since, limit=200):
    with _db(path) as c:
        if opened_only:
            rows = c.execute("select * from news where opened_at >= ? order by opened_at desc limit ?", (since, limit))
        else:
            rows = c.execute("select * from news where first_seen >= ? order by published desc limit ?", (since, limit))
        return [{k: r[k] for k in COLUMNS} for r in rows]
