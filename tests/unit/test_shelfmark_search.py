# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import socket
import sys
import types
from pathlib import Path
from unittest import mock

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "services" / "shelfmark_search.py"


def _gettext(value, **kwargs):
    return value % kwargs if kwargs else value


@pytest.fixture
def shelfmark_module(monkeypatch):
    logger_instance = types.SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )

    dummy_db = types.SimpleNamespace(
        Identifiers=types.SimpleNamespace(val=mock.Mock(), type=mock.Mock(), book=mock.Mock()),
        Books=types.SimpleNamespace(id=mock.Mock(), title=mock.Mock(), series_index=mock.Mock()),
        Series=types.SimpleNamespace(id=mock.Mock(), name=mock.Mock()),
        books_series_link=types.SimpleNamespace(
            c=types.SimpleNamespace(series=mock.Mock(), book=mock.Mock())
        ),
    )
    dummy_db.Identifiers.val.label = lambda name: name
    dummy_db.Books.id.label = lambda name: name
    dummy_db.Books.title.label = lambda name: name
    dummy_db.Books.series_index.label = lambda name: name
    dummy_db.Series.name.label = lambda name: name

    query = mock.Mock()
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    cps_module = types.ModuleType("cps")
    cps_module.calibre_db = types.SimpleNamespace(
        session=types.SimpleNamespace(query=mock.Mock(return_value=query)),
        common_filters=lambda *args, **kwargs: "COMMON_FILTER",
    )
    cps_module.config = types.SimpleNamespace(
        config_shelfmark_search=False,
        config_shelfmark_url="",
        config_shelfmark_browser_url="",
        config_shelfmark_username="",
        config_shelfmark_password_e="",
    )
    cps_module.db = dummy_db
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)
    clean_html_module = types.ModuleType("cps.clean_html")
    clean_html_module.clean_string = lambda value, book_id=0: value

    cw_advocate_module = types.ModuleType("cps.cw_advocate")
    cw_advocate_exceptions_module = types.ModuleType("cps.cw_advocate.exceptions")

    class DummyAddrValidator:
        def __init__(self, ip_whitelist=None, port_whitelist=None, **kwargs):
            self.ip_whitelist = ip_whitelist or set()
            self.port_whitelist = port_whitelist or set()

        def is_ip_allowed(self, value, _local_addresses=None):
            if value in {"192.168.0.87", "2001:db8::1"}:
                return True
            return False

        def is_addrinfo_allowed(self, addrinfo, _local_addresses=None):
            sockaddr = addrinfo[4]
            if len(sockaddr) == 2:
                ip_value, port = sockaddr
            else:
                ip_value, port = sockaddr[0], sockaddr[1]
            return self.is_ip_allowed(ip_value, _local_addresses=_local_addresses) and port in self.port_whitelist

    class DummySession:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

    cw_advocate_module.Session = DummySession
    cw_advocate_module.AddrValidator = DummyAddrValidator

    class DummyUnacceptableAddressException(Exception):
        pass

    cw_advocate_exceptions_module.UnacceptableAddressException = DummyUnacceptableAddressException

    flask_module = types.ModuleType("flask")
    flask_module.url_for = lambda *args, **kwargs: "/book/1"

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.gettext = _gettext

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_sql_module = types.ModuleType("sqlalchemy.sql")
    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.func = types.SimpleNamespace(lower=lambda value: value)

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.clean_html", clean_html_module)
    monkeypatch.setitem(sys.modules, "cps.cw_advocate", cw_advocate_module)
    monkeypatch.setitem(sys.modules, "cps.cw_advocate.exceptions", cw_advocate_exceptions_module)
    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql", sqlalchemy_sql_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql.expression", sqlalchemy_expression_module)

    module_name = "test_shelfmark_search_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_probe_state_authenticated_requestable(shelfmark_module):
    state = shelfmark_module.parse_shelfmark_probe_state(
        {"authenticated": True, "auth_required": True},
        {"requests_enabled": True, "defaults": {"ebook": "request_book"}},
    )

    assert state.authenticated is True
    assert state.requests_enabled is True
    assert state.ebook_mode == "request_book"
    assert state.probe_available is True


def test_select_action_uses_view_library_for_exact_duplicate(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=True,
        library_book_url="/book/12",
        hardcover_id="123",
        request_payload={"book_data": {"provider_id": "123"}},
        probe_state=None,
    )

    assert action.mode == "view_library"
    assert action.label == "Open existing CWA book"
    assert action.button_class == "btn-success"
    assert action.icon_class == "glyphicon glyphicon-book"
    assert action.hint is None


def test_build_advanced_query_uses_title_author_and_publisher_only(shelfmark_module):
    query, fields = shelfmark_module.build_shelfmark_advanced_query(
        {
            "title": "Dune",
            "authors": "Frank Herbert",
            "publisher": "Ace",
            "comments": "ignored",
            "ratinghigh": "5",
        }
    )

    assert query == "Dune Frank Herbert Ace"
    assert fields == ("title", "author", "publisher")


def test_build_advanced_query_returns_none_without_supported_external_fields(shelfmark_module):
    query, fields = shelfmark_module.build_shelfmark_advanced_query(
        {
            "comments": "desert planet",
            "ratinghigh": "5",
            "include_tag": ["science fiction"],
        }
    )

    assert query is None
    assert fields == ()


def test_select_action_falls_back_without_hardcover_id(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=False,
        library_book_url=None,
        hardcover_id=None,
        request_payload=None,
        probe_state=shelfmark_module.ShelfmarkProbeState(
            authenticated=True,
            auth_required=True,
            requests_enabled=True,
            ebook_mode="request_book",
            probe_available=True,
        ),
    )

    assert action.mode == "open"
    assert action.hint == "Direct request needs an exact Hardcover ID."


def test_select_action_falls_back_when_request_payload_is_incomplete(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=False,
        library_book_url=None,
        hardcover_id="123",
        request_payload=None,
        missing_request_requirements=("author",),
        probe_state=shelfmark_module.ShelfmarkProbeState(
            authenticated=True,
            auth_required=True,
            requests_enabled=True,
            ebook_mode="request_book",
            probe_available=True,
        ),
    )

    assert action.mode == "open"
    assert "at least one author" in action.hint


