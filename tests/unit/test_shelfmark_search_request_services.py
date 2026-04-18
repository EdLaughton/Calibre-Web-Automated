# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import sqlite3
import types
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
    search_module._REQUEST_SEARCH_PAGE_CACHE.clear()
    search_module._HARDCOVER_QUERY_CACHE.clear()
    details_module._DETAIL_CACHE.clear()

    web = Blueprint("web", __name__)
    shelfmark = Blueprint("shelfmark_search", __name__)

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @shelfmark.route("/request")
    def search_page():
        return "search"

    @shelfmark.route("/request/detail/<provider>/<provider_id>")
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


def test_search_shelfmark_uses_one_external_search_and_default_filters(
    shelfmark_service_app,
    shelfmark_service_config,
    temp_library_dir,
    monkeypatch,
):
    call_counts = {"search": 0, "detail": 0, "request": 0}

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit, page, sort):
            call_counts["search"] += 1
            assert query == "dune"
            assert limit == search_module.DEFAULT_SHELFMARK_SEARCH_LIMIT
            assert page == 1
            assert sort == search_module.DEFAULT_REQUEST_SEARCH_SORT
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
                        "cover_url": "https://covers.example.com/dune.jpg",
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
    monkeypatch.setattr(search_module, "_search_hardcover_enrichment", lambda _query: ())

    with shelfmark_service_app.test_request_context("/request?query=dune"):
        result = search_module.search_shelfmark(shelfmark_service_config, "dune")

    assert call_counts == {"search": 1, "detail": 0, "request": 0}
    assert result["searched"] is True
    assert result["total_found"] == 1
    assert result["selected_sort"] == "popularity"
    assert result["filter_has_cover"] is True
    assert result["filter_hide_owned"] is True
    assert result["filtered_owned"] == 1
    assert result["visible_count"] == 0
    assert result["page"] == 1
    assert result["total_pages"] == 0
    assert result["results"] == []


