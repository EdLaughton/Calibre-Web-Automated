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
    is_anonymous = False
    name = "Tester"
    locale = "en"
    shelf = DummyShelfCollection()

    @staticmethod
    def role_edit_shelfs():
        return False

    @staticmethod
    def role_upload():
        return False

    @staticmethod
    def role_admin():
        return False

    @staticmethod
    def role_edit():
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
    app.jinja_env.filters["get_cover_srcset"] = lambda value: ""

    web = Blueprint("web", __name__)
    search = Blueprint("search", __name__)

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @web.route("/list")
    def books_list():
        return "books"

    @search.route("/request")
    def request_page():
        return "request"

    @search.route("/request/detail/<provider>/<provider_id>")
    def request_detail(provider, provider_id):
        return f"detail:{provider}:{provider_id}"

    @search.route("/advsearch")
    def advanced_search():
        return "advsearch"

    @search.route("/search")
    def simple_search():
        return "search"

    app.register_blueprint(web)
    app.register_blueprint(search)
    return app


def _create_real_layout_app():
    _ensure_real_flask_package()
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.jinja_loader = ChoiceLoader(
        [
            DictLoader(
                {
                    "request_layout_smoke.html": (
                        "{% extends 'layout.html' %}"
                        "{% block body %}<div class='request-layout-smoke'>ok</div>{% endblock %}"
                    ),
                    "image.html": (
                        "{% macro book_cover(book) %}"
                        "<img alt=\"{{ book.title if book and book.title is defined else 'cover' }}\" src=\"/static/test-cover.png\">"
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
    app.jinja_env.filters["get_cover_srcset"] = lambda value: ""

    web = Blueprint("web", __name__)
    search = Blueprint("search", __name__)

    @web.route("/")
    def index():
        return "index"

    @web.route("/profile")
    def profile():
        return "profile"

    @web.route("/logout")
    def logout():
        return "logout"

    @web.route("/login")
    def login():
        return "login"

    @web.route("/list")
    def books_list():
        return "books"

    @search.route("/search")
    def simple_search():
        return "search"

    @search.route("/advsearch")
    def advanced_search():
        return "advsearch"

    @search.route("/request")
    def request_page():
        return "request"

    app.register_blueprint(web)
    app.register_blueprint(search)
    return app


def _base_context():
    saved_state_url = (
        "/search/stored/?query=Dune&shelfmark_page=2&shelfmark_page_size=24"
        "&shelfmark_sort=rating&shelfmark_filter_requestable=1"
        "&shelfmark_filter_has_cover=1"
    )
    saved_state_return = (
        "%2Fsearch%2Fstored%2F%3Fquery%3DDune%26shelfmark_page%3D2%26shelfmark_page_size%3D24"
        "%26shelfmark_sort%3Drating%26shelfmark_filter_requestable%3D1"
        "%26shelfmark_filter_has_cover%3D1"
    )

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
        "subtitle": None,
        "authors": ["Author One"],
        "cover_url": "https://covers.example.com/999.jpg",
        "description": "A duplicate already present in the library.",
        "description_html": "<p>A duplicate already present in the library.</p>",
        "publish_year": 2024,
        "source_url": "https://source.example.com/999",
        "display_fields": [],
        "rating": None,
        "ratings_count": None,
        "reviews_count": None,
        "readers_count": None,
        "series_display": "Dune (1)",
        "series_url": "https://hardcover.app/series/dune",
        "series_entries": [
            {
                "name": "Dune",
                "position": 1.0,
                "featured": True,
                "display": "Dune (1)",
                "url": "https://hardcover.app/series/dune",
            }
        ],
        "facts": ["2024", "Dune (1)"],
        "detail_stats": [],
        "genres": ["Science Fiction"],
        "moods": [],
        "content_warnings": [],
        "pages": None,
        "editions_count": None,
        "lists_count": None,
        "series_count": None,
        "series_context": None,
        "workflow_state": {
            "key": "imported",
            "label": "In library",
            "chip_class": "shelfmark-status-chip--imported",
        },
        "quality_state": None,
        "triage_state": None,
        "hardcover_id": "999",
        "already_in_library": True,
        "library_book_id": 7,
        "library_book_title": "Existing Title",
        "library_book_url": "/book/7",
        "detail_url": f"/search/external/shelfmark/hardcover/999?query=dune&return_to={saved_state_return}",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity"
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
        "subtitle": None,
        "authors": ["Author Two"],
        "cover_url": None,
        "description": "A result that can be requested in Shelfmark.",
        "description_html": "<p>A result that can be requested in <i>Shelfmark</i>.</p>",
        "publish_year": 2025,
        "source_url": "https://source.example.com/222",
        "display_fields": [
            {"label": "Rating", "value": "4.3 (5,900)", "icon": "star"},
            {"label": "Readers", "value": "9,893", "icon": "users"},
            {"label": "Pages", "value": "304", "icon": "book"},
            {"label": "Editions", "value": "42", "icon": "duplicate"},
            {"label": "Lists", "value": "128", "icon": "list"},
            {"label": "Moods", "value": "Whimsical, Adventurous", "icon": "spark"},
            {"label": "Content warnings", "value": "Violence, Death", "icon": "warning"},
        ],
        "rating": 4.3,
        "ratings_count": 5900,
        "reviews_count": 74,
        "readers_count": 9893,
        "series_display": "The Lord of the Rings (2)",
        "series_url": "https://hardcover.app/series/the-lord-of-the-rings",
        "series_entries": [
            {
                "name": "The Lord of the Rings",
                "position": 2.0,
                "featured": True,
                "display": "The Lord of the Rings (2)",
                "url": "https://hardcover.app/series/the-lord-of-the-rings",
            },
            {
                "name": "Middle-earth",
                "position": 5.0,
                "featured": False,
                "display": "Middle-earth (5)",
                "url": "https://hardcover.app/series/middle-earth",
            },
        ],
        "series_memberships": [
            {
                "key": "the lord of the rings",
                "name": "The Lord of the Rings",
                "position": 2.0,
                "featured": True,
                "display": "The Lord of the Rings (2)",
                "url": "https://hardcover.app/series/the-lord-of-the-rings",
            },
            {
                "key": "middle-earth",
                "name": "Middle-earth",
                "position": 5.0,
                "featured": False,
                "display": "Middle-earth (5)",
                "url": "https://hardcover.app/series/middle-earth",
            },
        ],
        "facts": ["4.3 ★", "5,900 ratings", "9,893 readers", "2025", "304 pages", "The Lord of the Rings (2)"],
        "detail_stats": [
            {"label": "Reviews", "value": "74"},
            {"label": "Editions", "value": "42"},
            {"label": "Lists", "value": "128"},
        ],
        "genres": ["Fantasy", "Adventure", "Epic Fantasy"],
        "moods": ["Whimsical", "Adventurous"],
        "content_warnings": ["Violence", "Death"],
        "pages": 304,
        "editions_count": 42,
        "lists_count": 128,
        "series_count": 3,
        "series_context": {
            "membership": {
                "key": "the lord of the rings",
                "name": "The Lord of the Rings",
                "position": 2.0,
                "featured": True,
                "display": "The Lord of the Rings (2)",
                "url": "https://hardcover.app/series/the-lord-of-the-rings",
            },
            "series_name": "The Lord of the Rings",
            "series_position": 2.0,
            "series_display": "The Lord of the Rings (2)",
            "series_url": "https://hardcover.app/series/the-lord-of-the-rings",
            "featured": True,
            "matched": True,
            "owned_series_name": "The Lord of the Rings",
            "owned_book_count": 1,
            "owned_max_position": 1.0,
            "owned_contiguous_position": 1,
            "is_continuation": True,
            "is_next_missing": True,
            "badges": [{"label": "Next missing", "badge_class": "label-primary"}],
            "facts": ["1 book owned in this series", "Owned through 1"],
            "detail_value": "Next missing · 1 book owned in this series · Owned through 1",
        },
        "series_contexts": [
            {
                "membership": {
                    "key": "the lord of the rings",
                    "name": "The Lord of the Rings",
                    "position": 2.0,
                    "featured": True,
                    "display": "The Lord of the Rings (2)",
                    "url": "https://hardcover.app/series/the-lord-of-the-rings",
                },
                "series_name": "The Lord of the Rings",
                "series_position": 2.0,
                "series_display": "The Lord of the Rings (2)",
                "series_url": "https://hardcover.app/series/the-lord-of-the-rings",
                "featured": True,
                "matched": True,
                "owned_series_name": "The Lord of the Rings",
                "owned_book_count": 1,
                "owned_max_position": 1.0,
                "owned_contiguous_position": 1,
                "is_continuation": True,
                "is_next_missing": True,
                "badges": [{"label": "Next missing", "badge_class": "label-primary"}],
                "facts": ["1 book owned in this series", "Owned through 1"],
                "detail_value": "Next missing · 1 book owned in this series · Owned through 1",
            }
        ],
        "best_series_context": {
            "membership": {
                "key": "the lord of the rings",
                "name": "The Lord of the Rings",
                "position": 2.0,
                "featured": True,
                "display": "The Lord of the Rings (2)",
                "url": "https://hardcover.app/series/the-lord-of-the-rings",
            },
            "series_name": "The Lord of the Rings",
            "series_position": 2.0,
            "series_display": "The Lord of the Rings (2)",
            "series_url": "https://hardcover.app/series/the-lord-of-the-rings",
            "featured": True,
            "matched": True,
            "owned_series_name": "The Lord of the Rings",
            "owned_book_count": 1,
            "owned_max_position": 1.0,
            "owned_contiguous_position": 1,
            "is_continuation": True,
            "is_next_missing": True,
            "badges": [{"label": "Next missing", "badge_class": "label-primary"}],
            "facts": ["1 book owned in this series", "Owned through 1"],
            "detail_value": "Next missing · 1 book owned in this series · Owned through 1",
        },
        "secondary_series_note": "Also in Middle-earth",
        "workflow_state": {
            "key": "available",
            "label": "Available to request",
            "chip_class": "shelfmark-status-chip--available",
        },
        "quality_state": {
            "high_confidence": True,
            "metadata_complete": True,
            "popularity_signal": True,
            "rating_signal": True,
            "bibliographic_signal": True,
            "facts": ["Well rated", "Popular", "Complete metadata"],
            "detail_value": "High confidence · Well rated · Popular · Complete metadata",
        },
        "triage_state": {
            "strong_candidate": True,
            "metadata_rich": True,
            "popularity_signal": True,
            "facts": ["Popular", "Rich metadata"],
            "detail_value": "Strong candidate · Popular · Rich metadata",
        },
        "hardcover_id": "222",
        "already_in_library": False,
        "library_book_id": None,
        "library_book_title": None,
        "library_book_url": None,
        "detail_url": f"/search/external/shelfmark/hardcover/222?query=dune&return_to={saved_state_return}",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity"
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
        "rating": None,
        "ratings_count": None,
        "reviews_count": None,
        "readers_count": None,
        "series_display": None,
        "series_url": None,
        "series_entries": [],
        "facts": [],
        "detail_stats": [],
        "genres": [],
        "moods": [],
        "content_warnings": [],
        "pages": None,
        "editions_count": None,
        "lists_count": None,
        "series_count": None,
        "series_context": None,
        "workflow_state": None,
        "quality_state": None,
        "triage_state": None,
        "hardcover_id": None,
        "already_in_library": False,
        "library_book_id": None,
        "library_book_title": None,
        "library_book_url": None,
        "detail_url": f"/search/external/shelfmark/other/333?query=dune&return_to={saved_state_return}",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": (
            "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity"
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

    duplicate_result.update(
        {
            "needs_progressive_enrichment": False,
            "progressive_filter_pending": False,
            "row_index": 0,
            "row_class_name": "shelfmark-result-card js-shelfmark-result-row shelfmark-result-card--success",
            "row_status_provider": "",
            "row_status_provider_id": "",
            "row_status_in_library": "1",
            "row_enrichment_url": None,
        }
    )
    candidate_result.update(
        {
            "needs_progressive_enrichment": True,
            "progressive_filter_pending": True,
            "row_index": 1,
            "row_class_name": (
                "shelfmark-result-card js-shelfmark-result-row shelfmark-result-card--info "
                "js-shelfmark-status-target js-shelfmark-batch-row "
                "js-shelfmark-progressive-row shelfmark-result-card--refining"
            ),
            "row_status_provider": "hardcover",
            "row_status_provider_id": "222",
            "row_status_in_library": "0",
            "row_enrichment_url": (
                "/search/external/shelfmark/hardcover/222/row?query=Dune"
                "&shelfmark_page=2&shelfmark_page_size=24&shelfmark_sort=rating"
                "&shelfmark_filter_requestable=1&shelfmark_filter_has_cover=1"
                "&return_to=%2Fsearch%2Fstored%2F%3Fquery%3DDune"
                "%26shelfmark_page%3D2%26shelfmark_page_size%3D24%26shelfmark_sort%3Drating"
                "%26shelfmark_filter_requestable%3D1%26shelfmark_filter_has_cover%3D1"
            ),
        }
    )
    unavailable_result.update(
        {
            "needs_progressive_enrichment": False,
            "progressive_filter_pending": False,
            "row_index": 2,
            "row_class_name": "shelfmark-result-card js-shelfmark-result-row shelfmark-result-card--warning",
            "row_status_provider": "",
            "row_status_provider_id": "",
            "row_status_in_library": "0",
            "row_enrichment_url": None,
        }
    )

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
            "selected_sort": "popularity",
            "selected_series_filter": "all",
            "selected_triage_filter": "all",
            "sort_options": [
                {"value": "popularity", "label": "Most popular"},
                {"value": "relevance", "label": "Most relevant"},
                {"value": "rating", "label": "Highest rated"},
            ],
            "series_filter_options": [
                {"value": "all", "label": "All matches"},
                {"value": "owned", "label": "Owned series"},
                {"value": "next_missing", "label": "Next missing"},
            ],
            "triage_filter_options": [
                {"value": "all", "label": "All shown"},
                {"value": "strong", "label": "Strong candidates"},
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
            "raw_total_available": 895,
            "page_result_count": 3,
            "filter_requestable": False,
            "filter_high_confidence": False,
            "filter_has_cover": True,
            "filters_active": False,
            "open_search_url": "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity&limit=12&page=1&query=Dune",
            "previous_page_url": None,
            "next_page_url": "/search/stored/?query=Dune&shelfmark_page=2",
            "clear_filters_url": "/search/stored/?query=Dune&shelfmark_page=1",
            "requestable_toggle_url": "/search/stored/?query=Dune&shelfmark_page=1&shelfmark_filter_requestable=1",
            "requestable_toggle_label": "Focus on requestable",
            "top_up_url": (
                "/search/external/shelfmark/topup?query=Dune&shelfmark_page=1&shelfmark_page_size=12"
                "&shelfmark_sort=popularity&return_to=%2Fsearch%2Fstored%2F%3Fquery%3DDune"
            ),
            "state_url": saved_state_url,
            "query_label": "External lookup query",
            "context_hint": "Duplicate awareness remains exact hardcover-id matching only.",
            "message": None,
            "message_level": "info",
            "pagination_mode": "shelfmark",
            "progressive_refinement": True,
            "progressive_refinement_note": (
                "Shelfmark totals are shown as-is. Visible rows refine as details load."
            ),
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


def _request_page_context():
    context = _base_context()
    requestable = dict(context["shelfmark_section"]["results"][1])
    requestable["detail_url"] = (
        "/request/detail/hardcover/222?query=Dune&page=2&sort=popularity&requestable=1&has_cover=1"
        "&return_to=%2Frequest%3Fquery%3DDune%26page%3D2%26sort%3Dpopularity%26requestable%3D1%26has_cover%3D1"
    )
    requestable["row_enrichment_url"] = None
    requestable["needs_progressive_enrichment"] = False
    requestable["progressive_filter_pending"] = False
    requestable["row_class_name"] = (
        "shelfmark-result-card js-shelfmark-result-row shelfmark-result-card--info "
        "js-shelfmark-status-target js-shelfmark-batch-row"
    )

    unavailable = dict(context["shelfmark_section"]["results"][2])
    unavailable["detail_url"] = (
        "/request/detail/other/333?query=Dune&page=2&sort=popularity&requestable=1&has_cover=1"
        "&return_to=%2Frequest%3Fquery%3DDune%26page%3D2%26sort%3Dpopularity%26requestable%3D1%26has_cover%3D1"
    )
    unavailable["row_enrichment_url"] = None

    return {
        "page": "request",
        "request_query": "Dune",
        "current_user": DummyCurrentUser(),
        "preferred_release": {
            "enabled": False,
            "provider": "",
            "content_type": "ebook",
            "ranking": "seeders_desc",
        },
        "shelfmark_section": {
            "enabled": True,
            "available": True,
            "query": "Dune",
            "page": 2,
            "page_size": 12,
            "selected_sort": "popularity",
            "sort_options": [
                {"value": "popularity", "label": "Most popular"},
                {"value": "relevance", "label": "Most relevant"},
                {"value": "rating", "label": "Highest rated"},
            ],
            "page_size_options": [12, 24, 50, 100],
            "total_pages": 5,
            "visible_start": 13,
            "visible_end": 24,
            "has_previous": True,
            "previous_page": 1,
            "next_page": 3,
            "has_more": True,
            "total_available": 58,
            "raw_total_available": 224,
            "page_result_count": 2,
            "filtered_non_books": 4,
            "filtered_owned": 19,
            "filtered_coverless": 11,
            "filter_requestable": True,
            "filter_has_cover": True,
            "filter_high_confidence": False,
            "filters_active": False,
            "open_search_url": "https://library.example.com/shelfmark/?content_type=ebook&sort=popularity&limit=12&page=1&query=Dune",
            "previous_page_url": "/request?query=Dune&page=1&sort=popularity&requestable=1&has_cover=1",
            "next_page_url": "/request?query=Dune&page=3&sort=popularity&requestable=1&has_cover=1",
            "clear_filters_url": "/request?query=Dune",
            "state_url": "/request?query=Dune&page=2&sort=popularity&requestable=1&has_cover=1",
            "preferred_release_settings": {
                "enabled": False,
                "provider": "",
                "content_type": "ebook",
                "ranking": "seeders_desc",
            },
            "results": [requestable, unavailable],
            "groups": [],
            "summary": {
                "total_results": 2,
                "total_available": 58,
                "raw_total_available": 224,
                "has_more": True,
                "already_in_library": 0,
                "external_candidates": 1,
                "library_match_unavailable": 1,
            },
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
    assert "3 shown" in html
    assert "895 total" in html
    assert "3 shown on this page" in html
    assert "895 total on Shelfmark" in html
    assert 'data-total-available="895"' in html
    assert 'data-filter-has-cover="1"' in html
    assert "Page 1" in html
    assert "Page 1 of 75" not in html
    assert "11 visible here" not in html
    assert 'id="shelfmark_page_size"' not in html
    assert 'id="shelfmark_page_size_footer"' in html
    assert html.index('id="shelfmark_page_size_footer"') > html.index('class="shelfmark-pagination-footer js-shelfmark-pagination-footer"')
    assert 'name="shelfmark_sort"' in html
    assert 'name="shelfmark_series_filter"' not in html
    assert 'id="shelfmark_series_filter_owned"' not in html
    assert "Owned series" not in html
    assert html.count('shelfmark-external-controls__checkbox-group') == 1
    assert "Next missing" not in html
    assert "Strong candidates" not in html
    assert "Candidates" not in html
    assert "High confidence" not in html
    assert "0 selected" in html
    assert "0 ready on this page" in html
    assert "Request selected" in html
    assert "Select visible" in html
    assert "js-shelfmark-batch-toolbar" in html
    assert "Bulk mode" in html
    assert "Request-capable" not in html
    assert "Has cover" in html
    assert 'name="shelfmark_filter_has_cover" value="1" checked' in html
    assert "Reset" in html
    assert "Focus on requestable" not in html
    assert 'href="/search/stored/?query=Dune&amp;shelfmark_page=2"' in html
    assert "CWA is previewing the first Shelfmark page here." not in html
    assert "Checking your browser for direct Shelfmark request availability." not in html
    assert 'class="shelfmark-status-banner js-shelfmark-request-status is-hidden"' in html
    assert 'data-top-up-url="/search/external/shelfmark/topup?query=Dune&amp;shelfmark_page=1&amp;shelfmark_page_size=12&amp;shelfmark_sort=popularity&amp;return_to=%2Fsearch%2Fstored%2F%3Fquery%3DDune"' in html
    assert 'data-page-size="12"' in html
    assert 'data-display-page="1"' in html
    assert html.index("Open in Shelfmark") < html.index("External Candidate")
    assert 'href="https://library.example.com/shelfmark/?content_type=ebook&amp;sort=popularity&amp;limit=12&amp;page=1&amp;query=Dune"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmark-section-pill" not in html
    assert "External Candidates" not in html
    assert "Already in Your Library" not in html
    assert "External Results Without Exact Hardcover ID" not in html
    assert "Duplicate awareness remains exact hardcover-id matching only." not in html
    assert "duplicate awareness stays exact" not in html
    assert "shelfmark-group-panel" not in html
    assert 'class="shelfmark-results-list js-shelfmark-results-list"' in html
    assert "Shelfmark totals are shown as-is. Visible rows refine as details load." not in html
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
    assert "Also in Middle-earth" in html
    assert "Middle-earth (5)" not in html
    assert html.count("js-shelfmark-batch-row") == 1
    assert html.count("js-shelfmark-batch-toggle") == 1
    assert 'aria-label="Select External Candidate for batch request"' in html
    assert "shelfmark-result-card__secondary-action" in html
    assert "js-shelfmark-detail-link" in html
    assert 'data-detail-title="External Candidate"' in html
    assert 'data-detail-provider="hardcover"' in html
    assert 'data-detail-provider-id="222"' in html
    assert 'data-row-enrich-url="/search/external/shelfmark/hardcover/222/row?query=Dune' in html
    assert 'return_to=%2Fsearch%2Fstored%2F%3Fquery%3DDune%26shelfmark_page%3D2' in html
    assert "No usable Shelfmark results remained" not in html
    assert "Reset filters" not in html
    assert ">Go<" not in html
    assert "shelfmark-pagination-footer__jump" not in html
    assert 'id="shelfmarkDetailModal"' in html
    assert 'id="shelfmarkDetailModalLabel"' in html
    assert 'class="modal fade shelfmark-detail-modal"' in html
    assert 'data-search-state-url="/search/stored/?query=Dune&amp;shelfmark_page=2&amp;shelfmark_page_size=24&amp;shelfmark_sort=rating&amp;shelfmark_filter_requestable=1&amp;shelfmark_filter_has_cover=1"' in html
    assert "4.3 ★" in html
    assert "The Lord of the Rings (2)" in html
    assert "304 pages" in html
    assert "1 book owned in this series" not in html
    assert "Owned through 1" not in html
    assert "Strong candidate" not in html
    assert "Well rated" not in html
    assert "Popular" not in html
    assert "Complete metadata" not in html
    assert "Next likely book in your library run" not in html
    assert "Can be requested" not in html
    assert "Library duplicate" not in html
    assert "No cover" in html
    candidate_chunk = html[html.index("External Candidate"):html.index("No Hardcover ID")]
    duplicate_chunk = html[html.index("Already Present"):html.index("External Candidate")]
    assert candidate_chunk.count("Open in Shelfmark") == 0
    assert duplicate_chunk.count("Open in Shelfmark") == 0
    assert 'shelfmark-status-chip shelfmark-status-chip--available js-shelfmark-status-chip is-hidden' in candidate_chunk


def test_search_template_renders_external_cover_image_when_available():
    app = _create_app()
    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **_base_context())

    assert 'src="https://covers.example.com/999.jpg"' in html
    assert 'loading="lazy"' in html
    assert 'class="shelfmark-result-card__cover-image"' in html


def test_search_template_keeps_shelfmark_shell_when_current_page_is_empty_but_later_pages_exist():
    app = _create_app()
    context = _base_context()
    context["entries"] = []
    context["result_count"] = 0
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "results": [],
        "page_result_count": 0,
        "total_available": 895,
        "raw_total_available": 895,
        "has_more": True,
        "next_page": 2,
        "summary": {
            **context["shelfmark_section"]["summary"],
            "total_results": 0,
            "external_candidates": 0,
        },
    }

    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert "No Results Found" not in html
    assert "No Shelfmark external results found" not in html
    assert 'class="shelfmark-results-list js-shelfmark-results-list"' in html
    assert 'class="shelfmark-pagination-footer js-shelfmark-pagination-footer"' in html
    assert 'data-next-page="2"' in html
    assert "895 total on Shelfmark" in html
    assert "No usable Shelfmark results remained" not in html
    assert "Reset filters" not in html
    assert 'id="shelfmarkDetailModal"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html


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


def test_search_template_uses_compact_count_wording_for_filtered_page_results():
    app = _create_app()
    context = _base_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "page_result_count": 25,
        "results": context["shelfmark_section"]["results"][:1],
        "summary": {
            **context["shelfmark_section"]["summary"],
            "total_results": 1,
        },
    }

    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert "1 shown on this page" in html
    assert "25 returned on this page" not in html
    assert "1 visible here" not in html
    assert "Showing 1-25 of" not in html


def test_search_template_limits_batch_selection_to_request_candidates():
    app = _create_app()
    with app.test_request_context("/search?query=Dune"):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **_base_context())

    assert html.count("js-shelfmark-batch-toggle") == 1
    assert 'aria-label="Select Already Present for batch request"' not in html
    assert 'aria-label="Select External Candidate for batch request"' in html
    assert 'aria-label="Select No Hardcover ID for batch request"' not in html


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
    assert "In library" in html
    assert html.count("Hardcover ID") == 1
    assert 'class="shelfmark-detail-status"' in html
    assert 'class="btn btn-default btn-sm shelfmark-detail-page__back-action"' in html
    assert 'href="https://source.example.com/999"' in html
    assert "Dune (1)" in html
    assert "Genres" in html
    assert "Science Fiction" in html


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

    assert 'class="shelfmark-detail-pane shelfmark-detail-pane--modal js-shelfmark-status-target"' in html
    assert 'data-detail-title="External Candidate"' in html
    assert "Back to search results" not in html
    assert "External Candidate" in html
    assert "— Author Two" in html
    assert "Request in Shelfmark" in html
    assert "Available to request" in html
    assert "5,900 ratings" in html
    assert "9,893 readers" in html
    assert "<i>Shelfmark</i>" in html
    assert "Strong candidate" not in html
    assert "Next missing" in html
    assert "1 book owned in this series" in html
    assert "Owned through 1" in html
    assert "Library series context" in html
    assert "Well rated" in html
    assert "Popular" in html
    assert "Reviews" in html
    assert "74" in html
    assert "Rating</dt>" not in html
    assert "Ratings</dt>" not in html
    assert "Readers</dt>" not in html
    assert 'href="https://hardcover.app/series/the-lord-of-the-rings"' in html
    assert "The Lord of the Rings (2)" in html
    assert "Middle-earth (5)" in html
    assert 'class="shelfmark-detail-token-list shelfmark-detail-token-list--genres"' in html
    assert "Whimsical" in html
    assert "Lists" in html
    assert "128 lists" in html
    assert "Content notes" in html
    assert "Violence" in html
    assert "Genres" in html
    assert "Fantasy" in html
    assert "Adventurous" in html


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
    assert "5,900 ratings" in html
    assert "9,893 readers" in html
    assert "The Lord of the Rings (2)" in html
    assert "Middle-earth (5)" in html
    assert "Strong candidate" not in html
    assert "Next missing" in html
    assert "Library series" in html
    assert "Available to request" in html
    assert html.count("Hardcover ID") == 1
    assert 'class="shelfmark-detail-status is-hidden"' in html
    assert "Next likely book in your library run" not in html
    assert "1 book owned in this series" in html
    assert "Owned through 1" in html
    assert "Well rated" in html
    assert "Popular" in html
    assert "Complete metadata" in html
    assert "Ratings</dt>" not in html
    assert "Readers</dt>" not in html
    assert 'href="https://hardcover.app/series/the-lord-of-the-rings"' in html
    assert "Genres" in html
    assert "Fantasy" in html
    assert "304" in html
    assert "42" in html
    assert "128 lists" in html
    assert "Whimsical" in html
    assert "Content notes" in html
    assert "Violence" in html
    assert "Death" in html


def test_detail_template_renders_inline_page_title_and_author():
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

    assert '<span class="shelfmark-detail-page__titletext">External Candidate</span>' in html
    assert '<span class="shelfmark-detail-page__authorinline">— Author Two</span>' in html


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
        "next_page": None,
        "total_pages": 0,
        "top_up_url": None,
        "has_more": False,
        "total_available": 0,
        "raw_total_available": 0,
        "page_result_count": 0,
        "summary": {
            "total_results": 0,
            "total_available": 0,
            "raw_total_available": 0,
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
    assert "No matches" not in html
    assert "js-shelfmark-results-state" not in html
    assert "External lookup query" not in html
    assert "<code>Dune</code>" not in html
    assert "Open in Shelfmark" in html


def test_search_template_renders_filter_toolbar_and_footer_state():
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
    assert 'name="shelfmark_filter_high_confidence"' not in html
    assert 'name="shelfmark_triage_filter"' not in html
    assert 'name="shelfmark_filter_has_cover" value="1" checked' in html
    assert "Show all matches" not in html
    assert "Reset" in html
    assert "Clear filters" not in html
    assert "Page 2" in html
    assert "Page 2 of 75" not in html
    assert ">Go<" not in html
    assert "shelfmark-pagination-footer__jump" not in html


def test_search_template_strips_removed_filter_params_from_saved_state():
    app = _create_app()
    context = _base_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "filters_active": True,
        "state_url": (
            "/search/stored/?query=Dune&shelfmark_page=2&shelfmark_page_size=24"
            "&shelfmark_sort=rating&shelfmark_filter_requestable=1"
            "&shelfmark_filter_has_cover=1"
        ),
        "clear_filters_url": "/search/stored/?query=Dune&shelfmark_page=1",
    }

    with app.test_request_context(
        "/search/stored/?query=Dune&shelfmark_page=2&shelfmark_page_size=24"
        "&shelfmark_sort=rating&shelfmark_filter_requestable=1&shelfmark_filter_high_confidence=1"
        "&shelfmark_filter_has_cover=1&shelfmark_series_filter=owned&shelfmark_triage_filter=strong"
    ):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert 'name="shelfmark_filter_high_confidence"' not in html
    assert 'name="shelfmark_triage_filter"' not in html
    assert 'data-search-state-url="/search/stored/?query=Dune&amp;shelfmark_page=2&amp;shelfmark_page_size=24&amp;shelfmark_sort=rating&amp;shelfmark_filter_requestable=1&amp;shelfmark_filter_has_cover=1"' in html


def test_search_template_omits_transient_modal_state_from_search_forms():
    app = _create_app()
    context = _base_context()

    with app.test_request_context(
        "/search/stored/?query=Dune&shelfmark_page=2&shelfmark_page_size=24"
        "&shelfmark_sort=rating&shelfmark_filter_requestable=1&shelfmark_filter_has_cover=1"
        "&shelfmark_detail_provider=hardcover&shelfmark_detail_id=222"
    ):
        g.shelves_access = []
        g.config_authors_max = 0
        html = render_template("search.html", **context)

    assert 'name="shelfmark_detail_provider"' not in html
    assert 'name="shelfmark_detail_id"' not in html
    assert 'data-search-state-url="/search/stored/?query=Dune&amp;shelfmark_page=2&amp;shelfmark_page_size=24&amp;shelfmark_sort=rating&amp;shelfmark_filter_requestable=1&amp;shelfmark_filter_has_cover=1"' in html


def test_request_template_renders_summary_and_pagination_for_requestable_results():
    app = _create_app()
    with app.test_request_context("/request?query=Dune&page=2&sort=popularity&requestable=1&has_cover=1"):
        html = render_template("request.html", **_request_page_context())

    assert "Request Book" in html
    assert "Search Shelfmark for a specific book" in html
    assert "224 Shelfmark matches" in html
    assert "Showing 13-24 of 58 requestable books from 224 Shelfmark matches" in html
    assert "Page 2 of 5" in html
    assert "4 non-book results suppressed" in html
    assert "19 owned books hidden" in html
    assert "11 coverless books hidden" in html
    assert 'id="requestable"' in html
    assert 'id="has_cover"' in html
    assert 'name="requestable"' in html and "checked" in html
    assert 'name="has_cover"' in html and "checked" in html
    assert 'href="/request?query=Dune&amp;page=1&amp;sort=popularity&amp;requestable=1&amp;has_cover=1"' in html
    assert 'href="/request?query=Dune&amp;page=3&amp;sort=popularity&amp;requestable=1&amp;has_cover=1"' in html
    assert 'data-total-available="224"' in html
    assert 'data-filter-requestable="1"' in html
    assert 'data-filter-has-cover="1"' in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmark_request_flow.js" in html
    assert "External Candidate" in html
    assert "Middle-earth (5)" not in html
    assert "No cover" in html
    assert 'id="shelfmarkDetailModal"' in html
    assert 'data-search-state-url="/request?query=Dune&amp;page=2&amp;sort=popularity&amp;requestable=1&amp;has_cover=1"' in html


def test_request_template_renders_empty_state_for_filtered_request_results():
    app = _create_app()
    context = _request_page_context()
    context["shelfmark_section"] = {
        **context["shelfmark_section"],
        "results": [],
        "total_available": 0,
        "page_result_count": 0,
        "total_pages": 0,
        "visible_start": 0,
        "visible_end": 0,
        "has_previous": False,
        "previous_page": None,
        "next_page": None,
        "filtered_non_books": 0,
        "filtered_owned": 19,
        "filtered_coverless": 11,
        "summary": {
            **context["shelfmark_section"]["summary"],
            "total_results": 0,
            "total_available": 0,
            "raw_total_available": 224,
        },
    }

    with app.test_request_context("/request?query=Dune&requestable=1&has_cover=1"):
        html = render_template("request.html", **context)

    assert "No requestable books matched the current filters" in html
    assert "Try showing non-requestable matches or turning off cover filtering to widen the search." in html
    assert "Search query <code>Dune</code>" in html


def test_real_layout_renders_request_book_link_on_normal_blur_page():
    app = _create_real_layout_app()
    with app.test_request_context("/"):
        g.google_site_verification = ""
        g.current_theme = 1
        g.allow_anonymous = True
        g.allow_registration = False
        g.shelves_access = []
        g.magic_shelves_access = []
        anonymous_user = type(
            "AnonymousUser",
            (),
            {
                "is_authenticated": False,
                "is_anonymous": True,
                "name": "Guest",
                "locale": "en",
                "role_upload": staticmethod(lambda: False),
                "role_admin": staticmethod(lambda: False),
                "role_edit": staticmethod(lambda: False),
                "check_visibility": staticmethod(lambda value: True),
                "shelf": DummyShelfCollection(),
            },
        )()
        html = render_template(
            "request_layout_smoke.html",
            instance="Library",
            title="Home",
            page="index",
            bodyClass="",
            searchterm="",
            simple=True,
            accept=["epub"],
            cwa_settings={},
            current_user=anonymous_user,
            sidebar=[],
            magic_shelf_routes=type("MagicRoutes", (), {"render": False, "create": False})(),
            config=type(
                "Config",
                (),
                {
                    "config_shelfmark_search": True,
                    "config_shelfmark_url": "https://shelfmark.example.com",
                },
            )(),
        )

    assert 'class="navbar-form navbar-left cwa-navbar-search"' in html
    assert 'class="nav navbar-nav cwa-navbar-primary"' in html
    assert 'id="advanced_search"' in html
    assert 'id="request_book"' in html
    assert 'href="/request"' in html


def test_detail_template_back_link_preserves_full_saved_search_state():
    app = _create_app()
    context = _base_context()
    result = context["shelfmark_section"]["results"][1]
    return_to = context["shelfmark_section"]["state_url"]

    with app.test_request_context("/search/external/shelfmark/hardcover/222?query=Dune"):
        html = render_template(
            "shelfmark_external_detail.html",
            title=result["title"],
            result=result,
            search_query="Dune",
            return_to=return_to,
            shelfmark_error=None,
        )

    assert 'href="/search/stored/?query=Dune&amp;shelfmark_page=2&amp;shelfmark_page_size=24&amp;shelfmark_sort=rating&amp;shelfmark_filter_requestable=1&amp;shelfmark_filter_has_cover=1"' in html