def test_select_action_uses_request_when_probe_allows_it(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=False,
        library_book_url=None,
        hardcover_id="123",
        request_payload={"book_data": {"provider_id": "123"}},
        probe_state=shelfmark_module.ShelfmarkProbeState(
            authenticated=True,
            auth_required=True,
            requests_enabled=True,
            ebook_mode="request_book",
            probe_available=True,
        ),
    )

    assert action.mode == "request"
    assert action.label == "Request in Shelfmark"
    assert action.button_class == "btn-primary"
    assert action.icon_class == "glyphicon glyphicon-send"
    assert action.hint is None


def test_select_action_defaults_to_request_when_payload_exists_before_browser_probe_runs(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=False,
        library_book_url=None,
        hardcover_id="123",
        request_payload={"book_data": {"provider_id": "123"}},
        probe_state=None,
    )

    assert action.mode == "request"
    assert action.label == "Request in Shelfmark"
    assert action.button_class == "btn-primary"
    assert action.icon_class == "glyphicon glyphicon-send"


def test_build_library_state_exposes_stable_visual_metadata(shelfmark_module):
    exact_match = shelfmark_module.build_shelfmark_library_state(
        library_match=shelfmark_module.ShelfmarkLibraryMatch("1", 5, "Existing"),
        hardcover_id="1",
    )
    external_candidate = shelfmark_module.build_shelfmark_library_state(
        library_match=None,
        hardcover_id="2",
    )
    unavailable = shelfmark_module.build_shelfmark_library_state(
        library_match=None,
        hardcover_id=None,
    )

    assert exact_match.panel_class == "panel-success"
    assert exact_match.icon_class == "glyphicon glyphicon-ok-circle"
    assert exact_match.label == "In library"
    assert exact_match.hint is None
    assert external_candidate.panel_class == "panel-info"
    assert external_candidate.icon_class == "glyphicon glyphicon-cloud-download"
    assert external_candidate.label is None
    assert external_candidate.hint is None
    assert unavailable.panel_class == "panel-warning"
    assert unavailable.icon_class == "glyphicon glyphicon-question-sign"
    assert unavailable.label == "No Hardcover ID"
    assert "Duplicate check is unavailable" in unavailable.hint


def test_build_open_url_uses_title_author_query_not_hardcover_id_syntax(shelfmark_module):
    url = shelfmark_module.build_shelfmark_open_url(
        "https://shelfmark.example.com",
        title="The Churn",
        authors=("James S. A. Corey",),
        hardcover_id="948974",
    )

    assert url == (
        "https://shelfmark.example.com/?content_type=ebook&sort=relevance"
        "&query=The+Churn+James+S.+A.+Corey&title=The+Churn&author=James+S.+A.+Corey"
    )
    assert "hardcover-id%3A948974" not in url


def test_build_result_view_links_existing_library_book(shelfmark_module):
    library_match = shelfmark_module.ShelfmarkLibraryMatch(
        hardcover_id="321",
        book_id=44,
        title="Existing Title",
    )
    book = {
        "provider": "hardcover",
        "provider_id": "321",
        "title": "External Title",
        "authors": ["Author One"],
        "identifiers": {"hardcover-id": "321"},
    }

    with mock.patch.object(shelfmark_module, "url_for", return_value="/book/44"):
        result = shelfmark_module.build_shelfmark_result_view(
            book,
            library_match=library_match,
            detail_url="/external/321",
            shelfmark_browser_base_url="https://shelfmark.example.com",
        )

    assert result.already_in_library is True
    assert result.library_book_url == "/book/44"
    assert result.action.mode == "view_library"


def test_build_result_view_normalizes_root_relative_shelfmark_cover_url_against_browser_base_path(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "cover_url": "/api/covers/hardcover_222?url=https%3A%2F%2Fcovers.example.com%2F222.jpg",
            "identifiers": {"hardcover-id": "222"},
        },
        library_match=None,
        detail_url="/external/222",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222"
        "?url=https%3A%2F%2Fcovers.example.com%2F222.jpg"
    )


def test_build_result_view_preserves_shelfmark_base_path_cover_proxy(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "cover_url": "/shelfmark/api/covers/hardcover_222?url=https%3A%2F%2Fcovers.example.com%2F222.jpg",
            "identifiers": {"hardcover-id": "222"},
        },
        library_match=None,
        detail_url="/external/222",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222"
        "?url=https%3A%2F%2Fcovers.example.com%2F222.jpg"
    )


def test_build_result_view_uses_preview_fallback_for_cover_when_cover_url_is_missing(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "preview": "/api/covers/hardcover_222?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vMjIyLmpwZw==",
            "identifiers": {"hardcover-id": "222"},
        },
        library_match=None,
        detail_url="/external/222",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vMjIyLmpwZw=="
    )


def test_build_request_payload_uses_metadata_book_shape_with_explicit_wildcard_source(shelfmark_module):
    payload = shelfmark_module.build_shelfmark_request_payload(
        {
            "provider": "hardcover",
            "provider_id": "321",
            "title": "External Title",
            "subtitle": "Library duplicate",
            "authors": ["Author One"],
            "source_url": "https://source.example.com/321",
            "identifiers": {"hardcover-id": "321"},
        }
    )

    assert payload is not None
    assert payload["book_data"]["provider"] == "hardcover"
    assert payload["book_data"]["provider_id"] == "321"
    assert payload["book_data"]["title"] == "External Title"
    assert payload["context"]["source"] == "*"
    assert payload["context"]["content_type"] == "ebook"
    assert payload["context"]["request_level"] == "book"


def test_build_request_payload_uses_search_field_fallbacks_when_authors_array_is_missing(shelfmark_module):
    payload = shelfmark_module.build_shelfmark_request_payload(
        {
            "provider": "hardcover",
            "provider_id": "444",
            "search_title": "Fallback Title",
            "search_author": "Fallback Author",
        }
    )

    assert payload is not None
    assert payload["book_data"]["provider_id"] == "444"
    assert payload["book_data"]["title"] == "Fallback Title"
    assert payload["book_data"]["author"] == "Fallback Author"


