# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "services" / "requests_workspace.py"


def _gettext(value, **kwargs):
    return value % kwargs if kwargs else value


@dataclass(frozen=True)
class _FakeSeriesContext:
    matched: bool = True
    is_next_missing: bool = False
    is_continuation: bool = False
    series_position: float | None = None


@dataclass(frozen=True)
class _FakeLibraryState:
    row_class: str = "info"


@dataclass(frozen=True)
class _FakeAction:
    mode: str = "request"
    label: str = "Request in Shelfmark"
    hint: str | None = None
    button_class: str = "btn-primary"
    icon_class: str = "glyphicon glyphicon-send"


@dataclass(frozen=True)
class _FakeWorkflowState:
    key: str = "available"
    label: str = "Available"
    chip_class: str = "shelfmark-status-chip--available"


@dataclass(frozen=True)
class _FakeResultView:
    provider: str = "hardcover"
    provider_id: str = "1"
    title: str = "Book"
    subtitle: str | None = None
    authors: tuple[str, ...] = ("Author",)
    cover_url: str | None = "https://covers.example.com/1.jpg"
    description: str | None = "Description"
    publish_year: int | None = 2000
    source_url: str | None = None
    display_fields: tuple[dict, ...] = ()
    rating: float | None = 4.2
    ratings_count: int | None = 500
    reviews_count: int | None = 20
    readers_count: int | None = 1000
    hardcover_id: str | None = "1"
    already_in_library: bool = False
    library_book_id: int | None = None
    library_book_title: str | None = None
    library_book_url: str | None = None
    detail_url: str | None = "/search/external/shelfmark/hardcover/1?query=Book"
    shelfmark_base_url: str = "https://library.example.com/shelfmark"
    shelfmark_open_url: str = "https://library.example.com/shelfmark/?query=Book"
    request_payload: dict | None = None
    library_state: _FakeLibraryState = _FakeLibraryState()
    action: _FakeAction = _FakeAction()
    pages: int | None = None
    editions_count: int | None = None
    lists_count: int | None = None
    description_html: str | None = None
    series_memberships: tuple = ()
    series_contexts: tuple = ()
    best_series_context: _FakeSeriesContext | None = None
    secondary_series_note: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    series_count: int | None = None
    series_display: str | None = None
    series_url: str | None = None
    series_entries: tuple = ()
    facts: tuple[str, ...] = ()
    detail_stats: tuple = ()
    genres: tuple = ()
    moods: tuple = ()
    content_warnings: tuple = ()
    series_context: _FakeSeriesContext | None = None
    workflow_state: _FakeWorkflowState | None = _FakeWorkflowState()
    quality_state: object | None = None
    triage_state: object | None = None
    needs_progressive_enrichment: bool = False
    progressive_filter_pending: bool = False

    def to_template_dict(self):
        return {
            "provider": self.provider,
            "provider_id": self.provider_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "authors": list(self.authors),
            "cover_url": self.cover_url,
            "description": self.description,
            "publish_year": self.publish_year,
            "source_url": self.source_url,
            "display_fields": list(self.display_fields),
            "rating": self.rating,
            "ratings_count": self.ratings_count,
            "reviews_count": self.reviews_count,
            "readers_count": self.readers_count,
            "hardcover_id": self.hardcover_id,
            "already_in_library": self.already_in_library,
            "library_book_id": self.library_book_id,
            "library_book_title": self.library_book_title,
            "library_book_url": self.library_book_url,
            "detail_url": self.detail_url,
            "shelfmark_base_url": self.shelfmark_base_url,
            "shelfmark_open_url": self.shelfmark_open_url,
            "request_payload": self.request_payload,
            "library_state": {"row_class": self.library_state.row_class},
            "action": {
                "mode": self.action.mode,
                "label": self.action.label,
                "hint": self.action.hint,
                "button_class": self.action.button_class,
                "icon_class": self.action.icon_class,
            },
            "workflow_state": (
                {
                    "key": self.workflow_state.key,
                    "label": self.workflow_state.label,
                    "chip_class": self.workflow_state.chip_class,
                }
                if self.workflow_state
                else None
            ),
        }


