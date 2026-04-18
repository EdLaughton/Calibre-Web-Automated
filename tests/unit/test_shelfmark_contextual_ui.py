# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib
from pathlib import Path
import sys

from flask import Blueprint, Flask, g, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "cps" / "templates"


class DummyAuthor:
    def __init__(self, author_id, name):
        self.id = author_id
        self.name = name


class DummySeries:
    def __init__(self, series_id, name):
        self.id = series_id
        self.name = name


class DummyBook:
    def __init__(self, book_id, title, author_name, series_name=None):
        self.id = book_id
        self.title = title
        self.has_cover = True
        self.authors = [DummyAuthor(1, author_name)]
        self.series = [DummySeries(1, series_name)] if series_name else []
        self.series_index = 1.0
        self.ratings = []
        self.data = []


class DummyEntry:
    def __init__(self, book):
        self.Books = book
        self._values = [book, None, False]

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

    @staticmethod
    def show_detail_random():
        return False


def _create_app():
    flask_module = sys.modules.get("flask")
    if flask_module is not None and not hasattr(flask_module, "__path__"):
        sys.modules.pop("flask", None)
        importlib.import_module("flask")

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
                        "{% macro book_cover(book, alt=None) %}"
                        "<img alt=\"{{ alt or book.title }}\" src=\"/static/test-cover.png\">"
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
    search = Blueprint("search", __name__)

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @web.route("/list")
    def books_list():
        return "books"

    @search.route("/search/external/shelfmark/<provider>/<provider_id>")
    def shelfmark_external_detail(provider, provider_id):
        return f"detail:{provider}:{provider_id}"

    app.register_blueprint(web)
    app.register_blueprint(search)
    return app


def _build_contextual_result():
    return {
        "provider": "hardcover",
        "provider_id": "222",
        "title": "The Amazing Maurice",
        "subtitle": None,
        "authors": ["Terry Pratchett"],
        "cover_url": "https://covers.example.com/222.jpg",
        "description": "A missing, requestable candidate.",
        "facts": ["Discworld (28)", "2001"],
        "series_context": {
            "matched": True,
            "is_next_missing": True,
        },
        "already_in_library": False,
        "library_book_url": None,
        "library_book_title": None,
        "detail_url": "/search/external/shelfmark/hardcover/222?query=Discworld",
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": "https://library.example.com/shelfmark/?query=The+Amazing+Maurice",
        "request_payload": {
            "book_data": {"provider": "hardcover", "provider_id": "222", "title": "The Amazing Maurice"},
            "context": {"source": "*", "content_type": "ebook", "request_level": "book"},
        },
        "library_state": {
            "row_class": "info",
            "panel_class": "panel-info",
            "icon_class": "glyphicon glyphicon-cloud-download",
            "key": "external_candidate",
            "label": None,
            "hint": None,
            "badge_class": None,
        },
        "action": {
            "mode": "request",
            "label": "Request in Shelfmark",
            "hint": None,
            "button_class": "btn-primary",
            "icon_class": "glyphicon glyphicon-send",
        },
        "workflow_state": {
            "key": "available",
            "label": "Available",
            "chip_class": "shelfmark-status-chip--available",
        },
        "needs_progressive_enrichment": False,
        "progressive_filter_pending": False,
        "row_index": 0,
        "row_class_name": "shelfmark-result-card js-shelfmark-result-row shelfmark-result-card--info js-shelfmark-status-target js-shelfmark-batch-row",
        "row_status_provider": "hardcover",
        "row_status_provider_id": "222",
        "row_status_in_library": "0",
        "row_has_cover": "1",
        "row_enrichment_url": None,
    }


def _build_contextual_section(subtitle, *, available=True, message=None):
    return {
        "enabled": True,
        "available": available,
        "variant": "contextual",
        "has_page_shell": available,
        "render_modal": available,
        "render_scripts": available,
        "section_title": "Shelfmark",
        "section_subtitle": subtitle,
        "state_url": "/author/1",
        "page": 1,
        "page_size": 8,
        "page_result_count": 1 if available else 0,
        "filter_requestable": True,
        "filter_has_cover": True,
        "open_search_url": "https://library.example.com/shelfmark/?query=Terry+Pratchett",
        "preferred_release_settings": {
            "enabled": False,
            "provider": "",
            "content_type": "ebook",
            "ranking": "seeders_desc",
        },
        "results": [_build_contextual_result()] if available else [],
        "message": message,
    }


def test_author_template_renders_contextual_shelfmark_section():
    app = _create_app()
    context = {
        "title": "Author: Terry Pratchett",
        "author": None,
        "entries": [DummyEntry(DummyBook(1, "Mort", "Terry Pratchett", "Discworld"))],
        "pagination": None,
        "id": 1,
        "other_books": [],
        "page": "author",
        "order": "abc",
        "simple": True,
        "current_user": DummyCurrentUser(),
        "shelfmark_section": _build_contextual_section(
            "Missing requestable books by this author from Shelfmark"
        ),
    }

    with app.test_request_context("/author/1"):
        g.config_authors_max = 3
        g.shelves_access = []
        html = render_template("author.html", **context)

    assert "Missing requestable books by this author from Shelfmark" in html
    assert "The Amazing Maurice" in html
    assert "Request in Shelfmark" in html
    assert "Bulk mode" not in html
    assert "shelfmark-pagination-footer" not in html
    assert 'id="shelfmarkDetailModal"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html


def test_series_template_renders_contextual_shelfmark_section():
    app = _create_app()
    context = {
        "title": "Series: Discworld",
        "random": [],
        "entries": [DummyEntry(DummyBook(1, "Mort", "Terry Pratchett", "Discworld"))],
        "pagination": None,
        "id": 1,
        "page": "series",
        "order": "seriesasc",
        "simple": True,
        "current_user": DummyCurrentUser(),
        "shelfmark_section": _build_contextual_section(
            "Missing requestable books for this series from Shelfmark"
        ),
    }

    with app.test_request_context("/series/1"):
        g.config_authors_max = 3
        html = render_template("index.html", **context)

    assert "Missing requestable books for this series from Shelfmark" in html
    assert "The Amazing Maurice" in html
    assert "Open in Shelfmark" in html
    assert "Bulk mode" not in html
    assert "shelfmark-pagination-footer" not in html
    assert 'id="shelfmarkDetailModal"' in html


def test_contextual_templates_render_unavailable_message_without_scripts():
    app = _create_app()
    context = {
        "title": "Author: Terry Pratchett",
        "author": None,
        "entries": [DummyEntry(DummyBook(1, "Mort", "Terry Pratchett", "Discworld"))],
        "pagination": None,
        "id": 1,
        "other_books": [],
        "page": "author",
        "order": "abc",
        "simple": True,
        "current_user": DummyCurrentUser(),
        "shelfmark_section": _build_contextual_section(
            "Missing requestable books by this author from Shelfmark",
            available=False,
            message="Shelfmark is unavailable right now.",
        ),
    }

    with app.test_request_context("/author/1"):
        g.config_authors_max = 3
        g.shelves_access = []
        html = render_template("author.html", **context)

    assert "Shelfmark is unavailable right now." in html
    assert "js-shelfmark-results-list" not in html
    assert "shelfmark_request_flow.js" not in html
    assert 'id="shelfmarkDetailModal"' not in html