def test_build_owned_series_map_tracks_counts_and_contiguous_run(shelfmark_module):
    owned_series = shelfmark_module.build_owned_series_map(
        (
            {"series_name": "The Expanse", "book_id": 10, "series_position": "1"},
            {"series_name": "The Expanse", "book_id": 11, "series_position": "2"},
            {"series_name": "The Expanse", "book_id": 12, "series_position": "4"},
        )
    )

    expanse = owned_series["the expanse"]
    assert expanse.series_name == "The Expanse"
    assert expanse.book_count == 3
    assert expanse.owned_positions == (1.0, 2.0, 4.0)
    assert expanse.max_position == 4.0
    assert expanse.contiguous_position == 2


def test_build_workflow_state_prefers_imported_and_available_request_states(shelfmark_module):
    imported = shelfmark_module.build_shelfmark_workflow_state(
        already_in_library=True,
        hardcover_id="777",
        request_payload={"book_data": {"provider_id": "777"}},
    )
    available = shelfmark_module.build_shelfmark_workflow_state(
        already_in_library=False,
        hardcover_id="888",
        request_payload={"book_data": {"provider_id": "888"}},
    )
    missing = shelfmark_module.build_shelfmark_workflow_state(
        already_in_library=False,
        hardcover_id=None,
        request_payload=None,
    )

    assert imported is not None
    assert imported.key == "imported"
    assert imported.label == "In library"
    assert available is not None
    assert available.key == "available"
    assert available.label == "Available to request"
    assert missing is None


def test_series_context_flags_next_missing_and_owned_series(shelfmark_module):
    results = (
        shelfmark_module.build_shelfmark_result_view(
            {
                "provider": "hardcover",
                "provider_id": "201",
                "title": "Caliban's War",
                "authors": ["James S. A. Corey"],
                "series_name": "The Expanse",
                "series_position": 2,
                "identifiers": {"hardcover-id": "201"},
            },
            library_match=None,
            detail_url="/external/201",
            shelfmark_browser_base_url="https://library.example.com/shelfmark",
        ),
        shelfmark_module.build_shelfmark_result_view(
            {
                "provider": "hardcover",
                "provider_id": "202",
                "title": "Babylon's Ashes",
                "authors": ["James S. A. Corey"],
                "series_name": "The Expanse",
                "series_position": 6,
                "identifiers": {"hardcover-id": "202"},
            },
            library_match=None,
            detail_url="/external/202",
            shelfmark_browser_base_url="https://library.example.com/shelfmark",
        ),
        shelfmark_module.build_shelfmark_result_view(
            {
                "provider": "hardcover",
                "provider_id": "301",
                "title": "Random Match",
                "authors": ["Other Author"],
                "identifiers": {"hardcover-id": "301"},
            },
            library_match=None,
            detail_url="/external/301",
            shelfmark_browser_base_url="https://library.example.com/shelfmark",
        ),
    )

    contexts = shelfmark_module.build_shelfmark_series_contexts(
        results,
        {
            "the expanse": shelfmark_module.ShelfmarkOwnedSeries(
                key="the expanse",
                series_name="The Expanse",
                book_count=3,
                owned_positions=(1.0,),
                max_position=1.0,
                contiguous_position=1,
            )
        },
    )

    assert contexts[0] is not None
    assert contexts[0].is_next_missing is True
    assert contexts[0].badges[0]["label"] == "Next missing"
    assert "3 books owned" in contexts[0].facts
    assert "Owned through 1" in contexts[0].facts
    assert contexts[0].detail_value == "Next missing · 3 books owned · Owned through 1"
    assert contexts[1] is not None
    assert contexts[1].is_continuation is True
    assert contexts[1].is_next_missing is False
    assert contexts[1].badges[0]["label"] == "Continue series"
    assert contexts[1].detail_value == "Continue series · 3 books owned · Owned through 1"
    assert contexts[2] is None


def test_build_triage_state_flags_strong_candidate_for_popular_metadata_rich_match(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "777",
            "title": "Strong Candidate",
            "authors": ["Author One"],
            "description": "<p>Rich metadata and a real synopsis.</p>",
            "cover_url": "/api/covers/hardcover_777?url=x",
            "rating": 4.4,
            "ratings_count": 1200,
            "users_count": 8500,
            "pages": 384,
            "identifiers": {"hardcover-id": "777"},
        },
        library_match=None,
        detail_url="/external/777",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    quality = shelfmark_module.build_shelfmark_quality_state(result)
    triage = shelfmark_module.build_shelfmark_triage_state(result, quality_state=quality)

    assert quality is not None
    assert quality.high_confidence is True
    assert quality.metadata_complete is True
    assert quality.rating_signal is True
    assert quality.popularity_signal is True
    assert quality.facts == ("Well rated", "Popular", "Complete metadata")
    assert quality.detail_value == "High confidence · Well rated · Popular · Complete metadata"
    assert triage is not None
    assert triage.strong_candidate is True
    assert triage.metadata_rich is True
    assert triage.popularity_signal is True
    assert triage.facts == ("Popular", "Rich metadata")
    assert triage.detail_value == "Strong candidate · Popular · Rich metadata"


