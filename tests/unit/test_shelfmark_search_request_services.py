# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from flask import Blueprint, Flask

from cps.services.shelfmark_client import ShelfmarkClientConfig
from cps.services.shelfmark_queue import ShelfmarkQueueSummary
import cps.services.shelfmark_details as details_module
import cps.services.shelfmark_queue as queue_module
import cps.services.shelfmark_search as search_module


@pytest.fixture
def shelfmark_service_app(monkeypatch):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"

    web = Blueprint("web", __name__)
    shelfmark = Blueprint("shelfmark_search", __name__)

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @shelfmark.route("/shelfmark")
    def search_page():
        return "search"

    @shelfmark.route("/shelfmark/detail/<provider>/<provider_id>")
    def book_detail(provider, provider_id):
        return f"{provider}:{provider_id}"

    app.register_blueprint(web)
    app.register_blueprint(shelfmark)
    monkeypatch.setattr(search_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)
    monkeypatch.setattr(details_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)
    monkeypatch.setattr(queue_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)
    return app


@pytest.fixture
def shelfmark_service_config():
    return ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        username="",
        password="",
    )


def _add_library_match(
    library_dir: Path,
    *,
    book_id: int = 42,
    title: str = "Dune",
    author: str = "Frank Herbert",
    hardcover_id: str | None = None,
    isbn: str | None = None,
) -> None:
    db_path = library_dir / "metadata.db"
    with sqlite3.connect(str(db_path), timeout=30) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book INTEGER NOT NULL,
                type TEXT NOT NULL,
                val TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO books (id, title, author_sort, path, has_cover) VALUES (?, ?, ?, ?, 0)",
            (book_id, title, author, f"book-{book_id}"),
        )
        connection.execute(
            "INSERT INTO authors (id, name, sort, link) VALUES (?, ?, ?, '')",
            (book_id, author, author),
        )
        connection.execute(
            "INSERT INTO books_authors_link (book, author) VALUES (?, ?)",
            (book_id, book_id),
        )
        if hardcover_id:
            connection.execute(
                "INSERT INTO identifiers (book, type, val) VALUES (?, 'hardcover-id', ?)",
                (book_id, hardcover_id),
            )
        if isbn:
            connection.execute(
                "INSERT INTO identifiers (book, type, val) VALUES (?, 'isbn', ?)",
                (book_id, isbn),
            )
        connection.commit()


