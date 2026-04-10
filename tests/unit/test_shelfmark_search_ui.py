# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import sys

from flask import Blueprint, Flask, g, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "cps" / "templates"


def _ensure_real_flask_package():
    flask_module = sys.modules.get("flask")
    if flask_module is not None and hasattr(flask_module, "__path__"):
        return

    sys.modules.pop("flask", None)
    importlib.import_module("flask")
    importlib.import_module("flask.testing")


@dataclass
class DummyAuthor:
    id: int
    name: str


@dataclass
class DummySeries:
    id: int
    name: str


@dataclass
class DummyRating:
    rating: int


@dataclass
class DummyBook:
    id: int
    title: str
    has_cover: bool = False
    authors: list[DummyAuthor] = field(default_factory=list)
    series: list[DummySeries] = field(default_factory=list)
    series_index: float = 1.0
    ratings: list[DummyRating] = field(default_factory=list)
    data: list[object] = field(default_factory=list)


class DummyEntry:
    def __init__(self, book: DummyBook, read: bool = False):
        self.Books = book
        self._values = [book, None, read]

    def __getitem__(self, index):
        return self._values[index]


class DummyShelfCollection:
    @staticmethod
    def all():
        return []


class DummyCurrentUser:
    is_authenticated = True
    shelf = DummyShelfCollection()

    @staticmethod
    def role_edit_shelfs():
        return False


def _create_app():
    _ensure_real_flask_package()
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.jinja_loader = ChoiceLoader(
        [
            DictLoader(
                {
                    "layout.html": (
                        "<!doctype html><html><head>{% block header %}{% endblock %}</head>"
                        "<body>{% block body %}{% endblock %}{% block modal %}{% endblock %}{% block js %}{% endblock %}</body></html>"
                    ),
                    "image.html": (
                        "{% macro book_cover(book) %}"
                        "<img alt=\"{{ book.title }}\" src=\"/static/test-cover.png\">"
                        "{% endmacro %}"
                    ),
                }
            ),
            FileSystemLoader(str(TEMPLATES_DIR)),
        ]
    )

    app.jinja_env.globals["csrf_token"] = lambda: "csrf-token"
    app.jinja_env.globals["_"] = lambda value, **kwargs: value % kwargs if kwargs else value
    app.jinja_env.filters["shortentitle"] = lambda value, *args, **kwargs: value
    app.jinja_env.filters["formatfloat"] = lambda value, *args, **kwargs: f"{value:.2f}"
    app.jinja_env.filters["music"] = lambda value: False

    web = Blueprint("web", __name__)

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @web.route("/list")
    def books_list():
        return "books"

    app.register_blueprint(web)
    return app


