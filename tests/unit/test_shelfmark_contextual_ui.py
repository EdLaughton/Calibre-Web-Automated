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


def _build_contextual_result(title="The Amazing Maurice", provider_id="222"):
    return {
        "provider": "hardcover",
        "provider_id": provider_id,
        "title": title,
        "subtitle": None,
        "authors": ["Terry Pratchett"],
        "cover_url": "https://covers.example.com/%s.jpg" % provider_id,
        "description": "A missing, requestable candidate.",
        "facts": ["Discworld (28)", "2001"],
        "series_context": {
            "matched": True,
            "is_next_missing": True,
        },
        "already_in_library": False,
        "library_book_url": None,
        "library_book_title": None,
        "detail_url": "/search/external/shelfmark/hardcover/%s?query=Discworld" % provider_id,
        "shelfmark_base_url": "https://library.example.com/shelfmark",
        "shelfmark_open_url": "https://library.example.com/shelfmark/?query=%s" % title.replace(" ", "+"),
        "request_payload": {
            "book_data": {"provider": "hardcover", "provider_id": provider_id, "title": title},
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
        "row_status_provider_id": provider_id,
        "row_status_in_library": "0",
        "row_has_cover": "1",
        "row_enrichment_url": None,
    }


def _build_contextual_section(subtitle, *, available=True, message=None, load_more_url=None):
    return {
        "enabled": True,
        "available": available,
        "variant": "contextual",
        "has_page_shell": available,
        "render_modal": False,
        "render_scripts": False,
        "section_title": "Shelfmark",
        "section_subtitle": subtitle,
        "state_url": "/author/stored/1",
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
        "load_more_url": load_more_url,
    }


def _build_runtime():
    return {
        "enabled": True,
        "render_modal": True,
        "render_scripts": True,
        "state_url": "/author/stored/1",
    }


def _build_loader(initial_url, context_type):
    return {
        "container_id": f"shelfmark-contextual-{context_type}",
        "initial_url": initial_url,
        "loading_message": "Loading Shelfmark results…",
        "failure_message": "Shelfmark is unavailable right now.",
        "load_more_failure_message": "Could not load more Shelfmark results right now.",
    }


def test_author_template_renders_async_placeholder_without_sync_shelfmark_markup():
    app = _create_app()
    context = {
        "title": "Author: Terry Pratchett",
        "author_profile": {
            "name": "Terry Pratchett",
            "image_url": "https://assets.hardcover.app/author/terry.jpg",
            "safe_about": "<p>Discworld creator.</p>",
            "link": "https://hardcover.app/authors/terry-pratchett",
            "source_label": "Hardcover",
        },
        "entries": [DummyEntry(DummyBook(1, "Mort", "Terry Pratchett", "Discworld"))],
        "pagination": None,
        "id": 1,
        "page": "author",
        "order": "abc",
        "simple": True,
        "current_user": DummyCurrentUser(),
        "shelfmark_runtime": _build_runtime(),
        "shelfmark_loader": _build_loader("/author/1/shelfmark?return_to=%2Fauthor%2Fstored%2F1", "author"),
    }

    with app.test_request_context("/author/stored/1"):
        g.config_authors_max = 3
        g.shelves_access = []
        html = render_template("author.html", **context)

    assert "Discworld creator." in html
    assert "Hardcover" in html
    assert "https://assets.hardcover.app/author/terry.jpg" in html
    assert 'class="author-bio__content"' in html
    assert 'class="author-bio__copy is-collapsed js-author-bio-copy"' in html
    assert 'class="author-bio__toggle js-author-bio-toggle"' in html
    assert 'data-collapsed-label="Read more"' in html
    assert 'data-expanded-label="Show less"' in html
    assert 'class="author-bio__meta"' in html
    assert "Read more" in html
    assert "Show less" in html
    assert "The Amazing Maurice" not in html
    assert "More by" not in html
    assert "goodreads.svg" not in html
    assert 'class="shelfmark-contextual-async js-shelfmark-contextual-async"' in html
    assert 'data-initial-url="/author/1/shelfmark?return_to=%2Fauthor%2Fstored%2F1"' in html
    assert "Loading Shelfmark results…" in html
    assert 'id="shelfmarkDetailModal"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmark_contextual_async.js" in html
    assert "js-shelfmark-results-list" not in html


def test_series_template_renders_async_placeholder_without_sync_shelfmark_markup():
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
        "shelfmark_runtime": _build_runtime(),
        "shelfmark_loader": _build_loader("/series/1/shelfmark?return_to=%2Fseries%2Fstored%2F1", "series"),
    }

    with app.test_request_context("/series/stored/1"):
        g.config_authors_max = 3
        html = render_template("index.html", **context)

    assert "The Amazing Maurice" not in html
    assert 'class="shelfmark-contextual-async js-shelfmark-contextual-async"' in html
    assert 'data-initial-url="/series/1/shelfmark?return_to=%2Fseries%2Fstored%2F1"' in html
    assert "Loading Shelfmark results…" in html
    assert 'id="shelfmarkDetailModal"' in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmark_contextual_async.js" in html
    assert "js-shelfmark-results-list" not in html


def test_contextual_async_section_template_renders_exact_author_heading_and_load_more():
    app = _create_app()
    section = _build_contextual_section(
        "Missing most popular requestable books by this author from Shelfmark",
        load_more_url="/author/1/shelfmark?offset=8&append=1",
    )

    with app.test_request_context("/author/1/shelfmark"):
        html = render_template("shelfmark_contextual_async_section.html", shelfmark_section=section)

    assert "Shelfmark" in html
    assert "Missing most popular requestable books by this author from Shelfmark" in html
    assert "The Amazing Maurice" in html
    assert "Open in Shelfmark" in html
    assert "Load more" in html
    assert 'data-load-url="/author/1/shelfmark?offset=8&amp;append=1"' in html


def test_contextual_async_section_template_renders_unavailable_message_compactly():
    app = _create_app()
    section = _build_contextual_section(
        "Missing most popular requestable books by this author from Shelfmark",
        available=False,
        message="Shelfmark is unavailable right now.",
    )

    with app.test_request_context("/author/1/shelfmark"):
        html = render_template("shelfmark_contextual_async_section.html", shelfmark_section=section)

    assert "Shelfmark is unavailable right now." in html
    assert "js-shelfmark-results-list" not in html


def test_contextual_async_append_template_renders_follow_on_batch_and_optional_load_more():
    app = _create_app()
    section = _build_contextual_section(
        "Missing requestable books for this series from Shelfmark",
        load_more_url=None,
    )
    section["results"] = [
        _build_contextual_result("Snuff", "401"),
        _build_contextual_result("Raising Steam", "402"),
    ]

    with app.test_request_context("/series/1/shelfmark?offset=8&append=1"):
        html = render_template("shelfmark_contextual_async_append.html", shelfmark_section=section)

    assert "Snuff" in html
    assert "Raising Steam" in html
    assert "Load more" not in html
