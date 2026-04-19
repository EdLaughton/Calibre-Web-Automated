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
        config_shelfmark_preferred_release_enabled=False,
        config_shelfmark_preferred_release_provider="",
        config_shelfmark_preferred_release_content_type="ebook",
        config_shelfmark_preferred_release_ranking="seeders_desc",
    )
    cps_module.db = dummy_db
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)
    cps_module.__path__ = []
    clean_html_module = types.ModuleType("cps.clean_html")
    clean_html_module.clean_string = lambda value, book_id=0: value
    metadata_provider_module = types.ModuleType("cps.metadata_provider")
    metadata_provider_module.__path__ = []
    hardcover_provider_module = types.ModuleType("cps.metadata_provider.hardcover")

    class DummyHardcover:
        def search(self, query):
            return []

    hardcover_provider_module.Hardcover = DummyHardcover

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

    markupsafe_module = types.ModuleType("markupsafe")

    class DummyMarkup(str):
        def striptags(self):
            import re as _re

            return _re.sub(r"<[^>]+>", "", self)

    markupsafe_module.Markup = DummyMarkup

    requests_module = types.ModuleType("requests")
    requests_module.RequestException = Exception

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_sql_module = types.ModuleType("sqlalchemy.sql")
    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.func = types.SimpleNamespace(lower=lambda value: value)

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.clean_html", clean_html_module)
    monkeypatch.setitem(sys.modules, "cps.metadata_provider", metadata_provider_module)
    monkeypatch.setitem(sys.modules, "cps.metadata_provider.hardcover", hardcover_provider_module)
    monkeypatch.setitem(sys.modules, "cps.cw_advocate", cw_advocate_module)
    monkeypatch.setitem(sys.modules, "cps.cw_advocate.exceptions", cw_advocate_exceptions_module)
    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)
    monkeypatch.setitem(sys.modules, "markupsafe", markupsafe_module)
    monkeypatch.setitem(sys.modules, "requests", requests_module)
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


def test_get_preferred_release_settings_defaults_off(shelfmark_module):
    settings = shelfmark_module.get_shelfmark_preferred_release_settings()

    assert settings.enabled is False
    assert settings.provider == ""
    assert settings.content_type == "ebook"
    assert settings.ranking == "seeders_desc"


def test_get_preferred_release_settings_normalizes_invalid_values(shelfmark_module):
    shelfmark_module.config.config_shelfmark_preferred_release_enabled = True
    shelfmark_module.config.config_shelfmark_preferred_release_provider = "  MyAnonamouse  "
    shelfmark_module.config.config_shelfmark_preferred_release_content_type = "AUDIOBOOK"
    shelfmark_module.config.config_shelfmark_preferred_release_ranking = "unknown"

    settings = shelfmark_module.get_shelfmark_preferred_release_settings()

    assert settings.enabled is True
    assert settings.provider == "MyAnonamouse"
    assert settings.content_type == "audiobook"
    assert settings.ranking == "seeders_desc"


def test_get_shelfmark_client_config_uses_stored_password_when_diagnostic_password_blank(shelfmark_module):
    shelfmark_module.config.config_shelfmark_password_e = "stored-secret"

    config_data = shelfmark_module.get_shelfmark_client_config(
        {
            "config_shelfmark_url": "https://shelfmark.example.com",
            "config_shelfmark_password_e": "",
        }
    )

    assert config_data.base_url == "https://shelfmark.example.com"
    assert config_data.password == "stored-secret"


def test_run_shelfmark_settings_diagnostics_discovers_sources_and_indexers(shelfmark_module):
    class FakeClient:
        def __init__(self, config_data):
            self.config = config_data
            self.authenticated = False

        def auth_check(self):
            return {"authenticated": self.authenticated, "auth_required": True}

        def authenticate_search_account(self):
            self.authenticated = True
            return None

        def request_policy(self):
            return {
                "requests_enabled": True,
                "source_modes": [
                    {
                        "source": "prowlarr",
                        "supported_content_types": ["ebook"],
                        "modes": {"ebook": "request_release"},
                    },
                    {
                        "source": "direct_download",
                        "supported_content_types": ["ebook"],
                        "modes": {"ebook": "download"},
                    },
                ],
            }

        def release_sources(self):
            return (
                {
                    "name": "prowlarr",
                    "display_name": "Prowlarr",
                    "enabled": True,
                    "supported_content_types": ["ebook"],
                },
                {
                    "name": "direct_download",
                    "display_name": "Direct Download",
                    "enabled": True,
                    "supported_content_types": ["ebook"],
                },
            )

        def probe_release_lookup(self, source, *, content_type, **kwargs):
            assert source == "prowlarr"
            assert content_type == "ebook"
            return True, {
                "column_config": {
                    "available_indexers": ["MyAnonamouse", "Bibliotik"],
                },
                "releases": [],
            }

    diagnostics = shelfmark_module.run_shelfmark_settings_diagnostics(
        {
            "config_shelfmark_url": "https://shelfmark.example.com",
            "config_shelfmark_username": "search",
            "config_shelfmark_password_e": "secret",
            "config_shelfmark_preferred_release_content_type": "ebook",
            "config_shelfmark_preferred_release_provider": "prowlarr",
        },
        client_factory=FakeClient,
    )

    assert diagnostics.success is True
    assert diagnostics.selected_probe_source == "prowlarr"
    assert [check.key for check in diagnostics.checks] == [
        "base_url",
        "auth",
        "request_policy",
        "release_lookup",
        "provider_options",
    ]
    assert diagnostics.checks[-1].status == "ok"
    assert [option.value for option in diagnostics.provider_options] == [
        "direct_download",
        "prowlarr",
        "Bibliotik",
        "MyAnonamouse",
    ]


def test_run_shelfmark_settings_diagnostics_reports_missing_base_url(shelfmark_module):
    diagnostics = shelfmark_module.run_shelfmark_settings_diagnostics(
        {
            "config_shelfmark_url": "",
            "config_shelfmark_preferred_release_content_type": "ebook",
        }
    )

    assert diagnostics.success is False
    assert diagnostics.checks[0].key == "base_url"
    assert diagnostics.checks[0].status == "error"
    assert diagnostics.provider_options == ()


def test_run_shelfmark_settings_diagnostics_keeps_manual_fallback_when_indexers_not_exposed(shelfmark_module):
    class FakeClient:
        def __init__(self, config_data):
            self.config = config_data

        def auth_check(self):
            return {"authenticated": True, "auth_required": False}

        def request_policy(self):
            return {
                "requests_enabled": True,
                "source_modes": [
                    {
                        "source": "direct_download",
                        "supported_content_types": ["ebook"],
                        "modes": {"ebook": "download"},
                    }
                ],
            }

        def release_sources(self):
            return (
                {
                    "name": "direct_download",
                    "display_name": "Direct Download",
                    "enabled": True,
                    "supported_content_types": ["ebook"],
                },
            )

        def probe_release_lookup(self, source, *, content_type, **kwargs):
            assert source == "direct_download"
            return True, {"releases": []}

    diagnostics = shelfmark_module.run_shelfmark_settings_diagnostics(
        {
            "config_shelfmark_url": "https://shelfmark.example.com",
            "config_shelfmark_preferred_release_content_type": "ebook",
        },
        client_factory=FakeClient,
    )

    assert diagnostics.success is True
    assert [option.value for option in diagnostics.provider_options] == ["direct_download"]
    assert diagnostics.checks[-1].key == "provider_options"
    assert diagnostics.checks[-1].status == "warning"
    assert "custom" in diagnostics.provider_options_message.lower()


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
        "https://shelfmark.example.com/?content_type=ebook&sort=popularity"
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