def _base_context():
    local_book = DummyBook(
        id=11,
        title="Local Library Book",
        has_cover=True,
        authors=[DummyAuthor(id=1, name="Frank Herbert")],
        series=[DummySeries(id=1, name="Dune")],
        series_index=1.0,
        ratings=[DummyRating(rating=8)],
    )
    local_entry = DummyEntry(local_book, read=True)

    duplicate_result = {
        "provider": "hardcover",
        "provider_id": "999",
        "title": "Already Present",
        "subtitle": "Library duplicate",
        "authors": ["Author One"],
        "cover_url": "https://covers.example.com/999.jpg",
        "description": "A duplicate already present in the library.",
        "description_html": "<p>A duplicate already present in the library.</p>",
        "publish_year": 2024,
        "source_url": "https://source.example.com/999",
        "display_fields": [],
        "series_display": "Dune (1)",
        "facts": ["2024", "Dune (1)"],
        "hardcover_id": "999",
        "already_in_library": True,
        "library_book_id": 7,
        "library_book_title": "Existing Title",
        "library_book_url": "/book/7",
        "detail_url": "/search/external/shelfmark/hardcover/999?query=dune",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance"
            "&query=Already+Present+Author+One&title=Already+Present&author=Author+One"
        ),
        "request_payload": {
            "book_data": {"provider_id": "999", "title": "Already Present"},
            "context": {"source": "*", "content_type": "ebook", "request_level": "book"},
        },
        "library_state": {
            "key": "already_in_library",
            "label": "In library",
            "hint": None,
            "row_class": "success",
            "badge_class": "label-success",
            "panel_class": "panel-success",
            "icon_class": "glyphicon glyphicon-ok-circle",
        },
        "action": {
            "mode": "view_library",
            "label": "Open existing CWA book",
            "hint": None,
            "button_class": "btn-success",
            "icon_class": "glyphicon glyphicon-book",
        },
    }
    candidate_result = {
        "provider": "hardcover",
        "provider_id": "222",
        "title": "External Candidate",
        "subtitle": "Can be requested",
        "authors": ["Author Two"],
        "cover_url": None,
        "description": "A result that can be requested in Shelfmark.",
        "description_html": "<p>A result that can be requested in <i>Shelfmark</i>.</p>",
        "publish_year": 2025,
        "source_url": "https://source.example.com/222",
        "display_fields": [
            {"label": "Rating", "value": "4.3 (5,900)", "icon": "star"},
            {"label": "Readers", "value": "9,893", "icon": "users"},
        ],
        "series_display": "The Lord of the Rings (2)",
        "facts": ["4.3 ★", "5,900 ratings", "9,893 readers", "2025", "The Lord of the Rings (2)"],
        "hardcover_id": "222",
        "already_in_library": False,
        "library_book_id": None,
        "library_book_title": None,
        "library_book_url": None,
        "detail_url": "/search/external/shelfmark/hardcover/222?query=dune",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance"
            "&query=External+Candidate+Author+Two&title=External+Candidate&author=Author+Two"
        ),
        "request_payload": {
            "book_data": {"provider_id": "222", "title": "External Candidate"},
            "context": {"source": "*", "content_type": "ebook", "request_level": "book"},
        },
        "library_state": {
            "key": "external_candidate",
            "label": None,
            "hint": None,
            "row_class": "info",
            "badge_class": None,
            "panel_class": "panel-info",
            "icon_class": "glyphicon glyphicon-cloud-download",
        },
        "action": {
            "mode": "request",
            "label": "Request in Shelfmark",
            "hint": None,
            "button_class": "btn-primary",
            "icon_class": "glyphicon glyphicon-send",
        },
    }
    unavailable_result = {
        "provider": "other",
        "provider_id": "333",
        "title": "No Hardcover ID",
        "subtitle": None,
        "authors": ["Author Three"],
        "cover_url": None,
        "description": "Duplicate status cannot be determined.",
        "description_html": "<p>Duplicate status cannot be determined.</p>",
        "publish_year": None,
        "source_url": None,
        "display_fields": [],
        "series_display": None,
        "facts": [],
        "hardcover_id": None,
        "already_in_library": False,
        "library_book_id": None,
        "library_book_title": None,
        "library_book_url": None,
        "detail_url": "/search/external/shelfmark/other/333?query=dune",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance"
            "&query=No+Hardcover+ID+Author+Three&title=No+Hardcover+ID&author=Author+Three"
        ),
        "request_payload": None,
        "library_state": {
            "key": "library_match_unavailable",
            "label": "No Hardcover ID",
            "hint": "Duplicate check is unavailable because Shelfmark did not return an exact Hardcover ID.",
            "row_class": "warning",
            "badge_class": "label-warning",
            "panel_class": "panel-warning",
            "icon_class": "glyphicon glyphicon-question-sign",
        },
        "action": {
            "mode": "open",
            "label": "Open in Shelfmark",
            "hint": "Direct request needs an exact Hardcover ID.",
            "button_class": "btn-default",
            "icon_class": "glyphicon glyphicon-new-window",
        },
    }

    return {
        "entries": [local_entry],
        "adv_searchterm": "Dune",
        "searchterm": "Dune",
        "query": "Dune",
        "result_count": 1,
        "pagination": None,
        "page": "search",
        "order": "abc",
        "simple": True,
        "current_user": DummyCurrentUser(),
        "shelfmark_section": {
            "enabled": True,
            "available": True,
            "query": "Dune",
            "page": 1,
            "page_size": 12,
            "selected_sort": "relevance",
            "sort_options": [
                {"value": "relevance", "label": "Most relevant"},
                {"value": "popularity", "label": "Most popular"},
                {"value": "rating", "label": "Highest rated"},
            ],
            "page_size_options": [12, 24, 50, 100],
            "total_pages": 75,
            "visible_start": 1,
            "visible_end": 3,
            "has_previous": False,
            "previous_page": None,
            "next_page": 2,
            "has_more": True,
            "total_available": 895,
            "page_result_count": 3,
            "filter_requestable": False,
            "filter_has_cover": False,
            "filters_active": False,
            "open_search_url": "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&limit=12&page=1&query=Dune",
            "previous_page_url": None,
            "next_page_url": "/search/stored/?query=Dune&shelfmark_page=2",
            "clear_filters_url": "/search/stored/?query=Dune&shelfmark_page=1",
            "requestable_toggle_url": "/search/stored/?query=Dune&shelfmark_page=1&shelfmark_filter_requestable=1",
            "requestable_toggle_label": "Focus on requestable",
            "query_label": "External lookup query",
            "context_hint": "Duplicate awareness remains exact hardcover-id matching only.",
            "message": None,
            "message_level": "info",
            "summary": {
                "total_results": 3,
                "total_available": 895,
                "has_more": True,
                "already_in_library": 1,
                "external_candidates": 1,
                "library_match_unavailable": 1,
            },
            "results": [duplicate_result, candidate_result, unavailable_result],
            "groups": [
                {
                    "key": "already_in_library",
                    "title": "Already in Your Library",
                    "hint": "These external hits already exist in metadata.db via an exact hardcover-id match.",
                    "panel_class": "panel-success",
                    "badge_class": "label-success",
                    "icon_class": "glyphicon glyphicon-ok-circle",
                    "count": 1,
                    "results": [duplicate_result],
                },
                {
                    "key": "external_candidate",
                    "title": "External Candidates",
                    "hint": "These results have an exact hardcover-id, but no matching library record yet.",
                    "panel_class": "panel-info",
                    "badge_class": "label-info",
                    "icon_class": "glyphicon glyphicon-cloud-download",
                    "count": 1,
                    "results": [candidate_result],
                },
                {
                    "key": "library_match_unavailable",
                    "title": "External Results Without Exact Hardcover ID",
                    "hint": "Duplicate checking is unavailable for these results because Shelfmark did not return an exact Hardcover ID.",
                    "panel_class": "panel-warning",
                    "badge_class": "label-warning",
                    "icon_class": "glyphicon glyphicon-question-sign",
                    "count": 1,
                    "results": [unavailable_result],
                },
            ],
        },
    }