@pytest.fixture
def requests_module(monkeypatch):
    logger_instance = types.SimpleNamespace(warning=lambda *args, **kwargs: None)

    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []
    cps_module.calibre_db = types.SimpleNamespace(session=types.SimpleNamespace(query=lambda *args, **kwargs: None))
    cps_module.db = types.SimpleNamespace(
        Authors=types.SimpleNamespace(id=None, name=None, sort=None),
        Books=types.SimpleNamespace(id=None, series_index=None),
        Series=types.SimpleNamespace(id=None, name=None),
        books_authors_link=types.SimpleNamespace(c=types.SimpleNamespace(book=None, author=None)),
        books_series_link=types.SimpleNamespace(c=types.SimpleNamespace(book=None, series=None)),
    )
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)

    services_module = types.ModuleType("cps.services")
    services_module.__path__ = []

    hardcover_module = types.ModuleType("cps.services.hardcover")
    hardcover_module.get_hardcover_client = lambda load_privacy=False: None

    class _FakeContextualSection:
        def __init__(self, results):
            self.available = True
            self.results = tuple(results)

    shelfmark_module = types.ModuleType("cps.services.shelfmark_search")
    shelfmark_module.ShelfmarkLibraryMatch = object
    shelfmark_module.ShelfmarkResultView = _FakeResultView
    shelfmark_module.ShelfmarkSearchSection = _FakeContextualSection
    shelfmark_module.apply_primary_series_context = lambda result, preferred_series_name=None: result
    shelfmark_module.build_owned_series_map = lambda rows: {}
    shelfmark_module.build_shelfmark_quality_state = lambda result: None
    shelfmark_module.build_shelfmark_result_view = lambda *args, **kwargs: _FakeResultView()
    shelfmark_module.build_shelfmark_series_membership_contexts = lambda *args, **kwargs: (tuple(),)
    shelfmark_module.build_shelfmark_triage_state = lambda *args, **kwargs: None
    shelfmark_module.get_shelfmark_client_config = lambda: types.SimpleNamespace(enabled=True, browser_base_url="https://library.example.com/shelfmark")
    shelfmark_module.lookup_visible_library_matches = lambda ids: {}
    shelfmark_module.lookup_visible_owned_series = lambda names: {}
    shelfmark_module.search_shelfmark_contextual_results = lambda *args, **kwargs: _FakeContextualSection(tuple())

    flask_module = types.ModuleType("flask")
    flask_module.url_for = lambda endpoint, **kwargs: "/" + endpoint.replace(".", "/") + (
        "?" + "&".join(f"{key}={value}" for key, value in sorted(kwargs.items()))
        if kwargs
        else ""
    )

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.gettext = _gettext

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_sql_module = types.ModuleType("sqlalchemy.sql")
    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.func = types.SimpleNamespace(count=lambda value: value)
    sqlalchemy_expression_module.text = lambda value: value

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.services", services_module)
    monkeypatch.setitem(sys.modules, "cps.services.hardcover", hardcover_module)
    monkeypatch.setitem(sys.modules, "cps.services.shelfmark_search", shelfmark_module)
    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql", sqlalchemy_sql_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql.expression", sqlalchemy_expression_module)

    spec = importlib.util.spec_from_file_location("cps.services.requests_workspace_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.services.requests_workspace_test", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_result(module, *, hardcover_id="1", title="Book", series_position=3, next_missing=False, continuation=False, readers=1000, in_library=False, cover_url="https://covers.example.com/1.jpg"):
    context = _FakeSeriesContext(
        matched=True,
        is_next_missing=next_missing,
        is_continuation=continuation,
        series_position=series_position,
    )
    return _FakeResultView(
        provider_id=hardcover_id,
        title=title,
        hardcover_id=hardcover_id,
        readers_count=readers,
        already_in_library=in_library,
        cover_url=cover_url,
        series_position=series_position,
        best_series_context=context,
        series_context=context,
        request_payload={"book_data": {"provider": "hardcover", "provider_id": hardcover_id}},
    )


def test_build_series_candidate_marks_gap_fill(requests_module):
    seed = requests_module.RequestsOwnedSeriesSeed(
        key="discworld",
        name="Discworld",
        book_count=4,
        owned_positions=(1.0, 2.0, 4.0, 5.0),
        max_position=5.0,
        contiguous_position=2,
    )

    candidate = requests_module._build_series_candidate(
        seed,
        _make_result(requests_module, hardcover_id="3", series_position=3, next_missing=True),
        section_key="series",
    )

    assert candidate is not None
    assert candidate.reason_label == "Missing volume"
    assert candidate.reason_detail == "Missing between volumes 2 and 4"
    assert candidate.priority_bucket == "critical"


def test_build_series_candidate_marks_next_in_series_without_gap(requests_module):
    seed = requests_module.RequestsOwnedSeriesSeed(
        key="expanse",
        name="The Expanse",
        book_count=3,
        owned_positions=(1.0, 2.0, 3.0),
        max_position=3.0,
        contiguous_position=3,
    )

    candidate = requests_module._build_series_candidate(
        seed,
        _make_result(requests_module, hardcover_id="4", series_position=4, next_missing=True),
        section_key="series",
    )

    assert candidate is not None
    assert candidate.reason_label == "Next in series"
    assert candidate.reason_detail == "Next after volume 3 in a series you own"
    assert candidate.priority_bucket == "high"


def test_build_author_candidate_explains_existing_author_ownership(requests_module):
    seed = requests_module.RequestsOwnedAuthorSeed(author_id=9, name="Terry Pratchett", book_count=4)

    candidate = requests_module._build_author_candidate(
        seed,
        _make_result(requests_module, hardcover_id="9", title="Nation", readers=2500),
    )

    assert candidate is not None
    assert candidate.reason_label == "Popular missing title"
    assert candidate.reason_detail == "You already own 4 books by this author"
    assert candidate.group_title == "Terry Pratchett"


def test_build_discover_candidate_skips_owned_and_coverless_results(requests_module):
    assert requests_module._build_discover_candidate(
        _make_result(requests_module, hardcover_id="10", in_library=True),
        trending=True,
    ) is None
    assert requests_module._build_discover_candidate(
        _make_result(requests_module, hardcover_id="11", cover_url=None),
        trending=True,
    ) is None


def test_dedupe_candidates_keeps_highest_priority_first(requests_module):
    result = _make_result(requests_module, hardcover_id="12", title="Equal Rites")
    low = requests_module.RequestsCandidate(
        key="a",
        result=result,
        reason_label="Later",
        sort_key=(2, 0),
    )
    high = requests_module.RequestsCandidate(
        key="b",
        result=result,
        reason_label="Sooner",
        sort_key=(0, 0),
    )

    deduped = requests_module._dedupe_candidates((low, high))

    assert [candidate.reason_label for candidate in deduped] == ["Sooner"]


def test_build_requests_workspace_series_uses_expected_sections(requests_module, monkeypatch):
    monkeypatch.setattr(
        requests_module,
        "_build_section_shells",
        lambda active_view, state_url=None: (
            requests_module.RequestsSectionShell(
                key="series-next",
                title="Next in series",
                subtitle="Next in series subtitle",
                empty_message="none",
                load_url="/requests/sections/series/series-next",
                loading_message="Loading recommendations…",
                layout="grouped",
                compact=True,
            ),
            requests_module.RequestsSectionShell(
                key="series-missing",
                title="Missing volumes",
                subtitle="Missing volumes subtitle",
                empty_message="none",
                load_url="/requests/sections/series/series-missing",
                loading_message="Loading recommendations…",
                layout="grouped",
                compact=True,
            ),
        ),
    )

    workspace = requests_module.build_requests_workspace("series", state_url="/requests/series").to_template_dict()

    assert workspace["active_view"] == "series"
    assert [section["title"] for section in workspace["sections"]] == [
        "Next in series",
        "Missing volumes",
    ]
    assert [section["load_url"] for section in workspace["sections"]] == [
        "/requests/sections/series/series-next",
        "/requests/sections/series/series-missing",
    ]

def test_requests_view_normalization_defaults_to_series(requests_module):
    assert requests_module.normalize_requests_view(None) == "series"
    assert requests_module.normalize_requests_view("home") == "series"
    assert requests_module.normalize_requests_view("discover") == "hot"


def test_build_requests_section_new_uses_new_cache(requests_module, monkeypatch):
    new_section = requests_module.RequestsSection(
        key="new",
        title="New and notable",
        subtitle="Recent releases worth adding next.",
        empty_message="none",
        layout="cards",
        candidates=(
            requests_module.RequestsCandidate(
                key="new:12",
                result=_make_result(requests_module, hardcover_id="12", title="A Stroke of the Pen"),
                reason_label="New and notable",
                sort_key=(0, 0),
            ),
        ),
    )

    monkeypatch.setattr(
        requests_module,
        "_cached_new_section",
        lambda state_url=None, cache_scope=None, limit=None: new_section,
    )

    section = requests_module.build_requests_section("new", "new", state_url="/requests/new", cache_scope=1)

    assert section.key == "new"
    assert [candidate.result.title for candidate in section.candidates] == ["A Stroke of the Pen"]
