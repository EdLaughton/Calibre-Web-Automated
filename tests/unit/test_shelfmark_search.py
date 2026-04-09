# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
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
        Books=types.SimpleNamespace(id=mock.Mock(), title=mock.Mock()),
    )
    dummy_db.Identifiers.val.label = lambda name: name
    dummy_db.Books.id.label = lambda name: name
    dummy_db.Books.title.label = lambda name: name

    cps_module = types.ModuleType("cps")
    cps_module.calibre_db = types.SimpleNamespace(session=mock.Mock(), common_filters=lambda *args, **kwargs: "COMMON_FILTER")
    cps_module.config = types.SimpleNamespace(
        config_shelfmark_search=False,
        config_shelfmark_url="",
        config_shelfmark_username="",
        config_shelfmark_password_e="",
    )
    cps_module.db = dummy_db
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)

    cw_advocate_module = types.ModuleType("cps.cw_advocate")

    class DummySession:
        pass

    cw_advocate_module.Session = DummySession

    flask_module = types.ModuleType("flask")
    flask_module.url_for = lambda *args, **kwargs: "/book/1"

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.gettext = _gettext

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_sql_module = types.ModuleType("sqlalchemy.sql")
    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.func = types.SimpleNamespace(lower=lambda value: value)

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.cw_advocate", cw_advocate_module)
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
    assert "hardcover-id" in action.hint


def test_select_action_falls_back_when_request_payload_is_incomplete(shelfmark_module):
    action = shelfmark_module.select_shelfmark_action(
        already_in_library=False,
        library_book_url=None,
        hardcover_id="123",
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
    assert "enough exact metadata" in action.hint


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
    assert external_candidate.panel_class == "panel-info"
    assert external_candidate.icon_class == "glyphicon glyphicon-cloud-download"
    assert unavailable.panel_class == "panel-warning"
    assert unavailable.icon_class == "glyphicon glyphicon-question-sign"


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
            shelfmark_base_url="https://shelfmark.example.com",
        )

    assert result.already_in_library is True
    assert result.library_book_url == "/book/44"
    assert result.action.mode == "view_library"


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
    fake_client.search_books.return_value = books

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
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
    ), mock.patch.object(shelfmark_module, "url_for", return_value="/book/7"):
        section = shelfmark_module.search_shelfmark_results(
            "dune",
            detail_url_builder=lambda _: "/external/dune",
        )

    assert section.enabled is True
    assert section.available is True
    assert len(section.results) == 3
    assert section.results[0].already_in_library is True
    assert section.results[0].detail_url == "/external/dune"
    assert section.summary.total_results == 3
    assert section.summary.already_in_library == 1
    assert section.summary.external_candidates == 1
    assert section.summary.library_match_unavailable == 1
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


def test_search_results_unavailable_without_guessing(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.search_books.side_effect = shelfmark_module.ShelfmarkIntegrationError("search failed")

    with mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=shelfmark_module.ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
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