def test_search_template_renders_local_and_external_sections_with_duplicate_states():
    app = _create_app()
    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **_base_context())

    assert "Library Results" in html
    assert "These are books already present in your Calibre library." in html
    assert "Shelfmark Results" in html
    assert "Additional matches from Shelfmark." in html
    assert html.index("Library Results") < html.index("Shelfmark Results")
    assert 'class="shelfmark-external-shell"' in html
    assert 'class="shelfmark-section-line shelfmark-section-line--local"' in html
    assert 'class="shelfmark-section-line shelfmark-section-line--external"' in html
    assert "1 book" in html
    assert "3 returned on this page" in html
    assert "Showing 1-3 of 895" in html
    assert "Page 1 of 75" in html
    assert "Jump to page" in html
    assert 'name="shelfmark_page_size"' in html
    assert 'name="shelfmark_sort"' in html
    assert "Request-capable" not in html
    assert "Has cover" in html
    assert "Focus on requestable" in html
    assert 'href="/search/stored/?query=Dune&amp;shelfmark_page=2"' in html
    assert "CWA is previewing the first Shelfmark page here." not in html
    assert "Checking your browser for direct Shelfmark request availability." not in html
    assert 'class="shelfmark-status-banner js-shelfmark-request-status is-hidden"' in html
    assert html.index("Open search in Shelfmark") < html.index("External Candidate")
    assert 'href="https://library.example.com/shelfmark/?content_type=ebook&amp;sort=relevance&amp;limit=12&amp;page=1&amp;query=Dune"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmark-section-pill" not in html
    assert "External Candidates" not in html
    assert "Already in Your Library" not in html
    assert "External Results Without Exact Hardcover ID" not in html
    assert "Duplicate awareness remains exact hardcover-id matching only." not in html
    assert "duplicate awareness stays exact" not in html
    assert "shelfmark-group-panel" not in html
    assert 'class="shelfmark-results-list"' in html
    assert "Open existing CWA book" in html
    assert 'href="/book/7"' in html
    assert "Existing CWA book" not in html
    assert "Duplicate state unavailable" not in html
    assert "No exact hardcover-id match was found in metadata.db." not in html
    assert "Exact hardcover-id match in metadata.db." not in html
    assert "Duplicate checking is unavailable for these results because Shelfmark did not return an exact Hardcover ID." not in html
    assert "Direct request needs an exact Hardcover ID." in html
    assert 'class="btn btn-sm btn-primary shelfmark-result-card__primary-action js-shelfmark-action"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "js-shelfmark-action-icon" in html
    assert "js-shelfmark-action-label" in html
    assert "shelfmark-result-card__secondary-action" in html
    assert "js-shelfmark-detail-link" in html
    assert 'data-detail-title="External Candidate"' in html
    assert 'id="shelfmarkDetailModal"' in html
    assert 'id="shelfmarkDetailModalLabel"' in html
    assert 'class="modal fade shelfmark-detail-modal"' in html
    assert "4.3 ★" in html
    assert "The Lord of the Rings (2)" in html
    assert "No cover" in html
    candidate_chunk = html[html.index("External Candidate"):html.index("No Hardcover ID")]
    duplicate_chunk = html[html.index("Already Present"):html.index("External Candidate")]
    assert candidate_chunk.count("Open in Shelfmark") == 0
    assert duplicate_chunk.count("Open in Shelfmark") == 0