def test_resolve_display_edition_prefers_non_audio_editions_for_detail_metadata(shelfmark_module):
    book = {
        "edition": {
            "id": "inline-audio",
            "edition_format": "Audiobook",
            "audio_seconds": 41234,
            "pages": None,
        },
        "default_audio_edition": {
            "id": "audio",
            "edition_format": "Audiobook",
            "audio_seconds": 41234,
        },
        "default_physical_edition": {
            "id": "hardcover",
            "edition_format": "Hardcover",
            "physical_format": "Hardcover",
            "pages": 544,
        },
        "default_ebook_edition": {
            "id": "ebook",
            "edition_format": "Ebook",
            "pages": 544,
        },
    }

    edition = shelfmark_module._resolve_display_edition(book)

    assert edition is not None
    assert edition["id"] == "ebook"
    assert shelfmark_module._is_audio_edition(edition) is False


def test_resolve_shelfmark_authors_prefers_author_contributions_over_audio_narrators(shelfmark_module):
    book = {
        "authors": ["Peter V. Brett", "Colin Mace"],
        "contributions": [
            {"contribution": "Narrator", "author": {"name": "Colin Mace"}},
            {"contribution": "Author", "author": {"name": "Peter V. Brett"}},
        ],
    }

    assert shelfmark_module._resolve_shelfmark_authors(book) == ["Peter V. Brett"]


def test_resolve_shelfmark_authors_strips_audio_contributor_names_from_fallback_authors(shelfmark_module):
    book = {
        "authors": ["Peter V. Brett", "Colin Mace"],
        "cached_contributors": [
            {"role": "Narrator", "author": {"name": "Colin Mace"}},
        ],
    }

    assert shelfmark_module._resolve_shelfmark_authors(book) == ["Peter V. Brett"]


def test_resolve_shelfmark_authors_prefers_non_audio_edition_contributors_over_audio_narrators(shelfmark_module):
    book = {
        "authors": ["Peter V. Brett", "Colin Mace"],
        "default_ebook_edition_id": "ebook-ed",
        "default_audio_edition_id": "audio-ed",
        "default_ebook_edition": {
            "id": "ebook-ed",
            "edition_format": "Ebook",
            "reading_format": {"format": "ebook"},
            "contributions": [
                {"contribution": "Author", "author": {"name": "Peter V. Brett"}},
            ],
        },
        "default_audio_edition": {
            "id": "audio-ed",
            "edition_format": "Audiobook",
            "reading_format": {"format": "audiobook"},
            "audio_seconds": 41234,
            "contributions": [
                {"contribution": "Narrator", "author": {"name": "Colin Mace"}},
            ],
        },
    }

    assert shelfmark_module._resolve_shelfmark_authors(book) == ["Peter V. Brett"]


def test_build_result_view_capitalizes_moods_and_content_warnings(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "moods": ["hopeful", "dark"],
            "content_warnings": ["misogyny", "graphic violence"],
            "identifiers": {"hardcover-id": "222"},
        },
        library_match=None,
        detail_url="/external/222",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.moods == ("Hopeful", "Dark")
    assert result.content_warnings == ("Misogyny", "Graphic Violence")


def test_build_result_view_filters_numeric_garbage_from_moods_and_content_warnings(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "External Candidate",
            "authors": ["Author Two"],
            "moods": ["dark", "1735854282725"],
            "content_warnings": ["misogyny", "1735854282725"],
            "identifiers": {"hardcover-id": "222"},
        },
        library_match=None,
        detail_url="/external/222",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.moods == ("Dark",)
    assert result.content_warnings == ("Misogyny",)


def test_apply_hardcover_query_enrichment_backfills_request_result_metadata(shelfmark_module, monkeypatch):
    class FakeRecord:
        def __init__(self):
            self.identifiers = {"hardcover-id": "222", "isbn": "9780316066525"}
            self.title = "The Painted Man"
            self.subtitle = ""
            self.authors = ["Peter V. Brett"]
            self.description = "<p>Nightfall brings demons.</p>"
            self.cover = "https://covers.example.com/painted-man.jpg"
            self.series = "The Demon Cycle"
            self.series_index = 1
            self.publishedDate = "2008-01-01"
            self.publisher = "Del Rey"
            self.languages = ["English"]
            self.format = "Ebook"
            self.pages = 590
            self.rating = 4.2
            self.ratings_count = 484
            self.readers_count = 1128
            self.url = "https://hardcover.app/books/the-painted-man"

    hardcover_module = sys.modules["cps.metadata_provider.hardcover"]
    monkeypatch.setattr(hardcover_module, "Hardcover", lambda: types.SimpleNamespace(search=lambda query: [FakeRecord()]))

    enriched = shelfmark_module._apply_hardcover_query_enrichment(
        "painted man",
        (
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "The Painted Man",
                "authors": ["Peter V. Brett"],
                "identifiers": {"hardcover-id": "222", "isbn": "9780316066525"},
                "description": "",
            },
        ),
    )

    assert len(enriched) == 1
    assert enriched[0]["pages"] == 590
    assert enriched[0]["series_name"] == "The Demon Cycle"
    assert enriched[0]["ratings_count"] == 484
    assert enriched[0]["readers_count"] == 1128


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


def test_build_result_view_omits_unreliable_subtitle_from_presentation(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "444",
            "title": "Mort",
            "subtitle": "Trois soeurcières",
            "authors": ["Terry Pratchett"],
            "identifiers": {"hardcover-id": "444"},
        },
        library_match=None,
        detail_url="/external/444",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert result.subtitle is None


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
    assert "3 books owned in this series" in contexts[0].facts
    assert "Owned through 1" in contexts[0].facts
    assert contexts[0].detail_value == "Next missing · 3 books owned in this series · Owned through 1"
    assert contexts[1] is not None
    assert contexts[1].is_continuation is True
    assert contexts[1].is_next_missing is False
    assert contexts[1].badges[0]["label"] == "Owned series"
    assert contexts[1].detail_value == "Owned series · 3 books owned in this series · Owned through 1"
    assert contexts[2] is None


def test_result_view_preserves_multiple_series_memberships(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "501",
            "title": "The Well of Ascension",
            "authors": ["Brandon Sanderson"],
            "book_series": [
                {
                    "featured": True,
                    "position": 7,
                    "series": {"name": "Cosmere", "slug": "cosmere"},
                },
                {
                    "featured": False,
                    "position": 2,
                    "series": {"name": "Mistborn", "slug": "mistborn"},
                },
            ],
            "identifiers": {"hardcover-id": "501"},
        },
        library_match=None,
        detail_url="/external/501",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )

    assert [membership.name for membership in result.series_memberships] == [
        "Cosmere",
        "Mistborn",
    ]
    assert [entry["display"] for entry in result.series_entries] == [
        "Cosmere (7)",
        "Mistborn (2)",
    ]


