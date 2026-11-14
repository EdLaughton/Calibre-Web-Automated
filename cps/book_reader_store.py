"""Shared storage and Hardcover client for CWA reader requests."""

import json
import os
import sqlite3
from contextlib import closing
from email.errors import HeaderParseError
from email.headerregistry import Address
from pathlib import Path
from urllib.request import Request, urlopen


QUEUE = Path(os.environ.get("CWA_REQUEST_DB", "/config/nova-ui/requests.db"))
LIBRARY = Path(os.environ.get("CWA_LIBRARY_DB", "/calibre-library/metadata.db"))
SETTINGS = Path(os.environ.get("CWA_SETTINGS_DB", "/config/app.db"))
ACTIVE = ("queued", "searching", "submitting", "downloading", "checking", "waiting_release", "waiting_epub")
DELIVERIES = {"email": "request_notices", "kindle": "request_kindles"}


def open_queue(path=QUEUE):
    os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            work INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,
            updated INTEGER NOT NULL,
            book_id INTEGER,
            download_id TEXT,
            release_title TEXT,
            identity_key TEXT,
            protocol TEXT,
            indexer TEXT,
            size_bytes INTEGER,
            format TEXT,
            review_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS readers (
            work INTEGER NOT NULL,
            reader INTEGER NOT NULL,
            PRIMARY KEY(work, reader)
        );
        CREATE TABLE IF NOT EXISTS request_notices (
            work INTEGER NOT NULL,
            reader INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY(work, reader)
        );
        CREATE TABLE IF NOT EXISTS request_kindles (
            work INTEGER NOT NULL,
            reader INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY(work, reader)
        );
        CREATE TABLE IF NOT EXISTS request_releases (
            work INTEGER PRIMARY KEY,
            release_date TEXT NOT NULL,
            next_check INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS request_admin_actions (
            id INTEGER PRIMARY KEY,
            work INTEGER NOT NULL,
            admin INTEGER NOT NULL,
            action TEXT NOT NULL,
            previous_state TEXT NOT NULL,
            created INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS request_admin_alerts (
            id INTEGER PRIMARY KEY,
            work INTEGER NOT NULL,
            state TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    for name, definition in {
        "authors": "TEXT NOT NULL DEFAULT ''",
        "protocol": "TEXT",
        "indexer": "TEXT",
        "size_bytes": "INTEGER",
        "format": "TEXT",
        "review_reason": "TEXT",
    }.items():
        if name not in columns:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    alert_columns = {row[1] for row in db.execute("PRAGMA table_info(request_admin_alerts)")}
    if "reason" not in alert_columns:
        db.execute("ALTER TABLE request_admin_alerts ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
    action_columns = {row[1] for row in db.execute("PRAGMA table_info(request_admin_actions)")}
    if "note" not in action_columns:
        db.execute("ALTER TABLE request_admin_actions ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    db.commit()
    return db


def kindle_address(value):
    try:
        address = Address(addr_spec=(value or "").strip())
    except (HeaderParseError, ValueError):
        return None
    return address if address.domain.casefold() == "kindle.com" else None


def owned(work, library=LIBRARY):
    with closing(sqlite3.connect(f"file:{library}?mode=ro", uri=True)) as db:
        return db.execute(
            "SELECT book FROM identifiers WHERE type='hardcover-id' AND val=?",
            (str(work),),
        ).fetchone()


def hardcover(query, variables, settings=SETTINGS):
    with closing(sqlite3.connect(f"file:{settings}?mode=ro", uri=True)) as db:
        token = db.execute("SELECT config_hardcover_token FROM settings").fetchone()[0]
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Hardcover unavailable")
    if not token.lower().startswith("bearer "):
        token = "Bearer " + token
    call = Request(
        "https://api.hardcover.app/v1/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    with urlopen(call, timeout=8) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError("Hardcover search failed")
    return result["data"]
