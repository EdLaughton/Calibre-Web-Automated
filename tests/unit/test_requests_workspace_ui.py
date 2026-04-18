# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from flask import Blueprint, Flask, g, redirect, render_template
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
        return redirect("/requests/series")

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
            "active_view": "series",
            "title": "Requests",
            "subtitle": "Track likely next entries and missing gaps across the series you already own.",
            "message": None,
            "sections": [
                {
                    "key": "series-next",
                    "title": "Next in series",
                    "subtitle": "Likely next books after the series you already own.",
                    "empty_message": "No likely next-in-series request candidates surfaced right now.",
                    "layout": "grouped",
                    "compact": True,
                    "see_more_url": None,
                    "load_url": "/requests/sections/series/series-next?return_to=/requests/series",
                    "loading_message": "Loading recommendations…",
                },
                {
                    "key": "series-missing",
                    "title": "Missing volumes",
                    "subtitle": "Gap fills inside series you already started.",
                    "empty_message": "No missing-volume gaps surfaced right now.",
                    "layout": "grouped",
                    "compact": True,
                    "see_more_url": None,
                    "load_url": "/requests/sections/series/series-missing?return_to=/requests/series",
                    "loading_message": "Loading recommendations…",
                },
            ],
        },
        "shelfmark_runtime": {
            "enabled": True,
            "render_modal": True,
            "render_scripts": True,
            "preferred_release_settings": {"enabled": False, "provider": "", "content_type": "ebook", "ranking": "seeders_desc"},
            "state_url": "/requests",
        },
        "title": "Requests",
        "page": "requests",
    }


def _requests_section_context():
    return {
        "section": {
            "key": "series-next",
            "title": "Next in series",
            "subtitle": "Likely next books after the series you already own.",
            "empty_message": "No likely next-in-series request candidates surfaced right now.",
            "layout": "grouped",
            "compact": True,
            "see_more_url": None,
            "has_content": True,
            "groups": [
                {
                    "key": "discworld",
                    "title": "Discworld",
                    "hint": "12 books in your library · Owned through 11",
                    "count": 1,
                    "candidates": [_requests_candidate()],
                }
            ],
            "candidates": [],
        },
        "preferred_release_settings": {"enabled": False, "provider": "", "content_type": "ebook", "ranking": "seeders_desc"},
    }


def _import_render_template_module(monkeypatch):
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

        @staticmethod
        def check_visibility(_visibility):
            return True

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
    monkeypatch.setattr(
        module,
        "url_for",
        lambda endpoint, **kwargs: "/" + endpoint.replace(".", "/") + (
            "?" + "&".join(f"{key}={value}" for key, value in sorted(kwargs.items()))
            if kwargs
            else ""
        ),
    )
    return module


class _LayoutCurrentUser:
    locale = "en"
    name = "Reader"
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