def test_search_results_normalize_external_and_duplicate_sections(shelfmark_module):
    books = [
        {
            "provider": "hardcover",
            "provider_id": "999",
            "title": "Already Present",
            "authors": ["Author One"],
            "identifiers": {"hardcover-id": "999"},
        },
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "identifiers": {"hardcover-id": "222"},
        },
        {
            "provider": "other",
            "provider_id": "333",
            "title": "No Hardcover ID",
            "authors": ["Author Three"],
        },
    ]

    fake_client = mock.Mock()
    fake_client.config = types.SimpleNamespace(base_url="https://shelfmark.example.com")
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=tuple(books),
        page=1,
        total_found=895,
        has_more=True,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: next(
        book for book in books if book["provider_id"] == provider_id
    )

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={"999": shelfmark_module.ShelfmarkLibraryMatch("999", 7, "Existing Title")},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ), mock.patch.object(shelfmark_module, "url_for", return_value="/book/7"):
        section = shelfmark_module.search_shelfmark_results(
            "dune",
            detail_url_builder=lambda _: "/external/dune",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    assert section.enabled is True
    assert section.available is True
    assert len(section.results) == 3
    assert [result.detail_url for result in section.results] == ["/external/dune"] * 3
    assert sum(1 for result in section.results if result.already_in_library) == 1
    assert section.summary.total_results == 3
    assert section.summary.total_available == 895
    assert section.summary.has_more is True
    assert section.summary.already_in_library == 1
    assert section.summary.external_candidates == 1
    assert section.summary.library_match_unavailable == 1
    assert section.total_available == 895
    assert section.has_more is True
    assert section.page_size == shelfmark_module.DEFAULT_SHELFMARK_LIMIT
    assert section.selected_sort == shelfmark_module.DEFAULT_SHELFMARK_SORT
    assert section.page_result_count == 3
    assert section.filters_active is True
    assert section.total_pages == 75
    assert section.visible_start == 1
    assert section.visible_end == 3
    assert section.has_previous is False
    assert section.previous_page is None
    assert section.next_page == 2
    assert section.open_search_url == (
        "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance"
        "&limit=12&page=1&query=dune"
    )
    assert [group.key for group in section.groups] == [
        "already_in_library",
        "external_candidate",
        "library_match_unavailable",
    ]
    assert [group.panel_class for group in section.groups] == [
        "panel-success",
        "panel-info",
        "panel-warning",
    ]
    assert [result.title for result in section.groups[0].results] == ["Already Present"]
    assert [result.title for result in section.groups[1].results] == ["External Candidate"]
    assert [result.title for result in section.groups[2].results] == ["No Hardcover ID"]


def test_search_results_enrich_missing_cover_from_detail_payload(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "1058398",
                "title": "Hell",
                "authors": ["C. Hallman", "J.L. Beck"],
                "identifiers": {"hardcover-id": "1058398"},
            },
        ),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "1058398",
        "title": "Hell",
        "authors": ["C. Hallman", "J.L. Beck"],
        "cover_url": "/api/covers/hardcover_1058398?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vaGVsbC5qcGc=",
        "identifiers": {"hardcover-id": "1058398"},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "hell",
            detail_url_builder=lambda _: "/external/hell",
            page=1,
        )

    assert fake_client.fetch_book.call_count == 1
    assert section.page_result_count == 1
    assert section.results[0].cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_1058398"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vaGVsbC5qcGc="
    )


def test_search_results_prefer_detail_cover_when_search_cover_differs(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "379631",
                "title": "The Two Towers",
                "authors": ["J.R.R. Tolkien"],
                "cover_url": "/api/covers/hardcover_379631?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vc2VhcmNoLmpwZw==",
                "identifiers": {"hardcover-id": "379631"},
            },
        ),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "379631",
        "title": "The Two Towers",
        "authors": ["J.R.R. Tolkien"],
        "cover_url": "/api/covers/hardcover_379631?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vZGV0YWlsLmpwZw==",
        "identifiers": {"hardcover-id": "379631"},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "the two towers",
            detail_url_builder=lambda _: "/external/two-towers",
            page=1,
        )

    assert fake_client.fetch_book.call_count == 1
    assert section.results[0].cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_379631"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vZGV0YWlsLmpwZw=="
    )


def test_search_results_promote_detail_series_facts_and_plain_description(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "379631",
                "title": "The Two Towers",
                "authors": ["J.R.R. Tolkien"],
                "description": "<i>Search</i> copy",
                "identifiers": {"hardcover-id": "379631"},
            },
        ),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "379631",
        "title": "The Two Towers",
        "authors": ["J.R.R. Tolkien"],
        "description": "<p><i>Detail</i> copy</p>",
        "rating": 4.3,
        "ratings_count": 5900,
        "users_count": 9893,
        "publish_year": 1937,
        "series_name": "The Lord of the Rings",
        "series_position": 2,
        "identifiers": {"hardcover-id": "379631"},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "the two towers",
            detail_url_builder=lambda _: "/external/two-towers",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    result = section.results[0]
    assert result.description == "Detail copy"
    assert result.description_html == "<p><i>Detail</i> copy</p>"
    assert result.series_display == "The Lord of the Rings (2)"
    assert result.facts == (
        "4.3 ★",
        "5,900 ratings",
        "9,893 readers",
        "1937",
        "The Lord of the Rings (2)",
    )
    assert result.detail_stats == (
        {"label": "Rating", "value": "4.3 ★"},
        {"label": "Ratings", "value": "5,900"},
        {"label": "Readers", "value": "9,893"},
    )


def test_search_results_promote_detail_genres_pages_and_editions(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "555",
                "title": "Guards! Guards!",
                "authors": ["Terry Pratchett"],
                "identifiers": {"hardcover-id": "555"},
            },
        ),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "555",
        "title": "Guards! Guards!",
        "authors": ["Terry Pratchett"],
        "rating": 4.2,
        "ratings_count": 12034,
        "users_count": 22221,
        "publish_year": 1989,
        "series_name": "Discworld",
        "series_position": 8,
        "genres": ["Fantasy", {"name": "Humour"}, {"tag": "Comedy"}],
        "pages": 384,
        "editions_count": 57,
        "display_fields": [
            {"label": "Lists", "value": "128", "icon": "list"},
            {"label": "Moods", "value": "Whimsical, Wry", "icon": "spark"},
            {"label": "Content warnings", "value": "Violence; Death", "icon": "warning"},
        ],
        "identifiers": {"hardcover-id": "555"},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "guards guards",
            detail_url_builder=lambda _: "/external/guards-guards",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    result = section.results[0]
    assert result.pages == 384
    assert result.editions_count == 57
    assert result.lists_count == 128
    assert result.genres == ("Fantasy", "Humour", "Comedy")
    assert result.moods == ("Whimsical", "Wry")
    assert result.content_warnings == ("Violence", "Death")
    assert result.detail_stats == (
        {"label": "Rating", "value": "4.2 ★"},
        {"label": "Ratings", "value": "12,034"},
        {"label": "Readers", "value": "22,221"},
        {"label": "Pages", "value": "384"},
        {"label": "Editions", "value": "57"},
        {"label": "Lists", "value": "128"},
    )