def test_search_shelfmark_uses_one_external_search_and_marks_existing_book(
    shelfmark_service_app,
    shelfmark_service_config,
    temp_library_dir,
    monkeypatch,
):
    call_counts = {"search": 0, "detail": 0, "request": 0}

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit):
            call_counts["search"] += 1
            assert query == "dune"
            assert limit == search_module.DEFAULT_SHELFMARK_SEARCH_LIMIT
            return {
                "books": [
                    {
                        "provider": "hardcover",
                        "provider_id": "hc-123",
                        "title": "Dune",
                        "authors": ["Frank Herbert"],
                        "publish_year": "1965",
                        "series_name": "Dune",
                        "series_position": 1,
                        "cover_url": "",
                    }
                ],
                "total_found": 1,
            }

        def fetch_book(self, *_args, **_kwargs):
            call_counts["detail"] += 1
            raise AssertionError("search_shelfmark should not fetch per-result details")

        def create_request(self, *_args, **_kwargs):
            call_counts["request"] += 1
            raise AssertionError("search_shelfmark should not submit requests")

    _add_library_match(temp_library_dir, hardcover_id="hc-123")
    monkeypatch.setattr(search_module.config, "config_calibre_dir", str(temp_library_dir), raising=False)
    monkeypatch.setattr(search_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(search_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/shelfmark?query=dune"):
        result = search_module.search_shelfmark(shelfmark_service_config, "dune")

    assert call_counts == {"search": 1, "detail": 0, "request": 0}
    assert result["searched"] is True
    assert result["total_found"] == 1
    assert result["results"][0]["action"]["mode"] == "open_existing"
    assert result["results"][0]["action"]["label"] == "Open existing CWA book"
    assert result["results"][0]["action"]["href"] == "/book/42"


def test_reconcile_queue_rows_prefers_exact_identifiers_over_title_author(
    temp_library_dir,
    monkeypatch,
):
    _add_library_match(
        temp_library_dir,
        book_id=84,
        title="The Left Hand of Darkness",
        author="Ursula K. Le Guin",
        isbn="9780441478125",
    )
    monkeypatch.setattr(search_module.config, "config_calibre_dir", str(temp_library_dir), raising=False)

    imported = search_module.reconcile_queue_rows_with_library(
        [
            {
                "id": 11,
                "provider": "google",
                "provider_id": "abc",
                "title": "Completely Different Title",
                "author": "Wrong Author",
                "identifiers_json": json.dumps({"isbn": "9780441478125"}),
            }
        ]
    )

    assert imported == [(11, 84)]


def test_sync_shelfmark_queue_isolates_failures_per_row(temp_cwa_db, shelfmark_service_config, monkeypatch):
    row_one = temp_cwa_db.shelfmark_queue_add(
        provider="hardcover",
        provider_id="111",
        title="Broken Request",
        author="A Author",
        status="queued",
        external_request_id=1,
        request_payload_json="{}",
        response_json="{}",
    )
    row_two = temp_cwa_db.shelfmark_queue_add(
        provider="hardcover",
        provider_id="222",
        title="Active Download",
        author="B Author",
        status="queued",
        external_source="annas_archive",
        external_source_id="download-222",
        request_payload_json="{}",
        response_json="{}",
    )
    assert row_one is not None and row_two is not None

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def fetch_activity_snapshot():
            return {
                "requests": [
                    {
                        "id": 1,
                        "status": "active",
                        "delivery_state": "error",
                        "last_failure_reason": "No usable sources",
                    }
                ],
                "status": {
                    "downloading": {
                        "task-222": {
                            "id": "task-222",
                            "source": "annas_archive",
                            "source_id": "download-222",
                            "status_message": "Fetching file",
                        }
                    }
                },
            }

    monkeypatch.setattr(queue_module, "ShelfmarkClient", _FakeShelfmarkClient)

    summary = queue_module.sync_shelfmark_queue(
        shelfmark_service_config,
        imported_matcher=lambda _rows: [],
    )

    refreshed = {
        row["provider_id"]: row
        for row in temp_cwa_db.shelfmark_queue_get_latest_for_items(
            [("hardcover", "111"), ("hardcover", "222")]
        )
    }
    assert summary["updated"] == 2
    assert refreshed["111"]["status"] == "failed"
    assert refreshed["111"]["last_error"] == "No usable sources"
    assert refreshed["222"]["status"] == "downloading"
    assert refreshed["222"]["external_task_id"] == "task-222"


def test_sync_shelfmark_queue_moves_complete_rows_to_importing(
    temp_cwa_db,
    shelfmark_service_config,
    monkeypatch,
):
    row_id = temp_cwa_db.shelfmark_queue_add(
        provider="hardcover",
        provider_id="333",
        title="Ready To Import",
        author="Frank Herbert",
        status="queued",
        external_request_id=33,
        request_payload_json="{}",
        response_json="{}",
    )
    assert row_id is not None

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def fetch_activity_snapshot():
            return {
                "requests": [
                    {
                        "id": 33,
                        "status": "active",
                        "delivery_state": "complete",
                        "last_failure_reason": "",
                    }
                ],
                "status": {},
            }

    monkeypatch.setattr(queue_module, "ShelfmarkClient", _FakeShelfmarkClient)

    queue_module.sync_shelfmark_queue(
        shelfmark_service_config,
        imported_matcher=lambda _rows: [],
    )

    row = temp_cwa_db.shelfmark_queue_get_by_id(row_id)
    assert row["status"] == "importing"


def test_details_view_cache_refreshes_dynamic_queue_state(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    details_module._DETAIL_CACHE.clear()
    fetch_calls = {"count": 0}
    queue_states = [
        {},
        {
            "hardcover:123": ShelfmarkQueueSummary(
                key="hardcover:123",
                provider="hardcover",
                provider_id="123",
                status="imported",
                label="Imported",
                detail="",
                imported_book_id=42,
                row={},
            )
        },
    ]

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch_book(self, provider, provider_id):
            fetch_calls["count"] += 1
            assert provider == "hardcover"
            assert provider_id == "123"
            return {
                "provider": "hardcover",
                "provider_id": "123",
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "publish_year": "1965",
                "series_name": "Dune",
            }

    monkeypatch.setattr(details_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(details_module, "_build_hardcover_overlay", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(details_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(
        details_module,
        "load_queue_rows_for_items",
        lambda _items: queue_states.pop(0),
    )

    with shelfmark_service_app.test_request_context("/shelfmark/detail/hardcover/123"):
        first_view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "hardcover",
            "123",
        )
        second_view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "hardcover",
            "123",
        )

    assert fetch_calls["count"] == 1
    assert first_view["action"]["mode"] == "request"
    assert second_view["action"]["mode"] == "open_existing"
    assert second_view["action"]["label"] == "Imported"
    assert second_view["action"]["href"] == "/book/42"


def test_details_view_gracefully_handles_missing_hardcover_enrichment(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    details_module._DETAIL_CACHE.clear()

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def fetch_book(_provider, _provider_id):
            return {
                "provider": "google",
                "provider_id": "abc",
                "title": "The Dispossessed",
                "authors": ["Ursula K. Le Guin"],
                "publish_year": "1974",
            }

    monkeypatch.setattr(details_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(details_module, "_build_hardcover_overlay", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(details_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(details_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/shelfmark/detail/google/abc"):
        view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "google",
            "abc",
        )

    assert view["title"] == "The Dispossessed"
    assert view["hardcover_overlay"] is None
    assert view["action"]["mode"] == "request"
