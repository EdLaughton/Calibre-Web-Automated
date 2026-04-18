# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from flask import Blueprint, Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "cps" / "templates"
RENDER_TEMPLATE_MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "render_template.py"


def _create_requests_app():
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

    @web.route("/requests")
    def requests_workspace():
        return "requests"

    @web.route("/requests/<view_name>")
    def requests_workspace_view(view_name):
        return view_name

    @web.route("/book/<int:book_id>")
    def show_book(book_id):
        return f"book:{book_id}"

    @search.route("/search/external/shelfmark/<provider>/<provider_id>")
    def shelfmark_external_detail(provider, provider_id):
        return f"detail:{provider}:{provider_id}"

    app.register_blueprint(web)
    app.register_blueprint(search)
    return app


def _requests_candidate(*, key="discworld:3", title="Witches Abroad", reason_label="Next in series"):
    return {
        "key": key,
        "priority_bucket": "high",
        "result": {
            "provider": "hardcover",
            "provider_id": key.replace(":", "-"),
            "title": title,
            "subtitle": None,
            "authors": ["Terry Pratchett"],
            "cover_url": "https://covers.example.com/%s.jpg" % key.replace(":", "-"),
            "description": "A strong request candidate.",
            "facts": ["Discworld (12)", "1991"],
            "recommendation_reason_label": reason_label,
            "recommendation_reason_detail": "Next after volume 11 in a series you own",
            "secondary_series_note": "Also in Witches",
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
            "already_in_library": False,
            "library_book_url": None,
            "library_book_title": None,
            "detail_url": "/search/external/shelfmark/hardcover/%s?query=Discworld" % key.replace(":", "-"),
            "shelfmark_base_url": "https://library.example.com/shelfmark",
            "shelfmark_open_url": "https://library.example.com/shelfmark/?query=Witches+Abroad",
            "request_payload": {
                "book_data": {"provider": "hardcover", "provider_id": key.replace(":", "-"), "title": title},
                "context": {"source": "*", "content_type": "ebook", "request_level": "book"},
            },
            "library_state": {
                "row_class": "info",
            },
        },
    }


def _requests_workspace_context():
    return {
        "requests_workspace": {
            "enabled": True,
            "active_view": "home",
            "title": "Requests",
            "subtitle": "Find likely next additions from the series and authors you already care about.",
            "message": None,
            "tabs": [
                {"key": "home", "label": "Home", "url": "/requests", "active": True},
                {"key": "series", "label": "Series", "url": "/requests/series", "active": False},
                {"key": "authors", "label": "Authors", "url": "/requests/authors", "active": False},
                {"key": "discover", "label": "Discover", "url": "/requests/discover", "active": False},
            ],
            "sections": [
                {
                    "key": "home-next",
                    "title": "Continue series",
                    "subtitle": "Likely next books to keep your current series moving.",
                    "empty_message": "No series continuations surfaced right now.",
                    "layout": "cards",
                    "compact": False,
                    "see_more_url": "/requests/series",
                    "has_content": True,
                    "groups": [],
                    "candidates": [_requests_candidate()],
                },
                {
                    "key": "home-authors",
                    "title": "More from authors you own",
                    "subtitle": "Popular missing books by authors already represented locally.",
                    "empty_message": "No author-led expansions surfaced right now.",
                    "layout": "cards",
                    "compact": False,
                    "see_more_url": "/requests/authors",
                    "has_content": False,
                    "groups": [],
                    "candidates": [],
                },
            ],
        },
        "shelfmark_runtime": {
            "enabled": True,
            "render_modal": True,
            "render_scripts": True,
            "state_url": "/requests",
        },
        "title": "Requests",
        "page": "requests",
    }


def test_requests_template_renders_sections_tabs_and_shelfmark_runtime():
    app = _create_requests_app()
    context = _requests_workspace_context()

    with app.test_request_context("/requests"):
        html = render_template("requests.html", **context)

    assert "Requests" in html
    assert "Discovery and acquisition" in html
    assert 'href="/requests/series"' in html
    assert "Continue series" in html
    assert "More from authors you own" in html
    assert "No author-led expansions surfaced right now." in html
    assert "Request in Shelfmark" in html
    assert "Next after volume 11 in a series you own" in html
    assert "Also in Witches" in html
    assert "js-shelfmark-action" in html
    assert "js-shelfmark-detail-link" in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "shelfmarkDetailModal" in html