def test_search_results_reuse_cached_detail_metadata_without_refetch(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()
    fake_client = mock.Mock()
    fake_client.config = types.SimpleNamespace(base_url="https://shelfmark.example.com")
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "External Candidate",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_222?url=search",
                "description": "<p>Search synopsis.</p>",
                "rating": 4.1,
                "ratings_count": 1500,
                "users_count": 4200,
                "series_name": "Discworld",
                "series_position": 8,
                "identifiers": {"hardcover-id": "222"},
            },
        ),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = AssertionError("search enrichment should reuse cached detail")

    shelfmark_module._remember_shelfmark_detail_book(
        "https://shelfmark.example.com",
        "hardcover",
        "222",
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "cover_url": "/api/covers/hardcover_222?url=detail",
            "description": "<p>Detail synopsis.</p>",
            "pages": 304,
            "editions_count": 42,
            "identifiers": {"hardcover-id": "222"},
        },
    )

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "candidate",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    result = section.results[0]
    assert fake_client.fetch_book.call_count == 0
    assert result.pages == 304
    assert result.editions_count == 42
    assert result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222?url=detail"
    )


def test_search_results_default_to_requestable_with_covers(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "111",
                "title": "Duplicate",
                "authors": ["Author One"],
                "cover_url": "/api/covers/hardcover_111?url=dup",
                "identifiers": {"hardcover-id": "111"},
            },
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "Request Ready",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_222?url=req",
                "identifiers": {"hardcover-id": "222"},
            },
            {
                "provider": "hardcover",
                "provider_id": "333",
                "title": "Missing Cover",
                "authors": ["Author Three"],
                "identifiers": {"hardcover-id": "333"},
            },
        ),
        page=1,
        total_found=3,
        has_more=False,
    )

    def fetch_book(provider, provider_id):
        if provider_id == "333":
            return {
                "provider": provider,
                "provider_id": provider_id,
                "title": "Missing Cover",
                "authors": ["Author Three"],
                "identifiers": {"hardcover-id": provider_id},
            }
        return {
            "provider": provider,
            "provider_id": provider_id,
            "title": "Request Ready",
            "authors": ["Author Two"],
            "cover_url": f"/api/covers/hardcover_{provider_id}?url=x",
            "identifiers": {"hardcover-id": provider_id},
        }

    fake_client.fetch_book.side_effect = fetch_book

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={
            "111": shelfmark_module.ShelfmarkLibraryMatch("111", 7, "Existing"),
        },
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "request",
            detail_url_builder=lambda _: "/external/request",
            page=1,
        )

    assert section.filter_requestable is True
    assert section.filter_has_cover is True
    assert section.filters_active is False
    assert [result.title for result in section.results] == ["Request Ready"]


def test_search_results_apply_sort_page_size_and_visible_filters(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "Request Ready",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_222?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vMjIyLmpwZw==",
                "identifiers": {"hardcover-id": "222"},
            },
            {
                "provider": "hardcover",
                "provider_id": "333",
                "title": "No Cover",
                "authors": ["Author Three"],
                "identifiers": {"hardcover-id": "333"},
            },
        ),
        page=4,
        total_found=3221,
        has_more=True,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: {
        "provider": provider,
        "provider_id": provider_id,
        "title": "Request Ready" if provider_id == "222" else "No Cover",
        "authors": ["Author Two"] if provider_id == "222" else ["Author Three"],
        "cover_url": (
            "/api/covers/hardcover_222?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vMjIyLmpwZw=="
            if provider_id == "222"
            else None
        ),
        "identifiers": {"hardcover-id": provider_id},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "hell",
            detail_url_builder=lambda _: "/external/hell",
            page=4,
            page_size=50,
            sort="rating",
            filter_requestable=True,
            filter_has_cover=True,
        )

    fake_client.search_books.assert_called_once_with("hell", limit=50, page=4, sort="rating")
    assert section.page == 4
    assert section.page_size == 50
    assert section.selected_sort == "rating"
    assert section.filter_requestable is True
    assert section.filter_has_cover is True
    assert section.filters_active is False
    assert section.page_result_count == 2
    assert [result.title for result in section.results] == ["Request Ready"]
    assert section.total_pages == 65
    assert section.visible_start == 151
    assert section.visible_end == 152
    assert section.open_search_url == (
        "https://library.example.com/shelfmark/?content_type=ebook&sort=rating"
        "&limit=50&page=4&query=hell"
    )


def test_search_results_rank_next_missing_owned_series_above_generic_matches(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "999",
                "title": "Generic Requestable",
                "authors": ["Author One"],
                "cover_url": "/api/covers/hardcover_999?url=generic",
                "identifiers": {"hardcover-id": "999"},
            },
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "Caliban's War",
                "authors": ["James S. A. Corey"],
                "cover_url": "/api/covers/hardcover_222?url=caliban",
                "series_name": "The Expanse",
                "series_position": 2,
                "identifiers": {"hardcover-id": "222"},
            },
        ),
        page=1,
        total_found=2,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: {
        "provider": provider,
        "provider_id": provider_id,
        "title": "Caliban's War" if provider_id == "222" else "Generic Requestable",
        "authors": ["James S. A. Corey"] if provider_id == "222" else ["Author One"],
        "cover_url": f"/api/covers/hardcover_{provider_id}?url=x",
        "series_name": "The Expanse" if provider_id == "222" else None,
        "series_position": 2 if provider_id == "222" else None,
        "identifiers": {"hardcover-id": provider_id},
    }

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={
            "the expanse": shelfmark_module.ShelfmarkOwnedSeries(
                key="the expanse",
                series_name="The Expanse",
                book_count=1,
                owned_positions=(1.0,),
                max_position=1.0,
                contiguous_position=1,
            )
        },
    ):
        section = shelfmark_module.search_shelfmark_results(
            "expanse",
            detail_url_builder=lambda _: "/external/expanse",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    assert [result.title for result in section.results] == ["Caliban's War", "Generic Requestable"]
    assert section.results[0].series_context is not None
    assert section.results[0].series_context.is_next_missing is True


def test_search_results_rank_strong_candidates_above_weaker_requestables(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "999",
                "title": "Weaker Requestable",
                "authors": ["Author One"],
                "cover_url": "/api/covers/hardcover_999?url=weak",
                "identifiers": {"hardcover-id": "999"},
            },
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "Strong Candidate",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_222?url=strong",
                "description": "<p>Detailed synopsis.</p>",
                "rating": 4.3,
                "ratings_count": 5000,
                "users_count": 9000,
                "pages": 320,
                "identifiers": {"hardcover-id": "222"},
            },
        ),
        page=1,
        total_found=2,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: next(
        book for book in fake_client.search_books.return_value.books if book["provider_id"] == provider_id
    )

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "candidates",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    assert [result.title for result in section.results] == ["Strong Candidate", "Weaker Requestable"]
    assert section.results[0].quality_state is not None
    assert section.results[0].quality_state.high_confidence is True
    assert section.results[0].triage_state is not None
    assert section.results[0].triage_state.strong_candidate is True
    assert section.results[1].quality_state is not None
    assert section.results[1].quality_state.high_confidence is False
    assert section.results[1].triage_state is not None
    assert section.results[1].triage_state.strong_candidate is False