def test_multi_series_context_prefers_actionable_subseries_for_primary_display(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "502",
            "title": "The Bands of Mourning",
            "authors": ["Brandon Sanderson"],
            "book_series": [
                {
                    "featured": True,
                    "position": 10,
                    "series": {"name": "Cosmere", "slug": "cosmere"},
                },
                {
                    "featured": False,
                    "position": 3,
                    "series": {"name": "Mistborn Era 2", "slug": "mistborn-era-2"},
                },
            ],
            "identifiers": {"hardcover-id": "502"},
        },
        library_match=None,
        detail_url="/external/502",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )
    contexts = shelfmark_module.build_shelfmark_series_membership_contexts(
        (result,),
        {
            "cosmere": shelfmark_module.ShelfmarkOwnedSeries(
                key="cosmere",
                series_name="Cosmere",
                book_count=8,
                owned_positions=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
                max_position=6.0,
                contiguous_position=6,
            ),
            "mistborn era 2": shelfmark_module.ShelfmarkOwnedSeries(
                key="mistborn era 2",
                series_name="Mistborn Era 2",
                book_count=2,
                owned_positions=(1.0, 2.0),
                max_position=2.0,
                contiguous_position=2,
            ),
        },
    )[0]
    result = shelfmark_module.apply_primary_series_context(
        shelfmark_module.replace(result, series_contexts=contexts),
    )

    assert len(contexts) == 2
    assert result.best_series_context is not None
    assert result.best_series_context.series_name == "Mistborn Era 2"
    assert result.best_series_context.is_next_missing is True
    assert result.series_display == "Mistborn Era 2 (3)"
    assert result.secondary_series_note == "Also in Cosmere"
    assert result.facts[-1] == "Mistborn Era 2 (3)"


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
    assert section.pagination_mode == "shelfmark"
    assert section.progressive_refinement is True
    assert section.progressive_refinement_note == (
        "Shelfmark totals are shown as-is. Visible rows refine as details load."
    )
    assert section.total_pages == 75
    assert section.visible_start == 1
    assert section.visible_end == 3
    assert section.has_previous is False
    assert section.previous_page is None
    assert section.next_page == 2
    assert section.open_search_url == (
        "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity"
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


def test_search_results_defer_missing_cover_until_detail_is_requested(shelfmark_module):
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
            filter_requestable=False,
            filter_has_cover=False,
        )
        detail_result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "1058398",
            detail_url="/external/hell",
        )

    result = section.results[0]
    assert fake_client.fetch_book.call_count == 1
    assert section.page_result_count == 1
    assert result.cover_url is None
    assert result.needs_progressive_enrichment is True
    assert result.progressive_filter_pending is False
    assert detail_result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_1058398"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vaGVsbC5qcGc="
    )


def test_search_results_keep_search_cover_until_detail_is_requested(shelfmark_module):
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
            filter_requestable=False,
            filter_has_cover=False,
        )
        detail_result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "379631",
            detail_url="/external/two-towers",
        )

    result = section.results[0]
    assert fake_client.fetch_book.call_count == 1
    assert result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_379631"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vc2VhcmNoLmpwZw=="
    )
    assert result.needs_progressive_enrichment is True
    assert detail_result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_379631"
        "?url=aHR0cHM6Ly9jb3ZlcnMuZXhhbXBsZS5jb20vZGV0YWlsLmpwZw=="
    )


def test_fetch_shelfmark_detail_promotes_series_facts_and_plain_description(shelfmark_module):
    fake_client = mock.Mock()
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
        result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "379631",
            detail_url="/external/two-towers",
        )

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
    assert result.series_url == "https://hardcover.app/series/the-lord-of-the-rings"
    assert result.detail_stats == ()


def test_fetch_shelfmark_detail_promotes_genres_pages_and_editions(shelfmark_module):
    fake_client = mock.Mock()
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
        result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "555",
            detail_url="/external/guards-guards",
        )

    assert result.facts == (
        "4.2 ★",
        "12,034 ratings",
        "22,221 readers",
        "1989",
        "384 pages",
        "Discworld (8)",
    )
    assert result.pages == 384
    assert result.editions_count == 57
    assert result.lists_count == 128
    assert result.series_url == "https://hardcover.app/series/discworld"
    assert result.genres == ("Fantasy", "Humour", "Comedy")
    assert result.moods == ("Whimsical", "Wry")
    assert result.content_warnings == ("Violence", "Death")
    assert result.detail_stats == (
        {"label": "Editions", "value": "57"},
        {"label": "Lists", "value": "128"},
    )


def test_fetch_shelfmark_detail_prefers_schema_relationships_when_available(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "777",
        "title": "The Wee Free Men",
        "subtitle": "Discworld 30",
        "authors": ["Terry Pratchett"],
        "rating": 4.4,
        "ratings_count": 4102,
        "users_count": 8123,
        "release_date": "2003-05-01",
        "slug": "the-wee-free-men",
        "pages": 999,
        "series_name": "Wrong Flat Series",
        "series_position": 99,
        "featured_book_series": {
            "position": 30,
            "series": {
                "name": "Discworld",
                "slug": "discworld",
                "primary_books_count": 41,
            },
        },
        "default_ebook_edition": {
            "pages": 304,
            "subtitle": "Discworld 30",
            "reading_format": {"format": "E-Book"},
        },
        "editions_aggregate": {"aggregate": {"count": 18}},
        "taggings": [
            {
                "tag": {
                    "tag": "Fantasy",
                    "tag_category": {"category": "Genre"},
                },
                "spoiler": False,
            },
            {
                "tag": {
                    "tag": "Funny",
                    "tag_category": {"category": "Mood"},
                },
                "spoiler": False,
            },
            {
                "tag": {
                    "tag": "Violence",
                    "tag_category": {"category": "Content warning"},
                },
                "spoiler": False,
            },
            {
                "tag": {
                    "tag": "Death",
                    "tag_category": {"category": "Content warnings"},
                },
                "spoiler": True,
            },
        ],
        "identifiers": {"hardcover-id": "777"},
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
        result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "777",
            detail_url="/external/the-wee-free-men",
        )

    assert result.subtitle == "Discworld 30"
    assert result.publish_year == 2003
    assert result.source_url == "https://hardcover.app/books/the-wee-free-men"
    assert result.series_display == "Discworld (30)"
    assert result.series_url == "https://hardcover.app/series/discworld"
    assert result.series_count == 41
    assert result.pages == 304
    assert result.editions_count == 18
    assert result.genres == ("Fantasy",)
    assert result.moods == ("Funny",)
    assert result.content_warnings == ("Violence", "Death")
    assert "304 pages" in result.facts
    assert "Discworld (30)" in result.facts