def _create_real_layout_app(sidebar_sections):
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    app.config["SECRET_KEY"] = "test-secret"
    app.jinja_loader = ChoiceLoader(
        [
            DictLoader(
                {
                    "image.html": (
                        "{% macro book_cover(book, alt=None) %}"
                        "<img alt=\"{{ alt or 'cover' }}\" src=\"/static/test-cover.png\">"
                        "{% endmacro %}"
                    ),
                    "layout_nav_smoke.html": (
                        "{% extends 'layout.html' %}"
                        "{% block body %}<div id=\"page-body\">shell ok</div>{% endblock %}"
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

    @app.before_request
    def _setup_globals():
        g.google_site_verification = ""
        g.current_theme = 0
        g.allow_anonymous = False
        g.allow_registration = False
        g.allow_upload = False
        g.shelves_access = []
        g.magic_shelves_access = []

    def _layout_context(page, title):
        return {
            "instance": "Calibre-Web Automated",
            "title": title,
            "page": page,
            "nav_active_page": page,
            "bodyClass": "",
            "cwa_settings": {},
            "current_user": _LayoutCurrentUser(),
            "searchterm": "",
            "simple": True,
            "sidebar": [],
            "sidebar_sections": sidebar_sections,
            "magic_shelf_routes": {"render": False, "create": False},
            "duplicate_notification": {"count": 0},
            "accept": [],
            "pagination": None,
        }

    web = Blueprint("web", __name__)
    search = Blueprint("search", __name__)
    shelf = Blueprint("shelf", __name__)
    about = Blueprint("about", __name__)

    @web.route("/")
    def index():
        return render_template("layout_nav_smoke.html", **_layout_context("hot", "Home"))

    @web.route("/list")
    def books_list():
        return "books"

    @web.route("/requests")
    def requests_workspace():
        return redirect("/requests/series")

    @web.route("/requests/<view_name>")
    def requests_workspace_view(view_name):
        return render_template(
            "layout_nav_smoke.html",
            **_layout_context("requests-" + view_name, "Requests"),
        )

    @web.route("/profile")
    def profile():
        return "profile"

    @web.route("/logout")
    def logout():
        return "logout"

    @search.route("/search")
    def simple_search():
        return "search"

    @search.route("/search/advanced")
    def advanced_search():
        return "advanced"

    @shelf.route("/shelf/create")
    def create_shelf():
        return "create-shelf"

    @about.route("/about")
    def package_versions():
        return "about"

    app.register_blueprint(web)
    app.register_blueprint(search)
    app.register_blueprint(shelf)
    app.register_blueprint(about)
    return app


def test_requests_template_renders_async_shell_without_duplicate_top_subnav():
    app = _create_requests_app()
    context = _requests_workspace_context()

    with app.test_request_context("/requests/series"):
        html = render_template("requests.html", **context)

    assert "Requests" in html
    assert "Track likely next entries and missing gaps across the series you already own." in html
    assert "Next in series" in html
    assert "Missing volumes" in html
    assert "Loading recommendations…" in html
    assert 'class="requests-workspace-section requests-workspace-section--shell js-requests-section-shell"' in html
    assert 'data-section-url="/requests/sections/series/series-next?return_to=/requests/series"' in html
    assert 'data-section-url="/requests/sections/series/series-missing?return_to=/requests/series"' in html
    assert "Witches Abroad" not in html
    assert "requests-workspace-subnav" not in html
    assert "shelfmark_request_flow.js" in html
    assert "shelfmark_external_search.js" in html
    assert "requests_workspace_async.js" in html
    assert "shelfmarkDetailModal" in html


def test_requests_root_redirects_to_series_view():
    app = _create_requests_app()

    with app.test_client() as client:
        response = client.get("/requests")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/requests/series")


def test_requests_section_partial_renders_grouped_series_section():
    app = _create_requests_app()
    context = _requests_section_context()
    context["section"] = {
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

    with app.test_request_context("/requests/sections/series/series-next?return_to=/requests/series"):
        html = render_template("requests_workspace_section.html", **context)

    assert "Next in series" in html
    assert "Discworld" in html
    assert "12 books in your library" in html
    assert "requests-candidate-card--compact" in html
    assert "Missing volume" in html


def test_requests_sidebar_includes_requests_link(monkeypatch):
    module = _import_render_template_module(monkeypatch)

    app = Flask(__name__)
    with app.test_request_context("/", headers={"User-Agent": "Mozilla/5.0"}):
        sidebar, simple = module.get_sidebar_config()

    assert simple is False
    requests_heading = next(item for item in sidebar if item["id"] == "requests-heading")
    requests_series = next(item for item in sidebar if item["id"] == "requests-series")
    requests_authors = next(item for item in sidebar if item["id"] == "requests-authors")
    requests_hot = next(item for item in sidebar if item["id"] == "requests-hot")
    requests_new = next(item for item in sidebar if item["id"] == "requests-new")
    sidebar_sections = module.build_sidebar_sections(sidebar)

    assert requests_heading["kind"] == "heading"
    assert requests_heading["text"] == "Requests"
    assert "requests-home" not in {item["id"] for item in sidebar}
    assert requests_authors["href"] == "/web/requests_workspace_view?view_name=authors"
    assert requests_series["href"] == "/web/requests_workspace_view?view_name=series"
    assert requests_hot["href"] == "/web/requests_workspace_view?view_name=hot"
    assert requests_new["href"] == "/web/requests_workspace_view?view_name=new"
    assert requests_hot["page"] == "requests-hot"
    assert [section["id"] for section in sidebar_sections] == ["browse", "requests"]
    assert [item["id"] for item in sidebar_sections[1]["entries"]] == [
        "requests-authors",
        "requests-series",
        "requests-hot",
        "requests-new",
    ]


def test_real_layout_sidebar_renders_requests_and_non_requests_pages(monkeypatch):
    module = _import_render_template_module(monkeypatch)
    sidebar_sections = module.build_sidebar_sections(
        [
            {
                "glyph": "glyphicon-fire",
                "text": "Hot Books",
                "link": "web.books_list",
                "id": "hot",
                "visibility": 1,
                "public": True,
                "page": "hot",
            },
            {
                "kind": "heading",
                "text": "Requests",
                "id": "requests-heading",
                "section": "requests",
                "visibility": 1,
                "public": True,
                "page": "requests",
            },
            {
                "glyph": "glyphicon-bookmark",
                "text": "Series",
                "link": "web.requests_workspace_view",
                "href": "/requests/series",
                "id": "requests-series",
                "section": "requests",
                "visibility": 1,
                "public": True,
                "page": "requests-series",
            },
        ]
    )
    app = _create_real_layout_app(sidebar_sections)

    with app.test_client() as client:
        home_response = client.get("/")
        requests_root_response = client.get("/requests", follow_redirects=False)
        requests_view_response = client.get("/requests/series")

    assert home_response.status_code == 200
    assert "nav_requests-series" in home_response.text
    assert "nav-subitem nav-subitem--requests" in home_response.text
    assert "shell ok" in home_response.text

    assert requests_root_response.status_code == 302
    assert requests_root_response.headers["Location"].endswith("/requests/series")

    assert requests_view_response.status_code == 200
    assert "Requests" in requests_view_response.text
    assert "Series" in requests_view_response.text
    assert 'id="nav_requests-series"' in requests_view_response.text