def test_search_results_filter_owned_series_and_next_missing(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "201",
                "title": "Caliban's War",
                "authors": ["James S. A. Corey"],
                "cover_url": "/api/covers/hardcover_201?url=1",
                "series_name": "The Expanse",
                "series_position": 2,
                "identifiers": {"hardcover-id": "201"},
            },
            {
                "provider": "hardcover",
                "provider_id": "202",
                "title": "Babylon's Ashes",
                "authors": ["James S. A. Corey"],
                "cover_url": "/api/covers/hardcover_202?url=2",
                "series_name": "The Expanse",
                "series_position": 6,
                "identifiers": {"hardcover-id": "202"},
            },
            {
                "provider": "hardcover",
                "provider_id": "203",
                "title": "Generic Match",
                "authors": ["Other"],
                "cover_url": "/api/covers/hardcover_203?url=3",
                "identifiers": {"hardcover-id": "203"},
            },
        ),
        page=1,
        total_found=3,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: {
        "provider": provider,
        "provider_id": provider_id,
        "title": {
            "201": "Caliban's War",
            "202": "Babylon's Ashes",
            "203": "Generic Match",
        }[provider_id],
        "authors": ["James S. A. Corey"] if provider_id in {"201", "202"} else ["Other"],
        "cover_url": f"/api/covers/hardcover_{provider_id}?url=x",
        "series_name": "The Expanse" if provider_id in {"201", "202"} else None,
        "series_position": {"201": 2, "202": 6, "203": None}[provider_id],
        "identifiers": {"hardcover-id": provider_id},
    }

    common_patches = (
        mock.patch.object(
            shelfmark_module,
            "get_shelfmark_client_config",
            return_value=shelfmark_module.ShelfmarkClientConfig(
                enabled=True,
                base_url="https://shelfmark.example.com",
                browser_base_url="https://library.example.com/shelfmark",
                username=None,
                password=None,
            ),
        ),
        mock.patch.object(
            shelfmark_module,
            "ShelfmarkClient",
            return_value=fake_client,
        ),
        mock.patch.object(
            shelfmark_module,
            "lookup_visible_library_matches",
            return_value={},
        ),
        mock.patch.object(
            shelfmark_module,
            "lookup_visible_owned_series",
            return_value={
                "the expanse": shelfmark_module.ShelfmarkOwnedSeries(
                    key="the expanse",
                    series_name="The Expanse",
                    book_count=1,
                    owned_positions=(1.0,),
                    max_position=1.0,
                    contiguous_position=1,
                )
            },
        ),
    )

    with common_patches[0], common_patches[1], common_patches[2], common_patches[3]:
        owned_section = shelfmark_module.search_shelfmark_results(
            "expanse",
            detail_url_builder=lambda _: "/external/expanse",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
            series_filter="owned",
        )

    with common_patches[0], common_patches[1], common_patches[2], common_patches[3]:
        next_missing_section = shelfmark_module.search_shelfmark_results(
            "expanse",
            detail_url_builder=lambda _: "/external/expanse",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
            series_filter="next_missing",
        )

    assert [result.title for result in owned_section.results] == ["Caliban's War", "Babylon's Ashes"]
    assert owned_section.selected_series_filter == "owned"
    assert owned_section.filters_active is True
    assert [result.title for result in next_missing_section.results] == ["Caliban's War"]
    assert next_missing_section.selected_series_filter == "next_missing"


def test_search_results_filter_strong_candidates(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "201",
                "title": "Strong Candidate",
                "authors": ["Author One"],
                "cover_url": "/api/covers/hardcover_201?url=1",
                "description": "<p>Detailed synopsis.</p>",
                "rating": 4.2,
                "ratings_count": 2100,
                "users_count": 12000,
                "pages": 400,
                "identifiers": {"hardcover-id": "201"},
            },
            {
                "provider": "hardcover",
                "provider_id": "202",
                "title": "Weaker Requestable",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_202?url=2",
                "identifiers": {"hardcover-id": "202"},
            },
        ),
        page=1,
        total_found=2,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: next(
        book for book in fake_client.search_books.return_value.books if book["provider_id"] == provider_id
    )

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "candidates",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
            triage_filter="strong",
        )

    assert [result.title for result in section.results] == ["Strong Candidate"]
    assert section.selected_triage_filter == "strong"
    assert section.filters_active is True


def test_search_results_filter_high_confidence_candidates(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "hardcover",
                "provider_id": "201",
                "title": "High Confidence",
                "authors": ["Author One"],
                "cover_url": "/api/covers/hardcover_201?url=1",
                "description": "<p>Detailed synopsis.</p>",
                "rating": 4.2,
                "ratings_count": 2100,
                "users_count": 12000,
                "pages": 400,
                "identifiers": {"hardcover-id": "201"},
            },
            {
                "provider": "hardcover",
                "provider_id": "202",
                "title": "Weak Metadata",
                "authors": ["Author Two"],
                "cover_url": "/api/covers/hardcover_202?url=2",
                "identifiers": {"hardcover-id": "202"},
            },
        ),
        page=1,
        total_found=2,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: next(
        book for book in fake_client.search_books.return_value.books if book["provider_id"] == provider_id
    )

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "candidates",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
            filter_high_confidence=True,
        )

    assert [result.title for result in section.results] == ["High Confidence"]
    assert section.filter_high_confidence is True
    assert section.filters_active is True