def test_fetch_shelfmark_detail_prefers_direct_hardcover_book_by_id_when_available(shelfmark_module):
    fake_client = mock.Mock()
    fake_client.fetch_book.return_value = {
        "provider": "hardcover",
        "provider_id": "379631",
        "title": "Mort",
        "authors": ["Terry Pratchett"],
        "description": "<p>Shelfmark detail copy</p>",
        "publish_year": 1987,
        "identifiers": {"hardcover-id": "379631"},
    }
    direct_book = {
        "id": 379631,
        "title": "Mort",
        "subtitle": "A Discworld Novel",
        "slug": "mort",
        "description": "<p>Direct Hardcover copy</p>",
        "release_date": "1987-11-12",
        "pages": 272,
        "rating": 4.1,
        "ratings_count": 1295,
        "users_count": 2298,
        "editions_count": 34,
        "book_series": [
            {
                "featured": True,
                "position": 4,
                "series": {"name": "Discworld", "slug": "discworld", "primary_books_count": 41},
            },
            {
                "featured": False,
                "position": 3,
                "series": {"name": "Death", "slug": "death", "primary_books_count": 5},
            },
        ],
        "featured_book_series": {
            "featured": True,
            "position": 4,
            "series": {"name": "Discworld", "slug": "discworld", "primary_books_count": 41},
        },
        "default_ebook_edition": {
            "pages": 272,
            "subtitle": "A Discworld Novel",
            "edition_format": "EBOOK",
        },
        "taggings": [
            {
                "spoiler": False,
                "tag": {
                    "tag": "Fantasy",
                    "slug": "fantasy",
                    "tag_category": {"category": "Genre", "slug": "genre"},
                },
            },
            {
                "spoiler": False,
                "tag": {
                    "tag": "funny",
                    "slug": "funny",
                    "tag_category": {"category": "Mood", "slug": "mood"},
                },
            },
            {
                "spoiler": True,
                "tag": {
                    "tag": "Death",
                    "slug": "death-warning",
                    "tag_category": {"category": "Content warning", "slug": "content-warning"},
                },
            },
        ],
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
        "_fetch_direct_hardcover_detail_book",
        return_value=direct_book,
    ) as direct_fetch, mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "379631",
            detail_url="/external/mort",
        )

    direct_fetch.assert_called_once_with("379631")
    assert result.subtitle == "A Discworld Novel"
    assert result.description == "Direct Hardcover copy"
    assert result.publish_year == 1987
    assert result.series_display == "Discworld (4)"
    assert result.series_url == "https://hardcover.app/series/discworld"
    assert result.series_count == 41
    assert [membership.name for membership in result.series_memberships] == [
        "Discworld",
        "Death",
    ]
    assert [entry["display"] for entry in result.series_entries] == [
        "Discworld (4)",
        "Death (3)",
    ]
    assert result.facts == (
        "4.1 ★",
        "1,295 ratings",
        "2,298 readers",
        "1987",
        "272 pages",
        "Discworld (4)",
    )
    assert result.genres == ("Fantasy",)
    assert result.moods == ("Funny",)
    assert result.content_warnings == ("Death",)