def test_search_template_renders_external_cover_image_when_available():
    app = _create_app()
    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **_base_context())

    assert 'src="https://covers.example.com/999.jpg"' in html
    assert 'loading="lazy"' in html
    assert 'class="shelfmark-result-card__cover-image"' in html


def test_search_template_omits_group_wrapper_chrome_for_external_results():
    app = _create_app()
    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **_base_context())

    assert "External Candidates" not in html
    assert "Already in Your Library" not in html
    assert "External Results Without Exact Hardcover ID" not in html
    assert "panel-heading shelfmark-group-panel__heading" not in html
    assert html.count('role="listitem"') == 3


def test_detail_template_renders_existing_book_jump_and_action_markup():
    app = _create_app()
    context = _base_context()
    result = context["shelfmark_section"]["results"][0]

    with app.test_request_context("/search/external/shelfmark/hardcover/999?query=Dune"):
        html = render_template(
            "shelfmark_external_detail.html",
            title=result["title"],
            result=result,
            search_query="Dune",
            return_to="/search?query=Dune",
            shelfmark_error=None,
        )

    assert "Back to search results" in html
    assert 'href="/search?query=Dune"' in html
    assert "Shelfmark External Result" not in html
    assert "Detailed external metadata, cover, and request actions from Shelfmark." not in html
    assert "Duplicate awareness remains metadata.db + exact Hardcover ID only." not in html
    assert "Already in library" not in html
    assert "Existing CWA book" not in html
    assert 'href="/book/7"' in html
    assert 'class="discover shelfmark-search-page shelfmark-detail-page"' in html
    assert 'class="shelfmark-detail-page__shell"' in html
    assert 'class="shelfmark-detail-layout"' in html
    assert 'class="shelfmark-detail-cover-card"' in html
    assert 'class="shelfmark-detail-hero shelfmark-detail-hero--success"' in html
    assert 'class="shelfmark-status-banner js-shelfmark-request-status is-hidden"' in html
    assert "Open in Shelfmark" not in html
    assert "Open source page" not in html
    assert "Book details" in html
    assert 'class="btn btn-default btn-sm shelfmark-detail-page__back-action"' in html
    assert 'href="https://source.example.com/999"' in html


