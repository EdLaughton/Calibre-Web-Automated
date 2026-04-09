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
        config_shelfmark_browser_url="",
        config_shelfmark_username="",
        config_shelfmark_password_e="",
    )
    cps_module.db = dummy_db
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)

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
    assert action.hint == "Exact Hardcover ID already exists in your library."


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
    assert "no exact Hardcover ID" in action.hint


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


def test_build_result_view_normalizes_root_relative_shelfmark_cover_url(shelfmark_module):
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
        "https://library.example.com/api/covers/hardcover_222"
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
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=tuple(books),
        page=1,
        total_found=895,
        has_more=True,
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
    ), mock.patch.object(shelfmark_module, "url_for", return_value="/book/7"):
        section = shelfmark_module.search_shelfmark_results(
            "dune",
            detail_url_builder=lambda _: "/external/dune",
            page=1,
        )

    assert section.enabled is True
    assert section.available is True
    assert len(section.results) == 3
    assert section.results[0].already_in_library is True
    assert section.results[0].detail_url == "/external/dune"
    assert section.summary.total_results == 3
    assert section.summary.total_available == 895
    assert section.summary.has_more is True
    assert section.summary.already_in_library == 1
    assert section.summary.external_candidates == 1
    assert section.summary.library_match_unavailable == 1
    assert section.total_available == 895
    assert section.has_more is True
    assert section.page_size == shelfmark_module.DEFAULT_SHELFMARK_LIMIT
    assert section.total_pages == 75
    assert section.visible_start == 1
    assert section.visible_end == 3
    assert section.has_previous is False
    assert section.previous_page is None
    assert section.next_page == 2
    assert section.open_search_url == "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&page=1&query=dune"
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
