# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from flask import Blueprint, Flask, g, render_template, render_template_string

from cps import config
from cps.shelfmark import shelfmark_search as shelfmark_blueprint
import cps.shelfmark as shelfmark_module
from cps.services.shelfmark_client import ShelfmarkClientConfig


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "cps" / "templates"


class _DummyCurrentUser:
    id = 7
    name = "Shelfmark Tester"
    locale = "en"
    is_authenticated = True
    is_anonymous = False

    @staticmethod
    def role_admin():
        return False

    @staticmethod
    def role_edit():
        return False

    @staticmethod
    def role_upload():
        return False


class _DummyLayoutUser:
    name = "Guest"
    locale = "en"
    is_authenticated = False
    is_anonymous = True

    @staticmethod
    def role_admin():
        return False

    @staticmethod
    def role_edit():
        return False

    @staticmethod
    def role_upload():
        return False

    @staticmethod
    def check_visibility(_visibility):
        return True


@pytest.fixture
def shelfmark_ui_app(monkeypatch):
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.jinja_env.globals["csrf_token"] = lambda: "csrf-token"
    app.jinja_env.globals["_"] = lambda value, **kwargs: value % kwargs if kwargs else value
    app.jinja_env.filters["yesno"] = lambda value, true_value, false_value: true_value if value else false_value
    app.jinja_env.filters["shortentitle"] = lambda value, *args, **kwargs: value
    app.jinja_env.filters["formatfloat"] = lambda value, *args, **kwargs: value
    app.jinja_env.filters["music"] = lambda value: False
    app.jinja_env.filters["get_cover_srcset"] = lambda value: ""
    app.jinja_env.filters["get_series_srcset"] = lambda value: ""
    app.jinja_env.filters["last_modified"] = lambda value: ""
    app.jinja_env.filters["cache_timestamp"] = lambda value: ""
    app.jinja_env.globals["config"] = types.SimpleNamespace(
        config_shelfmark_search=True,
        config_shelfmark_url="https://shelfmark.example.com",
    )
    app.jinja_env.globals["current_user"] = _DummyLayoutUser()

    web = Blueprint("web", __name__)
    search = Blueprint("search", __name__)
    tasks = Blueprint("tasks", __name__)
    admin = Blueprint("admin", __name__)
    edit_book = Blueprint("edit-book", __name__)

    @web.route("/")
    def index():
        return "index"

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @web.route("/login")
    def login():
        return "login"

    @web.route("/logout")
    def logout():
        return "logout"

    @web.route("/profile")
    def profile():
        return "profile"

    @search.route("/search")
    def simple_search():
        return "search"

    @search.route("/search/advanced")
    def advanced_search():
        return "advanced"

    @tasks.route("/tasks")
    def get_tasks_status():
        return "tasks"

    @admin.route("/admin")
    def admin_index():
        return "admin"

    @edit_book.route("/upload", methods=["POST"])
    def upload():
        return "upload"

    @app.route("/layout-test")
    def layout_test():
        g.google_site_verification = ""
        g.current_theme = 0
        g.allow_anonymous = True
        g.allow_registration = False
        g.allow_upload = False
        return render_template_string(
            "{% extends 'layout.html' %}{% block body %}<div>body</div>{% endblock %}",
            instance="CWA",
            title="Layout Test",
            page="layout",
            bodyClass="",
            cwa_settings={},
            searchterm="",
            simple=True,
            accept=[],
            sidebar=[],
            sidebar_sections=[],
        )

    app.register_blueprint(web)
    app.register_blueprint(search)
    app.register_blueprint(tasks)
    app.register_blueprint(admin)
    app.register_blueprint(edit_book)
    app.register_blueprint(shelfmark_blueprint)

    monkeypatch.setattr(config, "config_anonbrowse", 1, raising=False)
    monkeypatch.setattr(config, "config_allow_reverse_proxy_header_login", False, raising=False)
    monkeypatch.setattr(shelfmark_module, "current_user", _DummyCurrentUser())
    monkeypatch.setattr(shelfmark_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)
    monkeypatch.setattr(
        shelfmark_module,
        "get_shelfmark_client_config",
        lambda: ShelfmarkClientConfig(
            enabled=True,
            base_url="https://shelfmark.example.com",
            username="",
            password="",
        ),
    )
    monkeypatch.setattr(
        shelfmark_module,
        "render_title_template",
        lambda template_name, **context: render_template(template_name, **context),
    )

    return app


@pytest.fixture
def shelfmark_ui_client(shelfmark_ui_app):
    return shelfmark_ui_app.test_client()


def test_top_bar_entry_renders_and_links_correctly(shelfmark_ui_client):
    response = shelfmark_ui_client.get("/layout-test")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="shelfmark_request"' in html
    assert 'href="/shelfmark"' in html
    assert "Request Book" in html