def test_search_results_leave_cached_detail_for_on_demand_fetch(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()
    shelfmark_module.clear_shelfmark_scan_cache()
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
    config = shelfmark_module.ShelfmarkClientConfig(
        enabled=True,
        base_url="https://shelfmark.example.com",
        browser_base_url="https://library.example.com/shelfmark",
        username=None,
        password=None,
    )

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
        return_value=config,
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

    assert fake_client.fetch_book.call_count == 0
    search_result = section.results[0]
    assert search_result.pages is None
    assert search_result.editions_count is None
    assert search_result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222?url=search"
    )
    assert search_result.needs_progressive_enrichment is True

    real_client = shelfmark_module.ShelfmarkClient(config, session=mock.Mock())
    with mock.patch.object(real_client, "_ensure_authenticated") as ensure_authenticated, mock.patch.object(
        real_client,
        "_perform_request",
        side_effect=AssertionError("detail fetch should reuse cached payload"),
    ), mock.patch.object(
        shelfmark_module,
        "get_shelfmark_client_config",
        return_value=config,
    ), mock.patch.object(
        shelfmark_module,
        "ShelfmarkClient",
        return_value=real_client,
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_library_matches",
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        detail_result = shelfmark_module.fetch_shelfmark_detail(
            "hardcover",
            "222",
            detail_url="/external/candidate",
        )

    assert ensure_authenticated.call_count == 0
    assert detail_result.pages == 304
    assert detail_result.editions_count == 42
    assert detail_result.cover_url == (
        "https://library.example.com/shelfmark/api/covers/hardcover_222?url=detail"
    )


def test_search_results_cache_requested_shelfmark_pages_without_global_scan(shelfmark_module):
    shelfmark_module.clear_shelfmark_scan_cache()
    fake_client = mock.Mock()
    fake_client.config = types.SimpleNamespace(base_url="https://shelfmark.example.com")

    first_page_books = tuple(
        {
            "provider": "hardcover",
            "provider_id": str(index),
            "title": f"Book {index}",
            "authors": [f"Author {index}"],
            "identifiers": {"hardcover-id": str(index)},
        }
        for index in range(1, 13)
    )
    second_page_books = tuple(
        {
            "provider": "hardcover",
            "provider_id": str(index),
            "title": f"Book {index}",
            "authors": [f"Author {index}"],
            "identifiers": {"hardcover-id": str(index)},
        }
        for index in range(13, 25)
    )

    def search_books(query, limit, page, sort):
        assert query == "candidate"
        assert limit == shelfmark_module.DEFAULT_SHELFMARK_LIMIT
        assert sort == "popularity"
        if page == 1:
            return shelfmark_module.ShelfmarkSearchResponse(
                books=first_page_books,
                page=1,
                total_found=101,
                has_more=True,
            )
        if page == 2:
            return shelfmark_module.ShelfmarkSearchResponse(
                books=second_page_books,
                page=2,
                total_found=101,
                has_more=False,
            )
        raise AssertionError(f"unexpected raw page {page}")

    fake_client.search_books.side_effect = search_books

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
        first_section = shelfmark_module.search_shelfmark_results(
            "candidate",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
        )
        second_section = shelfmark_module.search_shelfmark_results(
            "candidate",
            detail_url_builder=lambda _: "/external/candidate",
            page=1,
        )
        third_section = shelfmark_module.search_shelfmark_results(
            "candidate",
            detail_url_builder=lambda _: "/external/candidate",
            page=2,
        )

    assert fake_client.search_books.call_count == 2
    assert first_section.page_result_count == 12
    assert second_section.page_result_count == 12
    assert third_section.page_result_count == 12
    assert [call.kwargs for call in fake_client.search_books.call_args_list] == [
        {"limit": shelfmark_module.DEFAULT_SHELFMARK_LIMIT, "page": 1, "sort": "popularity"},
        {"limit": shelfmark_module.DEFAULT_SHELFMARK_LIMIT, "page": 2, "sort": "popularity"},
    ]
    assert first_section.total_pages == 9
    assert third_section.page == 2


def test_filtered_search_requestable_prefilter_keeps_current_page_candidate_for_progressive_refinement(shelfmark_module):
    shelfmark_module.clear_shelfmark_detail_cache()
    shelfmark_module.clear_shelfmark_scan_cache()
    fake_client = mock.Mock()
    fake_client.config = types.SimpleNamespace(base_url="https://shelfmark.example.com")
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(
            {
                "provider": "other",
                "provider_id": "111",
                "title": "No Exact ID",
                "authors": ["Author One"],
                "description": "<p>Thin result.</p>",
            },
            {
                "provider": "hardcover",
                "provider_id": "222",
                "title": "Request Ready",
                "authors": ["Author Two"],
                "identifiers": {"hardcover-id": "222"},
            },
        ),
        page=1,
        total_found=2,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = AssertionError(
        "first render should not fetch detail metadata for filtered rows"
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
            "request",
            detail_url_builder=lambda _: "/external/request",
            page=1,
        )

    assert fake_client.fetch_book.call_count == 0
    assert [result.title for result in section.results] == ["Request Ready", "No Exact ID"]
    assert section.results[0].needs_progressive_enrichment is True
    assert section.results[0].progressive_filter_pending is True
    assert section.results[1].progressive_filter_pending is True


def test_search_results_default_to_requestable_with_covers_on_the_current_page(shelfmark_module):
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
    fake_client.fetch_book.side_effect = AssertionError(
        "first render should not hydrate row details"
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
    assert [result.title for result in section.results] == ["Request Ready", "Missing Cover"]
    assert section.results[0].progressive_filter_pending is False
    assert section.results[1].progressive_filter_pending is True


def test_contextual_series_results_fill_from_later_source_pages_and_exclude_in_library(shelfmark_module):
    fake_client = mock.Mock()
    source_books = {
        "111": {
            "provider": "hardcover",
            "provider_id": "111",
            "title": "Already Owned",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/hardcover_111?url=owned",
            "series_name": "Discworld",
            "series_position": 1,
            "identifiers": {"hardcover-id": "111"},
        },
        "222": {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "The Amazing Maurice",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/hardcover_222?url=maurice",
            "series_name": "Discworld",
            "series_position": 28,
            "identifiers": {"hardcover-id": "222"},
        },
    }
    fake_client.search_books.side_effect = [
        shelfmark_module.ShelfmarkSearchResponse(
            books=(source_books["111"],),
            page=1,
            total_found=4,
            has_more=True,
        ),
        shelfmark_module.ShelfmarkSearchResponse(
            books=(source_books["222"],),
            page=2,
            total_found=4,
            has_more=False,
        ),
    ]
    fake_client.fetch_book.side_effect = lambda provider, provider_id: dict(source_books[provider_id])

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
        return_value={"111": shelfmark_module.ShelfmarkLibraryMatch("111", 7, "Already Owned")},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={
            "discworld": shelfmark_module.ShelfmarkOwnedSeries(
                key="discworld",
                series_name="Discworld",
                book_count=2,
                owned_positions=(1.0, 27.0),
                max_position=27.0,
                contiguous_position=27,
            )
        },
    ):
        section = shelfmark_module.search_shelfmark_contextual_results(
            "discworld",
            detail_url_builder=lambda _: "/external/discworld",
            context_type="series",
            context_value="Discworld",
            limit=1,
        )

    assert [result.title for result in section.results] == ["The Amazing Maurice"]
    assert fake_client.search_books.call_count == 2
    assert section.results[0].already_in_library is False
    assert section.results[0].series_context is not None
    assert section.results[0].series_context.matched is True


def test_contextual_series_results_prefer_matching_membership_over_broader_featured_series(shelfmark_module):
    fake_client = mock.Mock()
    source_book = {
        "provider": "hardcover",
        "provider_id": "777",
        "title": "The Lost Metal",
        "authors": ["Brandon Sanderson"],
        "cover_url": "/api/covers/hardcover_777?url=lost-metal",
        "book_series": [
            {
                "featured": True,
                "position": 10,
                "series": {"name": "Cosmere", "slug": "cosmere"},
            },
            {
                "featured": False,
                "position": 4,
                "series": {"name": "Mistborn Era 2", "slug": "mistborn-era-2"},
            },
        ],
        "identifiers": {"hardcover-id": "777"},
    }
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(source_book,),
        page=1,
        total_found=1,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: dict(source_book)

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
            "mistborn era 2": shelfmark_module.ShelfmarkOwnedSeries(
                key="mistborn era 2",
                series_name="Mistborn Era 2",
                book_count=3,
                owned_positions=(1.0, 2.0, 3.0),
                max_position=3.0,
                contiguous_position=3,
            ),
            "cosmere": shelfmark_module.ShelfmarkOwnedSeries(
                key="cosmere",
                series_name="Cosmere",
                book_count=9,
                owned_positions=(1.0, 2.0, 3.0, 4.0, 5.0),
                max_position=5.0,
                contiguous_position=5,
            ),
        },
    ):
        section = shelfmark_module.search_shelfmark_contextual_results(
            "Mistborn",
            detail_url_builder=lambda _: "/external/mistborn",
            context_type="series",
            context_value="Mistborn Era 2",
            limit=4,
        )

    assert [result.title for result in section.results] == ["The Lost Metal"]
    assert section.results[0].series_display == "Mistborn Era 2 (4)"
    assert section.results[0].secondary_series_note == "Also in Cosmere"
    assert section.results[0].best_series_context is not None
    assert section.results[0].best_series_context.series_name == "Mistborn Era 2"
    assert section.results[0].best_series_context.is_next_missing is True


def test_contextual_author_results_require_requestable_matching_author(shelfmark_module):
    fake_client = mock.Mock()
    source_books = {
        "222": {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "The Amazing Maurice",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/hardcover_222?url=maurice",
            "identifiers": {"hardcover-id": "222"},
        },
        "333": {
            "provider": "hardcover",
            "provider_id": "333",
            "title": "Shared Anthology",
            "authors": ["Someone Else"],
            "cover_url": "/api/covers/hardcover_333?url=anthology",
            "identifiers": {"hardcover-id": "333"},
        },
        "444": {
            "provider": "other",
            "provider_id": "444",
            "title": "No Hardcover Match",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/other_444?url=missing",
        },
    }
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=(source_books["222"], source_books["333"], source_books["444"]),
        page=1,
        total_found=3,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = lambda provider, provider_id: dict(source_books[provider_id])

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
        section = shelfmark_module.search_shelfmark_contextual_results(
            "Terry Pratchett",
            detail_url_builder=lambda _: "/external/pratchett",
            context_type="author",
            context_value="Pratchett, Terry",
            limit=8,
        )

    assert [result.title for result in section.results] == ["The Amazing Maurice"]


def test_contextual_results_report_unavailable_without_raising(shelfmark_module):
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
        section = shelfmark_module.search_shelfmark_contextual_results(
            "discworld",
            detail_url_builder=lambda _: "/external/discworld",
            context_type="series",
            context_value="Discworld",
            limit=4,
        )

    assert section.available is False
    assert section.message == "search failed"


