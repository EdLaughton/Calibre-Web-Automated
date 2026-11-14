"""The request queue must upgrade without losing existing reader jobs."""

import importlib.util
import sqlite3
from pathlib import Path


def load_store():
    source = Path(__file__).resolve().parents[2] / "cps" / "book_reader_store.py"
    spec = importlib.util.spec_from_file_location("book_reader_store_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_queue_upgrade_preserves_jobs_and_readers(tmp_path):
    path = tmp_path / "requests.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE jobs (work INTEGER PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,
                updated INTEGER NOT NULL,book_id INTEGER,download_id TEXT,release_title TEXT,
                identity_key TEXT);
            CREATE TABLE readers (work INTEGER NOT NULL,reader INTEGER NOT NULL,
                PRIMARY KEY(work,reader));
            CREATE TABLE request_admin_actions (id INTEGER PRIMARY KEY,work INTEGER NOT NULL,
                admin INTEGER NOT NULL,action TEXT NOT NULL,previous_state TEXT NOT NULL,
                created INTEGER NOT NULL);
            INSERT INTO jobs VALUES (1477434,'The Unworthy','imported',100,3120,'abc','release','key');
            INSERT INTO readers VALUES (1477434,2);
            INSERT INTO request_admin_actions VALUES (1,1477434,1,'retry','held',100);
        """)
    store = load_store()
    db = store.open_queue(path)
    try:
        row = db.execute("SELECT title,state,book_id,authors,protocol,indexer,size_bytes,format "
                         "FROM jobs WHERE work=1477434").fetchone()
        assert tuple(row) == ("The Unworthy", "imported", 3120, "", None, None, None, None)
        assert db.execute("SELECT reader FROM readers WHERE work=1477434").fetchone()[0] == 2
        assert {name for name in ("request_admin_actions", "request_admin_alerts")
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone()} == {
                    "request_admin_actions", "request_admin_alerts"}
        assert db.execute("SELECT note FROM request_admin_actions WHERE id=1").fetchone()[0] == ""
    finally:
        db.close()
    # Upgrade is durable and repeatable after the connection is closed.
    db = store.open_queue(path)
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    db.close()