def test_requests_template_renders_grouped_series_section():
    app = _create_requests_app()
    context = _requests_workspace_context()
    context["requests_workspace"]["active_view"] = "series"
    context["requests_workspace"]["tabs"][0]["active"] = False
    context["requests_workspace"]["tabs"][1]["active"] = True
    context["requests_workspace"]["sections"] = [
        {
            "key": "series-next",
            "title": "Next in series",
            "subtitle": "Likely next books after the series you already own.",
            "empty_message": "No likely next-in-series request candidates surfaced right now.",
            "layout": "grouped",
            "compact": True,
            "see_more_url": None,
            "has_content": True,
            "candidates": [],
            "groups": [
                {
                    "key": "discworld",
                    "title": "Discworld",
                    "hint": "12 books in your library · Owned through 11",
                    "count": 1,
                    "candidates": [_requests_candidate(reason_label="Missing volume")],
                }
            ],
        }
    ]

    with app.test_request_context("/requests/series"):
        html = render_template("requests.html", **context)

    assert "Next in series" in html
    assert "Discworld" in html
    assert "12 books in your library" in html
    assert "requests-candidate-card--compact" in html
    assert "Missing volume" in html


def test_requests_sidebar_includes_requests_link(monkeypatch):
    class _DummyCurrentUser:
        is_anonymous = False
        id = 1

        @staticmethod
        def role_admin():
            return False

        @staticmethod
        def role_edit():
            return False

        @staticmethod
        def filter_language():
            return "all"

    class _DummyQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return []

    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []
    cps_module.config = types.SimpleNamespace()
    cps_module.constants = types.SimpleNamespace(
        SIDEBAR_RECENT=1,
        SIDEBAR_HOT=2,
        SIDEBAR_DOWNLOAD=4,
        SIDEBAR_BEST_RATED=8,
        SIDEBAR_READ_AND_UNREAD=16,
        SIDEBAR_RANDOM=32,
        SIDEBAR_CATEGORY=64,
        SIDEBAR_SERIES=128,
        SIDEBAR_AUTHOR=256,
        SIDEBAR_PUBLISHER=512,
        SIDEBAR_LANGUAGE=1024,
        SIDEBAR_RATING=2048,
        SIDEBAR_FORMAT=4096,
        SIDEBAR_ARCHIVED=8192,
        SIDEBAR_LIST=16384,
        SIDEBAR_DUPLICATES=32768,
        SIDEBAR_REQUESTS=65536,
    )
    cps_module.logger = types.SimpleNamespace(create=lambda: types.SimpleNamespace())
    cps_module.ub = types.SimpleNamespace(
        Shelf=types.SimpleNamespace(is_public=1, user_id=1, name="Shelf"),
        session=types.SimpleNamespace(query=lambda *args, **kwargs: _DummyQuery()),
        User=type("User", (), {}),
    )
    cw_login_module = types.ModuleType("cps.cw_login")
    cw_login_module.current_user = _DummyCurrentUser()
    cwa_db_module = types.ModuleType("cwa_db")
    cwa_db_module.CWA_DB = lambda: types.SimpleNamespace(cwa_settings={})

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.config", cps_module.config)
    monkeypatch.setitem(sys.modules, "cps.constants", cps_module.constants)
    monkeypatch.setitem(sys.modules, "cps.logger", cps_module.logger)
    monkeypatch.setitem(sys.modules, "cps.ub", cps_module.ub)
    monkeypatch.setitem(sys.modules, "cps.cw_login", cw_login_module)
    monkeypatch.setitem(sys.modules, "cwa_db", cwa_db_module)

    spec = importlib.util.spec_from_file_location("cps.render_template_test", RENDER_TEMPLATE_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.render_template_test", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)

    app = Flask(__name__)
    with app.test_request_context("/", headers={"User-Agent": "Mozilla/5.0"}):
        sidebar, simple = module.get_sidebar_config()

    assert simple is False
    requests_entry = next(item for item in sidebar if item["id"] == "requests")
    assert requests_entry["text"] == "Requests"
    assert requests_entry["link"] == "web.requests_workspace"
    assert requests_entry["page"] == "requests"