def test_search_results_apply_requested_page_size_sort_and_shelfmark_totals(shelfmark_module):
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
        total_found=152,
        has_more=False,
    )
    fake_client.fetch_book.side_effect = AssertionError(
        "requested page should render before deep detail fetches"
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
    assert [result.title for result in section.results] == ["Request Ready", "No Cover"]
    assert section.total_pages == 4
    assert section.visible_start == 151
    assert section.visible_end == 152
    assert section.open_search_url == (
        "https://library.example.com/shelfmark/?content_type=ebook&sort=rating"
        "&limit=50&page=4&query=hell"
    )
    assert section.results[1].progressive_filter_pending is True


def test_search_results_exclude_explicit_audiobook_results(shelfmark_module):
    fake_client = mock.Mock()
    books = (
        {
            "provider": "hardcover",
            "provider_id": "111",
            "title": "Mort",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/hardcover_111?url=mort",
            "description": "<p>Discworld novel</p>",
            "rating": 4.1,
            "ratings_count": 1295,
            "users_count": 2298,
            "publish_year": 1987,
            "pages": 317,
            "identifiers": {"hardcover-id": "111"},
        },
        {
            "provider": "hardcover",
            "provider_id": "222",
            "title": "Mort Audiobook",
            "authors": ["Terry Pratchett"],
            "cover_url": "/api/covers/hardcover_222?url=mort-audio",
            "description": "<p>Audio edition</p>",
            "content_type": "audiobook",
            "identifiers": {"hardcover-id": "222"},
        },
    )
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=books,
        page=1,
        total_found=2,
        has_more=False,
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
        return_value={},
    ), mock.patch.object(
        shelfmark_module,
        "lookup_visible_owned_series",
        return_value={},
    ):
        section = shelfmark_module.search_shelfmark_results(
            "mort",
            detail_url_builder=lambda _: "/external/mort",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    assert [result.title for result in section.results] == ["Mort"]


def test_search_results_exclude_audio_only_results_but_keep_books_with_ebook_editions(shelfmark_module):
    fake_client = mock.Mock()
    books = (
        {
            "provider": "hardcover",
            "provider_id": "401",
            "title": "Audio Only",
            "authors": ["Author One"],
            "default_audio_edition": {
                "edition_format": "Audiobook",
                "reading_format": {"format": "Audio"},
            },
            "identifiers": {"hardcover-id": "401"},
        },
        {
            "provider": "hardcover",
            "provider_id": "402",
            "title": "Mixed Format",
            "authors": ["Author Two"],
            "default_audio_edition": {
                "edition_format": "Audiobook",
                "reading_format": {"format": "Audio"},
            },
            "default_ebook_edition": {
                "edition_format": "EPUB",
                "reading_format": {"format": "E-Book"},
                "pages": 320,
            },
            "identifiers": {"hardcover-id": "402"},
        },
    )
    fake_client.search_books.return_value = shelfmark_module.ShelfmarkSearchResponse(
        books=books,
        page=1,
        total_found=2,
        has_more=False,
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
            "format",
            detail_url_builder=lambda _: "/external/format",
            page=1,
            filter_requestable=False,
            filter_has_cover=False,
        )

    assert [result.title for result in section.results] == ["Mixed Format"]


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

    assert [result.title for result in owned_section.results] == [
        "Caliban's War",
        "Babylon's Ashes",
        "Generic Match",
    ]
    assert owned_section.selected_series_filter == "owned"
    assert owned_section.filters_active is True
    assert owned_section.results[-1].progressive_filter_pending is True
    assert [result.title for result in next_missing_section.results] == [
        "Caliban's War",
        "Babylon's Ashes",
        "Generic Match",
    ]
    assert next_missing_section.selected_series_filter == "next_missing"
    assert next_missing_section.results[1].progressive_filter_pending is True
    assert next_missing_section.results[-1].progressive_filter_pending is True


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

    assert [result.title for result in section.results] == [
        "Strong Candidate",
        "Weaker Requestable",
    ]
    assert section.selected_triage_filter == "strong"
    assert section.filters_active is True
    assert section.results[0].progressive_filter_pending is False
    assert section.results[1].progressive_filter_pending is True


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

    assert [result.title for result in section.results] == [
        "High Confidence",
        "Weak Metadata",
    ]
    assert section.filter_high_confidence is True
    assert section.filters_active is True
    assert section.results[0].progressive_filter_pending is False
    assert section.results[1].progressive_filter_pending is True


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
            reviews_count=None,
            readers_count=None,
            hardcover_id="1",
            already_in_library=True,
            library_book_id=1,
            library_book_title="Existing",
            library_book_url="/book/1",
            detail_url="/external/1",
            shelfmark_base_url="https://shelfmark.example.com",
            shelfmark_open_url=(
                "https://shelfmark.example.com/?content_type=ebook&sort=popularity"
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
            reviews_count=None,
            readers_count=None,
            hardcover_id="2",
            already_in_library=False,
            library_book_id=None,
            library_book_title=None,
            library_book_url=None,
            detail_url="/external/2",
            shelfmark_base_url="https://shelfmark.example.com",
            shelfmark_open_url=(
                "https://shelfmark.example.com/?content_type=ebook&sort=popularity"
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


def _make_request_result(
    shelfmark_module,
    provider_id,
    *,
    title=None,
    already_in_library=False,
    has_cover=True,
):
    if already_in_library:
        library_state = shelfmark_module.ShelfmarkLibraryState(
            key="already_in_library",
            label="In library",
            hint=None,
            row_class="success",
            badge_class="label-success",
            panel_class="panel-success",
            icon_class="glyphicon glyphicon-ok-circle",
        )
        action = shelfmark_module.ShelfmarkActionState(
            mode="view_library",
            label="Open existing CWA book",
            hint="",
            button_class="btn-success",
            icon_class="glyphicon glyphicon-book",
        )
        workflow_state = shelfmark_module.ShelfmarkWorkflowState(
            key="imported",
            label="In library",
            chip_class="shelfmark-status-chip--imported",
        )
    else:
        library_state = shelfmark_module.ShelfmarkLibraryState(
            key="external_candidate",
            label=None,
            hint=None,
            row_class="info",
            badge_class=None,
            panel_class="panel-info",
            icon_class="glyphicon glyphicon-cloud-download",
        )
        action = shelfmark_module.ShelfmarkActionState(
            mode="request",
            label="Request in Shelfmark",
            hint="",
            button_class="btn-primary",
            icon_class="glyphicon glyphicon-send",
        )
        workflow_state = shelfmark_module.ShelfmarkWorkflowState(
            key="available",
            label="Available to request",
            chip_class="shelfmark-status-chip--available",
        )

    return shelfmark_module.ShelfmarkResultView(
        provider="hardcover",
        provider_id=str(provider_id),
        title=title or f"Book {provider_id}",
        subtitle=None,
        authors=("Author",),
        cover_url=f"https://covers.example.com/{provider_id}.jpg" if has_cover else None,
        description="A requestable book",
        publish_year=2025,
        source_url=None,
        display_fields=(),
        rating=None,
        ratings_count=None,
        reviews_count=None,
        readers_count=None,
        hardcover_id=str(provider_id),
        already_in_library=already_in_library,
        library_book_id=7 if already_in_library else None,
        library_book_title="Existing" if already_in_library else None,
        library_book_url="/book/7" if already_in_library else None,
        detail_url=f"/request/detail/hardcover/{provider_id}",
        shelfmark_base_url="https://library.example.com/shelfmark",
        shelfmark_open_url=f"https://library.example.com/shelfmark?q={provider_id}",
        request_payload=None if already_in_library else {"book_data": {"provider_id": str(provider_id)}},
        library_state=library_state,
        action=action,
        workflow_state=workflow_state,
    )


def test_request_search_fills_visible_page_from_later_source_pages(shelfmark_module, monkeypatch):
    shelfmark_module.config.config_shelfmark_search = True
    shelfmark_module.config.config_shelfmark_url = "https://shelfmark.example.com"
    shelfmark_module.config.config_shelfmark_browser_url = "https://library.example.com/shelfmark"
    monkeypatch.setattr(shelfmark_module, "_normalize_page_size", lambda value: int(value))

    class DummyClient:
        def __init__(self, config_data):
            self.config = config_data

    monkeypatch.setattr(shelfmark_module, "ShelfmarkClient", DummyClient)

    page_calls = []

    responses = {
        1: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "1", "title": "Owned", "authors": ["Author"], "owned": True},
                {"provider": "hardcover", "provider_id": "2", "title": "No cover", "authors": ["Author"], "cover": False},
            ),
            page=1,
            total_found=4,
            has_more=True,
        ),
        2: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "3", "title": "Visible 1", "authors": ["Author"]},
                {"provider": "hardcover", "provider_id": "4", "title": "Visible 2", "authors": ["Author"]},
            ),
            page=2,
            total_found=4,
            has_more=False,
        ),
    }

    def fake_fetch_page(client, query, *, page, page_size, sort):
        page_calls.append(page)
        return responses[page]

    def fake_build_views(books, **kwargs):
        results = tuple(
            _make_request_result(
                shelfmark_module,
                book["provider_id"],
                title=book["title"],
                already_in_library=bool(book.get("owned")),
                has_cover=book.get("cover", True),
            )
            for book in books
        )
        return results, tuple(books)

    monkeypatch.setattr(shelfmark_module, "_fetch_shelfmark_search_page", fake_fetch_page)
    monkeypatch.setattr(shelfmark_module, "_build_search_result_views", fake_build_views)

    section = shelfmark_module.search_request_shelfmark_results(
        "dune",
        detail_url_builder=lambda book: f"/request/detail/{book['provider']}/{book['provider_id']}",
        page=1,
        page_size=2,
        sort="popularity",
        filter_requestable=True,
        filter_has_cover=True,
    )

    assert page_calls == [1, 2]
    assert [result.provider_id for result in section.results] == ["3", "4"]
    assert section.page_result_count == 2
    assert section.total_available == 2
    assert section.raw_total_available == 4
    assert section.filtered_owned == 1
    assert section.filtered_coverless == 1
    assert section.visible_start == 1
    assert section.visible_end == 2
    assert section.total_pages == 1