def test_search_page_renders_results(shelfmark_ui_client, monkeypatch):
    monkeypatch.setattr(
        shelfmark_module,
        "search_shelfmark",
        lambda *_args, **_kwargs: {
            "query": "dune",
            "results": [
                {
                    "key": "hardcover:123",
                    "provider": "hardcover",
                    "provider_id": "123",
                    "title": "Dune",
                    "subtitle": "",
                    "authors": ["Frank Herbert"],
                    "cover_url": "",
                    "series_name": "Dune",
                    "series_position": 1,
                    "facts": ["1965", "Hardcover"],
                    "detail_url": "/shelfmark/detail/hardcover/123?query=dune",
                    "action": {
                        "mode": "open_existing",
                        "label": "Open existing CWA book",
                        "button_class": "btn-success",
                        "href": "/book/42",
                        "disabled": False,
                        "hint": "",
                    },
                }
            ],
            "error": "",
            "total_found": 1,
            "searched": True,
        },
    )

    response = shelfmark_ui_client.get(
        "/shelfmark?query=dune",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Request Book" in html
    assert "Dune" in html
    assert "Frank Herbert" in html
    assert "Open existing CWA book" in html


def test_details_overlay_renders_with_hardcover_enrichment(shelfmark_ui_client, monkeypatch):
    monkeypatch.setattr(
        shelfmark_module,
        "get_shelfmark_detail_view",
        lambda *_args, **_kwargs: {
            "provider": "hardcover",
            "provider_id": "123",
            "title": "Dune",
            "subtitle": "The novel",
            "authors": ["Frank Herbert"],
            "description": "Classic science fiction.",
            "cover_url": "",
            "publisher": "Chilton",
            "publish_year": "1965",
            "language": "en",
            "series_name": "Dune",
            "series_position": 1,
            "series_count": 6,
            "genres": ("Science Fiction",),
            "isbn_10": "",
            "isbn_13": "9780441172719",
            "source_url": "https://shelfmark.example.com/books/123",
            "action": {
                "mode": "request",
                "label": "Request in Shelfmark",
                "button_class": "btn-primary",
                "href": "",
                "disabled": False,
                "hint": "",
                "payload_json": json.dumps({"book_data": {"provider": "hardcover", "provider_id": "123"}}),
            },
            "library_match": None,
            "queue_summary": None,
            "hardcover_overlay": types.SimpleNamespace(
                series="Dune",
                series_index=1,
                published_date="1965-08-01",
                publisher="Chilton",
                language="en",
                tags=("Epic", "Classic"),
                description="Expanded metadata.",
            ),
        },
    )

    response = shelfmark_ui_client.get(
        "/shelfmark/detail/hardcover/123?query=dune",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Dune" in html
    assert "Hardcover enrichment" in html
    assert "Expanded metadata." in html


def test_details_overlay_degrades_cleanly_without_hardcover(shelfmark_ui_client, monkeypatch):
    monkeypatch.setattr(
        shelfmark_module,
        "get_shelfmark_detail_view",
        lambda *_args, **_kwargs: {
            "provider": "google",
            "provider_id": "abc",
            "title": "The Left Hand of Darkness",
            "subtitle": "",
            "authors": ["Ursula K. Le Guin"],
            "description": "Shelfmark-only details still render.",
            "cover_url": "",
            "publisher": "",
            "publish_year": "1969",
            "language": "en",
            "series_name": "",
            "series_position": None,
            "series_count": None,
            "genres": (),
            "isbn_10": "",
            "isbn_13": "",
            "source_url": "",
            "action": {
                "mode": "request",
                "label": "Request in Shelfmark",
                "button_class": "btn-primary",
                "href": "",
                "disabled": False,
                "hint": "",
                "payload_json": json.dumps({"book_data": {"provider": "google", "provider_id": "abc"}}),
            },
            "library_match": None,
            "queue_summary": None,
            "hardcover_overlay": None,
        },
    )

    response = shelfmark_ui_client.get(
        "/shelfmark/detail/google/abc?query=left+hand",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "The Left Hand of Darkness" in html
    assert "Shelfmark-only details still render." in html
    assert "Hardcover enrichment" not in html


def test_request_post_creates_persisted_queue_row(shelfmark_ui_client, temp_cwa_db, monkeypatch):
    import cps.services.shelfmark_queue as queue_module

    class _FakeShelfmarkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def create_request(_payload):
            return {
                "id": 55,
                "status": "pending",
                "delivery_state": "queued",
                "release_data": {
                    "source": "annas_archive",
                    "source_id": "abc-123",
                },
            }

    monkeypatch.setattr(queue_module, "ShelfmarkClient", _FakeShelfmarkClient)

    payload = {
        "book_data": {
            "title": "Dune",
            "author": "Frank Herbert",
            "content_type": "ebook",
            "provider": "hardcover",
            "provider_id": "123",
            "isbn_13": "9780441172719",
        },
        "release_data": {"source": "annas_archive", "source_id": "abc-123"},
        "context": {"source": "*", "content_type": "ebook", "request_level": "book"},
    }

    response = shelfmark_ui_client.post(
        "/shelfmark/request",
        data={
            "request_payload": json.dumps(payload),
            "return_to": "/shelfmark?query=dune",
        },
    )

    assert response.status_code == 302
    rows = temp_cwa_db.shelfmark_queue_get_latest_for_items([("hardcover", "123")])
    assert len(rows) == 1
    assert rows[0]["title"] == "Dune"
    assert rows[0]["status"] == "queued"
    assert rows[0]["external_request_id"] == 55