def test_grouping_omits_zero_count_unavailable_bucket(shelfmark_module):
    results = (
        shelfmark_module.ShelfmarkResultView(
            provider="hardcover",
            provider_id="1",
            title="Already Present",
            subtitle=None,
            authors=("Author One",),
            cover_url=None,
            description=None,
            publish_year=None,
            source_url=None,
            display_fields=(),
            rating=None,
            ratings_count=None,
            readers_count=None,
            hardcover_id="1",
            already_in_library=True,
            library_book_id=1,
            library_book_title="Existing",
            library_book_url="/book/1",
            detail_url="/external/1",
            shelfmark_base_url="https://shelfmark.example.com",
            shelfmark_open_url=(
                "https://shelfmark.example.com/?content_type=ebook&sort=relevance"
                "&query=Already+Present+Author+One&title=Already+Present&author=Author+One"
            ),
            request_payload=None,
            library_state=shelfmark_module.build_shelfmark_library_state(
                library_match=shelfmark_module.ShelfmarkLibraryMatch("1", 1, "Existing"),
                hardcover_id="1",
            ),
            action=shelfmark_module.ShelfmarkActionState(
                mode="view_library",
                label="Open existing CWA book",
                hint="Exact Hardcover ID already exists in your library.",
                button_class="btn-success",
                icon_class="glyphicon glyphicon-book",
            ),
        ),
        shelfmark_module.ShelfmarkResultView(
            provider="hardcover",
            provider_id="2",
            title="External Candidate",
            subtitle=None,
            authors=("Author Two",),
            cover_url=None,
            description=None,
            publish_year=None,
            source_url=None,
            display_fields=(),
            rating=None,
            ratings_count=None,
            readers_count=None,
            hardcover_id="2",
            already_in_library=False,
            library_book_id=None,
            library_book_title=None,
            library_book_url=None,
            detail_url="/external/2",
            shelfmark_base_url="https://shelfmark.example.com",
            shelfmark_open_url=(
                "https://shelfmark.example.com/?content_type=ebook&sort=relevance"
                "&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two"
            ),
            request_payload={"book_data": {"provider_id": "2"}},
            library_state=shelfmark_module.build_shelfmark_library_state(
                library_match=None,
                hardcover_id="2",
            ),
            action=shelfmark_module.ShelfmarkActionState(
                mode="request",
                label="Request in Shelfmark",
                hint="This browser already has a Shelfmark session and the current policy allows book-level requests.",
                button_class="btn-primary",
                icon_class="glyphicon glyphicon-send",
            ),
        ),
    )

    groups = shelfmark_module.group_shelfmark_results(results)

    assert [group.key for group in groups] == ["already_in_library", "external_candidate"]