def test_request_search_paginates_over_filtered_visible_results(shelfmark_module, monkeypatch):
    shelfmark_module.config.config_shelfmark_search = True
    shelfmark_module.config.config_shelfmark_url = "https://shelfmark.example.com"
    shelfmark_module.config.config_shelfmark_browser_url = "https://library.example.com/shelfmark"
    monkeypatch.setattr(shelfmark_module, "_normalize_page_size", lambda value: int(value))

    class DummyClient:
        def __init__(self, config_data):
            self.config = config_data

    monkeypatch.setattr(shelfmark_module, "ShelfmarkClient", DummyClient)

    responses = {
        1: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "1", "title": "One", "authors": ["Author"]},
                {"provider": "hardcover", "provider_id": "2", "title": "Two", "authors": ["Author"]},
            ),
            page=1,
            total_found=5,
            has_more=True,
        ),
        2: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "3", "title": "Three", "authors": ["Author"]},
                {"provider": "hardcover", "provider_id": "4", "title": "Four", "authors": ["Author"]},
            ),
            page=2,
            total_found=5,
            has_more=True,
        ),
        3: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "5", "title": "Five", "authors": ["Author"]},
            ),
            page=3,
            total_found=5,
            has_more=False,
        ),
    }

    monkeypatch.setattr(
        shelfmark_module,
        "_fetch_shelfmark_search_page",
        lambda client, query, *, page, page_size, sort: responses[page],
    )
    monkeypatch.setattr(
        shelfmark_module,
        "_build_search_result_views",
        lambda books, **kwargs: (
            tuple(
                _make_request_result(
                    shelfmark_module,
                    book["provider_id"],
                    title=book["title"],
                    already_in_library=False,
                    has_cover=True,
                )
                for book in books
            ),
            tuple(books),
        ),
    )

    section = shelfmark_module.search_request_shelfmark_results(
        "dune",
        detail_url_builder=lambda book: f"/request/detail/{book['provider']}/{book['provider_id']}",
        page=2,
        page_size=2,
        sort="popularity",
        filter_requestable=True,
        filter_has_cover=True,
    )

    assert [result.provider_id for result in section.results] == ["3", "4"]
    assert section.total_available == 5
    assert section.raw_total_available == 5
    assert section.page == 2
    assert section.total_pages == 3
    assert section.visible_start == 3
    assert section.visible_end == 4
    assert section.has_previous is True
    assert section.previous_page == 1
    assert section.has_more is True
    assert section.next_page == 3


def test_request_search_suppresses_probable_non_book_entities(shelfmark_module, monkeypatch):
    shelfmark_module.config.config_shelfmark_search = True
    shelfmark_module.config.config_shelfmark_url = "https://shelfmark.example.com"
    shelfmark_module.config.config_shelfmark_browser_url = "https://library.example.com/shelfmark"
    monkeypatch.setattr(shelfmark_module, "_normalize_page_size", lambda value: int(value))

    class DummyClient:
        def __init__(self, config_data):
            self.config = config_data

    monkeypatch.setattr(shelfmark_module, "ShelfmarkClient", DummyClient)
    monkeypatch.setattr(
        shelfmark_module,
        "_fetch_shelfmark_search_page",
        lambda client, query, *, page, page_size, sort: shelfmark_module.ShelfmarkSearchResponse(
            books=(
                {"provider": "hardcover", "provider_id": "author-1", "title": "Brandon Sanderson", "authors": ["Brandon Sanderson"], "entity_type": "author"},
                {"provider": "hardcover", "provider_id": "book-1", "title": "The Way of Kings", "authors": ["Brandon Sanderson"]},
            ),
            page=1,
            total_found=2,
            has_more=False,
        ),
    )
    monkeypatch.setattr(
        shelfmark_module,
        "_build_search_result_views",
        lambda books, **kwargs: (
            tuple(
                _make_request_result(
                    shelfmark_module,
                    book["provider_id"],
                    title=book["title"],
                    already_in_library=False,
                    has_cover=True,
                )
                for book in books
            ),
            tuple(books),
        ),
    )

    section = shelfmark_module.search_request_shelfmark_results(
        "brandon sanderson",
        detail_url_builder=lambda book: f"/request/detail/{book['provider']}/{book['provider_id']}",
        page=1,
        page_size=12,
        sort="popularity",
        filter_requestable=True,
        filter_has_cover=True,
    )

    assert [result.provider_id for result in section.results] == ["book-1"]
    assert section.filtered_non_books == 1
    assert section.total_available == 1
    assert section.raw_total_available == 2