def test_search_shelfmark_can_include_owned_book_when_requested(
    shelfmark_service_app,
    shelfmark_service_config,
    temp_library_dir,
    monkeypatch,
):
    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit, page, sort):
            assert query == "dune"
            assert limit == search_module.DEFAULT_SHELFMARK_SEARCH_LIMIT
            assert page == 1
            assert sort == search_module.DEFAULT_REQUEST_SEARCH_SORT
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
                        "cover_url": "https://covers.example.com/dune.jpg",
                    }
                ],
                "total_found": 1,
            }

    _add_library_match(temp_library_dir, hardcover_id="hc-123")
    monkeypatch.setattr(search_module.config, "config_calibre_dir", str(temp_library_dir), raising=False)
    monkeypatch.setattr(search_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(search_module, "load_queue_rows_for_items", lambda _items: {})
    monkeypatch.setattr(search_module, "_search_hardcover_enrichment", lambda _query: ())

    with shelfmark_service_app.test_request_context("/request?query=dune&hide_owned=0&has_cover=0"):
        result = search_module.search_shelfmark(
            shelfmark_service_config,
            "dune",
            hide_owned=False,
            has_cover_only=False,
        )

    assert result["results"][0]["action"]["mode"] == "open_existing"
    assert result["results"][0]["action"]["label"] == "Open existing CWA book"
    assert result["results"][0]["action"]["href"] == "/book/42"


def test_search_shelfmark_suppresses_probable_non_book_results_and_uses_cached_hardcover_backfill(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    call_counts = {"search": 0, "hardcover": 0}
    search_module._HARDCOVER_QUERY_CACHE.clear()

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit, page, sort):
            call_counts["search"] += 1
            assert query == "brandon sanderson"
            assert page == 1
            assert sort == search_module.DEFAULT_REQUEST_SEARCH_SORT
            return {
                "books": [
                    {
                        "provider": "hardcover",
                        "provider_id": "author-1",
                        "title": "Brandon Sanderson",
                        "authors": ["Brandon Sanderson"],
                        "cover_url": "https://covers.example.com/author.jpg",
                    },
                    {
                        "provider": "hardcover",
                        "provider_id": "book-2",
                        "title": "Words of Radiance",
                        "authors": ["Brandon Sanderson"],
                        "cover_url": "",
                        "description": "",
                    },
                ],
                "total_found": 2,
            }

    class _FakeHardcover:
        def search(self, query):
            call_counts["hardcover"] += 1
            assert query == "brandon sanderson"
            return [
                types.SimpleNamespace(
                    id="book-2",
                    title="Words of Radiance",
                    authors=["Brandon Sanderson"],
                    cover="https://covers.example.com/words.jpg",
                    description="Kaladin must survive bridge duty and a shattered war on Roshar.",
                    series="The Stormlight Archive",
                    series_index=2,
                    publishedDate="2014-03-04",
                    publisher="Tor",
                    languages=["en"],
                    tags=["Epic Fantasy"],
                    format="Hardcover",
                    url="https://hardcover.app/books/words-of-radiance",
                    identifiers={"hardcover-id": "book-2"},
                )
            ]

    monkeypatch.setattr(search_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(search_module, "Hardcover", _FakeHardcover)
    monkeypatch.setattr(search_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(search_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/request?query=brandon+sanderson"):
        first = search_module.search_shelfmark(shelfmark_service_config, "brandon sanderson")
        second = search_module.search_shelfmark(shelfmark_service_config, "brandon sanderson")

    assert call_counts["search"] == 1
    assert call_counts["hardcover"] == 1
    assert first["filtered_non_books"] == 1
    assert len(first["results"]) == 1
    assert first["results"][0]["title"] == "Words of Radiance"
    assert first["results"][0]["description"].startswith("Kaladin must survive")
    assert first["results"][0]["cover_url"] == "https://covers.example.com/words.jpg"
    assert first["results"][0]["series_note"] == "The Stormlight Archive #2"
    assert second["results"][0]["description"].startswith("Kaladin must survive")


def test_search_shelfmark_fills_visible_page_from_later_raw_pages(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    searched_pages: list[int] = []

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit, page, sort):
            searched_pages.append(page)
            assert query == "stormlight"
            assert limit == 2
            assert sort == search_module.DEFAULT_REQUEST_SEARCH_SORT
            pages = {
                1: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "owned-1",
                            "title": "The Way of Kings",
                            "authors": ["Brandon Sanderson"],
                            "cover_url": "https://covers.example.com/kings.jpg",
                        },
                        {
                            "provider": "hardcover",
                            "provider_id": "coverless-1",
                            "title": "Words of Radiance",
                            "authors": ["Brandon Sanderson"],
                            "cover_url": "",
                        },
                    ],
                    "total_found": 5,
                },
                2: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "author-1",
                            "title": "Brandon Sanderson",
                            "authors": ["Brandon Sanderson"],
                            "cover_url": "https://covers.example.com/author.jpg",
                        },
                        {
                            "provider": "hardcover",
                            "provider_id": "book-2",
                            "title": "Oathbringer",
                            "authors": ["Brandon Sanderson"],
                            "cover_url": "https://covers.example.com/oathbringer.jpg",
                        },
                    ],
                    "total_found": 5,
                },
                3: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "book-3",
                            "title": "Rhythm of War",
                            "authors": ["Brandon Sanderson"],
                            "cover_url": "https://covers.example.com/row.jpg",
                        }
                    ],
                    "total_found": 5,
                },
            }
            return pages[page]

    monkeypatch.setattr(search_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(search_module, "_search_hardcover_enrichment", lambda _query: ())
    monkeypatch.setattr(
        search_module,
        "find_library_matches",
        lambda _results: {
            "hardcover:owned-1": search_module.LibraryMatch(
                book_id=42,
                title="The Way of Kings",
                author="Brandon Sanderson",
                reason="hardcover-id",
            )
        },
    )
    monkeypatch.setattr(search_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/request?query=stormlight"):
        result = search_module.search_shelfmark(
            shelfmark_service_config,
            "stormlight",
            limit=2,
        )

    assert searched_pages == [1, 2, 3]
    assert [item["title"] for item in result["results"]] == ["Oathbringer", "Rhythm of War"]
    assert result["visible_count"] == 2
    assert result["page_result_count"] == 2
    assert result["filtered_owned"] == 1
    assert result["filtered_coverless"] == 1
    assert result["filtered_non_books"] == 1
    assert result["page"] == 1
    assert result["total_pages"] == 1
    assert result["visible_start"] == 1
    assert result["visible_end"] == 2


def test_search_shelfmark_paginates_over_filtered_visible_results(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    searched_pages: list[int] = []

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_books(self, query, *, limit, page, sort):
            searched_pages.append(page)
            assert query == "murderbot"
            assert limit == 2
            assert sort == search_module.DEFAULT_REQUEST_SEARCH_SORT
            pages = {
                1: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "book-1",
                            "title": "All Systems Red",
                            "authors": ["Martha Wells"],
                            "cover_url": "https://covers.example.com/asr.jpg",
                        },
                        {
                            "provider": "hardcover",
                            "provider_id": "book-2",
                            "title": "Artificial Condition",
                            "authors": ["Martha Wells"],
                            "cover_url": "https://covers.example.com/ac.jpg",
                        },
                    ],
                    "total_found": 5,
                },
                2: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "book-3",
                            "title": "Rogue Protocol",
                            "authors": ["Martha Wells"],
                            "cover_url": "https://covers.example.com/rp.jpg",
                        },
                        {
                            "provider": "hardcover",
                            "provider_id": "book-4",
                            "title": "Exit Strategy",
                            "authors": ["Martha Wells"],
                            "cover_url": "https://covers.example.com/es.jpg",
                        },
                    ],
                    "total_found": 5,
                },
                3: {
                    "books": [
                        {
                            "provider": "hardcover",
                            "provider_id": "book-5",
                            "title": "Network Effect",
                            "authors": ["Martha Wells"],
                            "cover_url": "https://covers.example.com/ne.jpg",
                        }
                    ],
                    "total_found": 5,
                },
            }
            return pages[page]

    monkeypatch.setattr(search_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(search_module, "_search_hardcover_enrichment", lambda _query: ())
    monkeypatch.setattr(search_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(search_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/request?query=murderbot&page=2"):
        result = search_module.search_shelfmark(
            shelfmark_service_config,
            "murderbot",
            limit=2,
            page=2,
        )

    assert searched_pages == [1, 2, 3]
    assert [item["title"] for item in result["results"]] == ["Rogue Protocol", "Exit Strategy"]
    assert result["visible_count"] == 5
    assert result["page_result_count"] == 2
    assert result["page"] == 2
    assert result["total_pages"] == 3
    assert result["has_previous"] is True
    assert result["previous_page"] == 1
    assert result["has_next"] is True
    assert result["next_page"] == 3
    assert result["visible_start"] == 3
    assert result["visible_end"] == 4


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

    with shelfmark_service_app.test_request_context("/request/detail/hardcover/123"):
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


def test_details_view_preserves_multiple_series_memberships_and_stats(
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
                "provider": "hardcover",
                "provider_id": "123",
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "publish_year": "1965",
                "pages": 412,
                "rating": 4.4,
                "ratings_count": 12304,
                "readers_count": 48110,
                "series_memberships": [
                    {
                        "name": "Dune",
                        "series_position": 1,
                        "series_count": 6,
                        "url": "https://series.example.com/dune",
                    },
                    {
                        "name": "Great Schools of Dune",
                        "series_position": 1,
                        "series_count": 3,
                    },
                ],
            }

    monkeypatch.setattr(details_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(details_module, "_build_hardcover_overlay", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(details_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(details_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/request/detail/hardcover/123"):
        view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "hardcover",
            "123",
        )

    assert [series["display"] for series in view["series_memberships"]] == [
        "Dune #1",
        "Great Schools of Dune #1",
    ]
    assert [series["detail"] for series in view["series_memberships"]] == ["6 books", "3 books"]
    assert view["detail_stats"] == (
        {"label": "Rating", "value": "4.4"},
        {"label": "Ratings", "value": "12,304"},
        {"label": "Readers", "value": "48,110"},
        {"label": "Pages", "value": "412"},
    )


def test_details_view_uses_cached_hardcover_enrichment_for_non_hardcover_provider(
    shelfmark_service_app,
    shelfmark_service_config,
    monkeypatch,
):
    details_module._DETAIL_CACHE.clear()
    hardcover_calls = {"count": 0}

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
                "description": "",
            }

    class _FakeHardcover:
        def search(self, query):
            hardcover_calls["count"] += 1
            assert query == "The Dispossessed Ursula K. Le Guin"
            return [
                types.SimpleNamespace(
                    id="hc-77",
                    title="The Dispossessed",
                    authors=["Ursula K. Le Guin"],
                    cover="https://covers.example.com/dispossessed.jpg",
                    description="A spare, political science-fiction classic set between twin worlds.",
                    series="Hainish Cycle",
                    series_index=None,
                    publishedDate="1974-01-01",
                    publisher="Harper & Row",
                    languages=["en"],
                    tags=["Science Fiction"],
                    url="https://hardcover.app/books/the-dispossessed",
                    identifiers={"hardcover-id": "hc-77"},
                )
            ]

    monkeypatch.setattr(details_module, "ShelfmarkClient", _FakeShelfmarkClient)
    monkeypatch.setattr(details_module, "Hardcover", _FakeHardcover)
    monkeypatch.setattr(details_module, "find_library_matches", lambda _results: {})
    monkeypatch.setattr(details_module, "load_queue_rows_for_items", lambda _items: {})

    with shelfmark_service_app.test_request_context("/request/detail/google/abc"):
        first_view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "google",
            "abc",
        )
        second_view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "google",
            "abc",
        )

    assert hardcover_calls["count"] == 1
    assert first_view["description"].startswith("A spare, political science-fiction classic")
    assert first_view["series_name"] == "Hainish Cycle"
    assert first_view["description_source"] == "Shelfmark and Hardcover"
    assert second_view["description"].startswith("A spare, political science-fiction classic")


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

    with shelfmark_service_app.test_request_context("/request/detail/google/abc"):
        view = details_module.get_shelfmark_detail_view(
            shelfmark_service_config,
            "google",
            "abc",
        )

    assert view["title"] == "The Dispossessed"
    assert view["hardcover_overlay"] is None
    assert view["action"]["mode"] == "request"