def test_build_validator_trusts_exact_private_shelfmark_base_url(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="http://192.168.0.87:8084",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    validator = shelfmark_module.build_shelfmark_validator(config_data)

    assert validator is not None
    assert validator.is_ip_allowed("192.168.0.87", _local_addresses=[]) is True
    assert validator.is_ip_allowed("192.168.0.88", _local_addresses=[]) is False
    assert validator.is_addrinfo_allowed(
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.87", 8084)),
        _local_addresses=[],
    ) is True
    assert validator.is_addrinfo_allowed(
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.87", 8080)),
        _local_addresses=[],
    ) is False


def test_create_session_scopes_validator_to_configured_base_url(shelfmark_module):
    calls = []

    class CapturingSession:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="http://192.168.0.87:8084",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    shelfmark_module.create_shelfmark_session(config_data, session_factory=CapturingSession)

    assert "validator" in calls[0]


def test_get_client_config_uses_optional_browser_url_for_browser_actions(shelfmark_module):
    shelfmark_module.config.config_shelfmark_search = True
    shelfmark_module.config.config_shelfmark_url = "http://192.168.0.87:8084"
    shelfmark_module.config.config_shelfmark_browser_url = "https://library.example.com/shelfmark"

    config_data = shelfmark_module.get_shelfmark_client_config()

    assert config_data.enabled is True
    assert config_data.base_url == "http://192.168.0.87:8084"
    assert config_data.browser_base_url == "https://library.example.com/shelfmark"


def test_client_reports_blocked_untrusted_private_address_cleanly(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="http://192.168.0.87:8084",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    class BlockingSession:
        def get(self, *args, **kwargs):
            raise shelfmark_module.UnacceptableAddressException("blocked")

    client = shelfmark_module.ShelfmarkClient(config_data, session=BlockingSession())

    with pytest.raises(shelfmark_module.ShelfmarkIntegrationError, match="server-side request validation blocked this address"):
        client.search_books("dune")


def test_client_search_books_still_returns_normalized_results(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {
                "books": [
                    {
                        "provider": "hardcover",
                        "provider_id": "123",
                        "title": "Dune",
                        "authors": ["Frank Herbert"],
                    }
                ],
                "page": 1,
                "total_found": 42,
                "has_more": True,
            }

    calls = []

    class FakeSession:
        def get(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return FakeResponse()

    client = shelfmark_module.ShelfmarkClient(config_data, session=FakeSession())
    response = client.search_books("dune")

    assert response.books == (
        {
            "provider": "hardcover",
            "provider_id": "123",
            "title": "Dune",
            "authors": ["Frank Herbert"],
        },
    )
    assert response.page == 1
    assert response.total_found == 42
    assert response.has_more is True
    assert calls[0]["kwargs"]["params"] == {
        "query": "dune",
        "limit": shelfmark_module.DEFAULT_SHELFMARK_LIMIT,
        "sort": shelfmark_module.DEFAULT_SHELFMARK_SORT,
        "page": shelfmark_module.DEFAULT_SHELFMARK_PAGE,
        "provider": shelfmark_module.SHELFMARK_METADATA_PROVIDER,
        "content_type": shelfmark_module.SHELFMARK_CONTENT_TYPE,
    }


def test_client_search_books_respects_requested_page(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {
                "books": [],
                "page": 3,
                "total_found": 42,
                "has_more": True,
            }

    calls = []

    class FakeSession:
        def get(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return FakeResponse()

    client = shelfmark_module.ShelfmarkClient(config_data, session=FakeSession())
    response = client.search_books("dune", page=3)

    assert response.page == 3
    assert calls[0]["kwargs"]["params"]["page"] == 3


def test_client_search_books_surfaces_auth_required_guidance_without_search_account(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    class FakeResponse:
        ok = False
        status_code = 401

        @staticmethod
        def json():
            return {"error": "Unauthorized"}

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    client = shelfmark_module.ShelfmarkClient(config_data, session=FakeSession())

    with pytest.raises(shelfmark_module.ShelfmarkIntegrationError, match="Configure Shelfmark Search Username and Password"):
        client.search_books("black house")


def test_client_search_books_rejects_unexpected_payload_shape(shelfmark_module):
    config_data = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {"provider": "hardcover", "query": "dune"}

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    client = shelfmark_module.ShelfmarkClient(config_data, session=FakeSession())

    with pytest.raises(shelfmark_module.ShelfmarkIntegrationError, match="Expected a 'books' list"):
        client.search_books("dune")


def test_search_results_unavailable_without_guessing(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.side_effect = shelfmark_module.ShelfmarkIntegrationError("search failed")

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=fake_client,
    ):
        section = shelfmark_module.search_shelfmark_results(
            "dune",
            detail_url_builder=lambda _: None,
        )

    assert section.enabled is True
    assert section.available is False
    assert section.results == ()


def test_search_results_return_info_message_when_advanced_query_is_not_clean(shelfmark_module):
    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
    ):
        section = shelfmark_module.search_shelfmark_results(
            None,
            detail_url_builder=lambda _: None,
            query_label="Advanced external query",
            context_hint="Advanced external search only uses title, author, and publisher fields when present.",
            empty_message="Add a title, author, or publisher filter to include Shelfmark external results in advanced search.",
        )

    assert section.enabled is True
    assert section.available is True
    assert section.results == ()
    assert section.message == "Add a title, author, or publisher filter to include Shelfmark external results in advanced search."
    assert section.query_label == "Advanced external query"


def test_fetch_book_reuses_short_lived_detail_cache(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()

    client = shelfmark_module.ShelfmarkClient(
        shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
        session=mock.Mock(),
    )

    with mock.patch.object(client, "_ensure_authenticated") as ensure_authenticated, mock.patch.object(
        client,
        "_perform_request",
        return_value=object(),
    ) as perform_request, mock.patch.object(
        client,
        "_parse_json_response",
        return_value={"provider": "hardcover", "provider_id": "222", "title": "External Candidate"},
    ):
        first = client.fetch_book("hardcover", "222")
        second = client.fetch_book("hardcover", "222")

    assert first == second
    assert perform_request.call_count == 1
    assert ensure_authenticated.call_count == 1


def test_fetch_book_refetches_after_detail_cache_expiry(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()

    client = shelfmark_module.ShelfmarkClient(
        shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
        session=mock.Mock(),
    )

    with mock.patch.object(client, "_ensure_authenticated") as ensure_authenticated, mock.patch.object(
        client,
        "_perform_request",
        return_value=object(),
    ) as perform_request, mock.patch.object(
        client,
        "_parse_json_response",
        side_effect=[
            {"provider": "hardcover", "provider_id": "222", "title": "First"},
            {"provider": "hardcover", "provider_id": "222", "title": "Second"},
        ],
    ):
        with mock.patch.object(shelfmark_module, "monotonic", return_value=100.0):
            first = client.fetch_book("hardcover", "222")
        with mock.patch.object(
            shelfmark_module,
            "monotonic",
            return_value=100.0 + shelfmark_module.SHELFMARK_DETAIL_CACHE_TTL_SECONDS + 1,
        ):
            second = client.fetch_book("hardcover", "222")

    assert first["title"] == "First"
    assert second["title"] == "Second"
    assert perform_request.call_count == 2
    assert ensure_authenticated.call_count == 2


def test_fetch_book_evicts_oldest_detail_cache_entry_when_bounded(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()

    client = shelfmark_module.ShelfmarkClient(
        shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            browser_base_url="https://library.example.com/shelfmark",
            username=None,
            password=None,
        ),
        session=mock.Mock(),
    )

    with mock.patch.object(client, "_ensure_authenticated"), mock.patch.object(
        client,
        "_perform_request",
        return_value=object(),
    ) as perform_request, mock.patch.object(
        client,
        "_parse_json_response",
        side_effect=[
            {"provider": "hardcover", "provider_id": "111", "title": "One"},
            {"provider": "hardcover", "provider_id": "222", "title": "Two"},
            {"provider": "hardcover", "provider_id": "111", "title": "One Again"},
        ],
    ), mock.patch.object(shelfmark_module, "SHELFMARK_DETAIL_CACHE_MAX_ENTRIES", 1):
        first = client.fetch_book("hardcover", "111")
        second = client.fetch_book("hardcover", "222")
        refetched = client.fetch_book("hardcover", "111")

    assert first["title"] == "One"
    assert second["title"] == "Two"
    assert refetched["title"] == "One Again"
    assert perform_request.call_count == 3


def test_normalize_shelfmark_cover_url_reuses_cached_resolution(shelfmark_module):
    shelfmark_module.clear_shelfmark_cover_cache()
    original_urljoin = shelfmark_module.urljoin

    with mock.patch.object(shelfmark_module, "urljoin", side_effect=original_urljoin) as urljoin_mock:
        first = shelfmark_module._normalize_shelfmark_cover_url(
            "https://library.example.com/shelfmark",
            "api/covers/hardcover_222?url=detail",
        )
        second = shelfmark_module._normalize_shelfmark_cover_url(
            "https://library.example.com/shelfmark",
            "api/covers/hardcover_222?url=detail",
        )

    assert first == "https://library.example.com/shelfmark/api/covers/hardcover_222?url=detail"
    assert second == first
    assert urljoin_mock.call_count == 1