def test_detail_partial_renders_modal_ready_content_without_back_link():
    app = _create_app()
    context = _base_context()
    result = context["shelfmark_section"]["results"][1]

    with app.test_request_context("/search/external/shelfmark/hardcover/222?query=Dune&view=modal"):
        html = render_template(
            "shelfmark_external_detail_content.html",
            result=result,
            modal_mode=True,
            shelfmark_error=None,
        )

    assert 'class="shelfmark-detail-pane shelfmark-detail-pane--modal"' in html
    assert 'data-detail-title="External Candidate"' in html
    assert "Back to search results" not in html
    assert "Request in Shelfmark" in html
    assert "<i>Shelfmark</i>" in html


def test_detail_template_hides_request_ready_browser_copy_for_requestable_result():
    app = _create_app()
    context = _base_context()
    result = context["shelfmark_section"]["results"][1]

    with app.test_request_context("/search/external/shelfmark/hardcover/222?query=Dune"):
        html = render_template(
            "shelfmark_external_detail.html",
            title=result["title"],
            result=result,
            search_query="Dune",
            return_to="/search?query=Dune",
            shelfmark_error=None,
        )

    assert "This browser already has a valid Shelfmark session and the current Shelfmark policy allows a direct book-level request for this result." not in html
    assert "Duplicate awareness remains metadata.db + exact Hardcover ID only." not in html
    assert "Shelfmark External Result" not in html
    assert "Not in your library" not in html
    assert "No exact Hardcover ID match found in metadata.db." not in html
    assert "4.3 ★" in html
    assert "The Lord of the Rings (2)" in html


def test_detail_template_renders_sanitized_description_html():
    app = _create_app()
    context = _base_context()
    result = context["shelfmark_section"]["results"][1]

    with app.test_request_context("/search/external/shelfmark/hardcover/222?query=Dune"):
        html = render_template(
            "shelfmark_external_detail.html",
            title=result["title"],
            result=result,
            search_query="Dune",
            return_to="/search?query=Dune",
            shelfmark_error=None,
        )

    assert "<i>Shelfmark</i>" in html
    assert "&lt;i&gt;" not in html


def test_search_template_renders_intentional_zero_results_state():
    app = _create_app()
    context = _base_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "has_more": False,
        "total_available": 0,
        "page_result_count": 0,
        "summary": {
            "total_results": 0,
            "total_available": 0,
            "has_more": False,
            "already_in_library": 0,
            "external_candidates": 0,
            "library_match_unavailable": 0,
        },
        "results": [],
        "groups": [],
    }

    with app.test_request_context("/search?query=Black+House"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert "Shelfmark Results" in html
    assert "No Shelfmark external results found" in html
    assert "Shelfmark search completed for this query but did not return any external matches." in html
    assert "No matches" in html
    assert "External lookup query" in html
    assert "<code>Dune</code>" in html
    assert "Open search in Shelfmark" in html


def test_search_template_renders_filter_toolbar_and_page_jump_state():
    app = _create_app()
    context = _base_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "page": 2,
        "page_size": 24,
        "selected_sort": "rating",
        "filter_requestable": True,
        "filter_has_cover": True,
        "filters_active": False,
        "page_result_count": 12,
        "results": context["shelfmark_section"]["results"][:1],
        "clear_filters_url": "/search/stored/?query=Dune&shelfmark_page=1",
        "requestable_toggle_url": "/search/stored/?query=Dune&shelfmark_page=1&shelfmark_filter_requestable=0",
        "requestable_toggle_label": "Show all matches",
    }

    with app.test_request_context(
        "/search/stored/?query=Dune&shelfmark_page=2&shelfmark_page_size=24&shelfmark_sort=rating&shelfmark_filter_requestable=1&shelfmark_filter_has_cover=1"
    ):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert 'value="rating" selected' in html
    assert 'value="24" selected' in html
    assert html.count('checked') == 1
    assert "Show all matches" in html
    assert "Clear filters" not in html
    assert "Jump to page" in html
