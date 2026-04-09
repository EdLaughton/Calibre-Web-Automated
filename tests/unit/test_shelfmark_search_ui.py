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
                        "<body>{% block body %}{% endblock %}{% block js %}{% endblock %}</body></html>"
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
        "publish_year": 2024,
        "source_url": "https://source.example.com/999",
        "display_fields": [],
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
            "hint": "Exact Hardcover ID already exists in your library.",
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
        "publish_year": 2025,
        "source_url": "https://source.example.com/222",
        "display_fields": [],
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
            "hint": "This browser already has a Shelfmark session and the current policy allows book-level requests.",
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
        "publish_year": None,
        "source_url": None,
        "display_fields": [],
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
            "hint": "This result has no exact Hardcover ID, so CWA cannot prepare a direct Shelfmark request.",
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
            "has_more": True,
            "total_available": 895,
            "open_search_url": "https://library.example.com/shelfmark/?content_type=ebook&sort=relevance&page=1&query=Dune",
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
    assert "Shelfmark External Results" in html
    assert html.index("Library Results") < html.index("Shelfmark External Results")
    assert 'class="shelfmark-external-shell"' in html
    assert "1 book" in html
    assert "Showing 3 of 895" in html
    assert "CWA is previewing the first Shelfmark page here." in html
    assert "See more in Shelfmark" in html
    assert 'href="https://library.example.com/shelfmark/?content_type=ebook&amp;sort=relevance&amp;page=1&amp;query=Dune"' in html
    assert "shelfmark-section-pill" not in html
    assert "Already in Your Library" in html
    assert "External Candidates" in html
    assert "External Results Without Exact Hardcover ID" in html
    assert "Open existing CWA book" in html
    assert 'href="/book/7"' in html
    assert "Duplicate state unavailable" not in html
    assert "No exact hardcover-id match was found in metadata.db." not in html
    assert "Exact hardcover-id match in metadata.db." not in html
    assert "Duplicate checking is unavailable for these results because Shelfmark did not return an exact Hardcover ID." in html
    assert 'class="btn btn-sm btn-primary shelfmark-result-card__primary-action js-shelfmark-action"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "js-shelfmark-action-icon" in html
    assert "js-shelfmark-action-label" in html
    assert "shelfmark-result-card__secondary-action" in html
    assert "No cover" in html
    candidate_chunk = html[html.index("External Candidate"):html.index("No Hardcover ID")]
    duplicate_chunk = html[html.index("Already Present"):html.index("External Candidate")]
    assert candidate_chunk.count("Open in Shelfmark") == 0
    assert duplicate_chunk.count("Open in Shelfmark") == 1


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
    assert "Already in your library via an exact Hardcover ID match." in html
    assert "Existing CWA book" in html
    assert 'href="/book/7"' in html
    assert "Open existing CWA book" in html
    assert 'class="discover shelfmark-search-page shelfmark-detail-page"' in html
    assert 'class="shelfmark-detail-page__shell"' in html
    assert 'class="shelfmark-detail-layout"' in html
    assert 'class="shelfmark-detail-cover-card"' in html
    assert 'class="shelfmark-detail-card shelfmark-detail-card--hero shelfmark-detail-card--success"' in html
    assert html.count("Open in Shelfmark") == 1
    assert 'target="_blank"' in html


def test_search_template_renders_intentional_zero_results_state():
    app = _create_app()
    context = _base_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "has_more": False,
        "total_available": 0,
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

    assert "Shelfmark External Results" in html
    assert "No Shelfmark external results found" in html
    assert "Shelfmark search completed for this query but did not return any external matches." in html
    assert "No matches" in html
    assert "External lookup query" in html
    assert "<code>Dune</code>" in html
    assert "Open this search in Shelfmark" in html