def test_request_search_tracks_extended_suppression_breakdown(shelfmark_module, monkeypatch):
    shelfmark_module.config.config_shelfmark_search = True
    shelfmark_module.config.config_shelfmark_url = "https://shelfmark.example.com"
    shelfmark_module.config.config_shelfmark_browser_url = "https://library.example.com/shelfmark"
    monkeypatch.setattr(shelfmark_module, "_normalize_page_size", lambda value: int(value))

    class DummyClient:
        def __init__(self, config_data):
            self.config = config_data

    monkeypatch.setattr(shelfmark_module, "ShelfmarkClient", DummyClient)

    raw_books = (
        {"provider": "hardcover", "provider_id": "good", "title": "Visible", "authors": ["Author"]},
        {"provider": "hardcover", "provider_id": "owned", "title": "Owned", "authors": ["Author"]},
        {"provider": "hardcover", "provider_id": "coverless", "title": "Coverless", "authors": ["Author"]},
        {
            "provider": "hardcover",
            "provider_id": "audio",
            "title": "Audio Original",
            "authors": ["Author"],
            "default_audio_edition_id": "audio-ed",
            "default_audio_edition": {
                "id": "audio-ed",
                "edition_format": "Audiobook",
                "reading_format": {"format": "audiobook"},
                "audio_seconds": 7200,
            },
        },
        {
            "provider": "hardcover",
            "provider_id": "foreign",
            "title": "Foreign",
            "authors": ["Author"],
            "language": {"code3": "spa"},
        },
        {"provider": "hardcover", "provider_id": "partial", "title": "Preview Sampler", "authors": ["Author"]},
        {"provider": "hardcover", "provider_id": "omnibus", "title": "Collected Stories Omnibus", "authors": ["Author"]},
        {
            "provider": "hardcover",
            "provider_id": "non-primary",
            "title": "Alternate Edition",
            "authors": ["Author"],
            "edition_id": "edition-2",
            "edition": {"id": "edition-2", "edition_format": "Ebook", "reading_format": {"format": "ebook"}},
            "default_ebook_edition_id": "edition-1",
            "default_ebook_edition": {"id": "edition-1", "edition_format": "Ebook", "reading_format": {"format": "ebook"}},
        },
        {"provider": "hardcover", "provider_id": "blocked", "title": "Blocked", "authors": ["Author"]},
        {"provider": "hardcover", "provider_id": "author-1", "title": "Brandon Sanderson", "authors": ["Brandon Sanderson"], "entity_type": "author"},
    )

    monkeypatch.setattr(
        shelfmark_module,
        "_fetch_shelfmark_search_page",
        lambda client, query, *, page, page_size, sort: shelfmark_module.ShelfmarkSearchResponse(
            books=raw_books,
            page=1,
            total_found=len(raw_books),
            has_more=False,
        ),
    )

    def fake_build_views(books, **kwargs):
        results = []
        for book in books:
            result = _make_request_result(
                shelfmark_module,
                book["provider_id"],
                title=book["title"],
                already_in_library=book["provider_id"] == "owned",
                has_cover=book["provider_id"] != "coverless",
            )
            if book["provider_id"] == "blocked":
                result = shelfmark_module.replace(
                    result,
                    hardcover_id=None,
                    request_payload=None,
                )
            results.append(result)
        return tuple(results), tuple(books)

    monkeypatch.setattr(shelfmark_module, "_build_search_result_views", fake_build_views)

    section = shelfmark_module.search_request_shelfmark_results(
        "painted man",
        detail_url_builder=lambda book: f"/request/detail/{book['provider']}/{book['provider_id']}",
        page=1,
        page_size=12,
        sort="popularity",
    )

    assert [result.provider_id for result in section.results] == ["good"]
    assert section.filtered_non_books == 1
    assert section.filtered_owned == 1
    assert section.filtered_coverless == 1
    assert section.filtered_audiobook_only == 1
    assert section.filtered_non_english == 1
    assert section.filtered_partial == 1
    assert section.filtered_compilations == 1
    assert section.filtered_non_primary == 1
    assert section.filtered_unrequestable == 1
    assert [item["key"] for item in section.suppression_counts] == [
        "non_book",
        "owned",
        "coverless",
        "audiobook_only",
        "partial",
        "compilation",
        "non_english",
        "unrequestable",
        "non_primary",
    ]


def test_request_suppression_counts_include_active_focus_filters(shelfmark_module):
    counts = {
        "next_missing_only": 3,
        "well_rated_only": 4,
        "popular_only": 5,
        "new_releases_only": 6,
        "standalone_only": 7,
        "first_in_series_only": 8,
    }
    filters = shelfmark_module.normalize_request_filter_state(
        next_missing_only=True,
        well_rated_only=True,
        popular_only=True,
        new_releases_only=True,
        standalone_only=True,
        first_in_series_only=True,
    )

    items = shelfmark_module._build_request_suppression_counts(counts, filters)

    assert [item["key"] for item in items] == [
        "next_missing_only",
        "well_rated_only",
        "popular_only",
        "new_releases_only",
        "standalone_only",
        "first_in_series_only",
    ]


def test_build_request_badges_include_owned_series_and_complete_metadata(shelfmark_module):
    result = shelfmark_module.build_shelfmark_result_view(
        {
            "provider": "hardcover",
            "provider_id": "900",
            "title": "Abaddon's Gate",
            "authors": ["James S. A. Corey"],
            "description": "<p>A fully enriched request result.</p>",
            "cover_url": "/api/covers/hardcover_900?url=x",
            "rating": 4.4,
            "ratings_count": 1200,
            "users_count": 8500,
            "pages": 528,
            "series_name": "The Expanse",
            "series_position": 1,
            "identifiers": {"hardcover-id": "900"},
        },
        library_match=None,
        detail_url="/request/detail/hardcover/900",
        shelfmark_browser_base_url="https://library.example.com/shelfmark",
    )
    contexts = shelfmark_module.build_shelfmark_series_membership_contexts(
        (result,),
        {
            "the expanse": shelfmark_module.ShelfmarkOwnedSeries(
                key="the expanse",
                series_name="The Expanse",
                book_count=2,
                owned_positions=(1.0, 3.0),
                max_position=3.0,
                contiguous_position=1,
            )
        },
    )[0]
    result = shelfmark_module.apply_primary_series_context(
        shelfmark_module.replace(result, series_contexts=contexts),
    )
    quality_state = shelfmark_module.build_shelfmark_quality_state(result)
    result = shelfmark_module.replace(result, quality_state=quality_state)

    badges = shelfmark_module._build_request_badges(result)
    labels = [badge["label"] for badge in badges]

    assert "Owned series" in labels
    assert "Next missing" not in labels
    assert "Well rated" in labels
    assert "Popular" in labels
    assert "Complete metadata" in labels
    assert "Continue series" not in labels
