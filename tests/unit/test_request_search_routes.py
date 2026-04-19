# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "search.py"


class _DummyBlueprint:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def _gettext(value, **kwargs):
    return value % kwargs if kwargs else value


@pytest.fixture
def search_module(monkeypatch):
    render_calls = []

    flask_module = types.ModuleType("flask")
    flask_module.Blueprint = _DummyBlueprint
    flask_module.request = types.SimpleNamespace(
        args=types.SimpleNamespace(get=lambda *args, **kwargs: "", getlist=lambda *args, **kwargs: []),
        form=types.SimpleNamespace(getlist=lambda *args, **kwargs: []),
        path="/search",
        view_args={},
    )
    flask_module.redirect = lambda value: value
    flask_module.render_template = lambda *args, **kwargs: {"template": args[0], **kwargs}
    flask_module.url_for = lambda endpoint, **kwargs: f"/{endpoint}"
    flask_module.flash = lambda *args, **kwargs: None
    flask_module.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs
    flask_module.abort = lambda code: (_ for _ in ()).throw(RuntimeError(f"abort:{code}"))
    flask_module.session = {}

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.format_date = lambda value, *args, **kwargs: value
    flask_babel_module.gettext = _gettext

    sqlalchemy_expression_module = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression_module.func = types.SimpleNamespace(lower=lambda value: value)
    sqlalchemy_expression_module.not_ = lambda value: value
    sqlalchemy_expression_module.and_ = lambda *values: values
    sqlalchemy_expression_module.or_ = lambda *values: values
    sqlalchemy_expression_module.text = lambda value: value
    sqlalchemy_expression_module.true = lambda: True

    sqlalchemy_functions_module = types.ModuleType("sqlalchemy.sql.functions")
    sqlalchemy_functions_module.coalesce = lambda *values: values[0] if values else None

    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []  # treat as package for relative imports
    cps_module.logger = types.SimpleNamespace(create=lambda: types.SimpleNamespace(debug=lambda *a, **k: None))
    cps_module.db = types.SimpleNamespace(
        books_series_link=types.SimpleNamespace(c=types.SimpleNamespace(book="book", series="series")),
        Books=types.SimpleNamespace(id="book-id"),
        Series=types.SimpleNamespace(id="series-id"),
    )
    cps_module.calibre_db = types.SimpleNamespace(
        get_search_results=lambda *args, **kwargs: (["entry"], 1, "pagination"),
        order_authors=lambda *args, **kwargs: ["ordered-entry"],
    )
    cps_module.config = types.SimpleNamespace(config_shelfmark_search=True, config_shelfmark_url="https://shelfmark.example.com")
    cps_module.ub = types.SimpleNamespace(store_combo_ids=lambda *args, **kwargs: None)

    render_template_module = types.ModuleType("cps.render_template")

    def _render_title_template(template, **kwargs):
        render_calls.append((template, kwargs))
        return {"template": template, **kwargs}

    render_template_module.render_title_template = _render_title_template

    usermanagement_module = types.ModuleType("cps.usermanagement")
    usermanagement_module.login_required_if_no_ano = lambda func: func

    pagination_module = types.ModuleType("cps.pagination")
    pagination_module.Pagination = lambda *args, **kwargs: "pagination"

    cw_login_module = types.ModuleType("cps.cw_login")
    cw_login_module.current_user = types.SimpleNamespace(is_authenticated=True, id=1, name="Tester")

    string_helper_module = types.ModuleType("cps.string_helper")
    string_helper_module.strip_whitespaces = lambda value: value

    shelfmark_service_module = types.ModuleType("cps.services.shelfmark_search")
    shelfmark_service_module.DEFAULT_SHELFMARK_FILTER_HAS_COVER = True
    shelfmark_service_module.DEFAULT_SHELFMARK_FILTER_REQUESTABLE = True
    shelfmark_service_module.DEFAULT_SHELFMARK_SERIES_FILTER = "all"
    shelfmark_service_module.SHELFMARK_REQUEST_FILTER_OPTIONS = (
        ("requestable", "Requestable only", True),
        ("has_cover", "Has cover", True),
        ("english_only", "English only", True),
        ("hide_owned", "Hide owned books", True),
        ("hide_partial", "Hide partial books", True),
        ("hide_compilations", "Hide compilations / omnibuses / bind-ups", True),
        ("prefer_primary", "Prefer primary editions", True),
        ("hide_audiobook_only", "Hide audiobook-only", True),
        ("suppress_non_book", "Suppress non-book results", True),
        ("next_missing_only", "Next missing only", False),
        ("well_rated_only", "Well rated only", False),
        ("popular_only", "Popular only", False),
        ("new_releases_only", "New releases only", False),
        ("standalone_only", "Standalone only", False),
        ("first_in_series_only", "First in series only", False),
    )
    shelfmark_service_module.ShelfmarkIntegrationError = RuntimeError
    shelfmark_service_module.fetch_shelfmark_detail = lambda *args, **kwargs: None
    shelfmark_service_module.get_shelfmark_preferred_release_settings = lambda: types.SimpleNamespace(to_template_dict=lambda: {})
    shelfmark_service_module.lookup_visible_library_matches = lambda ids: {}
    shelfmark_service_module.normalize_request_filter_state = (
        lambda values=None, **overrides: {
            **{
                key: default
                for key, _label, default in shelfmark_service_module.SHELFMARK_REQUEST_FILTER_OPTIONS
            },
            **(values or {}),
            **{key: value for key, value in overrides.items() if value is not None},
        }
    )
    shelfmark_service_module.result_matches_shelfmark_filters = lambda *args, **kwargs: True
    shelfmark_service_module.search_request_shelfmark_results = lambda *args, **kwargs: types.SimpleNamespace(to_template_dict=lambda: {})
    shelfmark_service_module.search_shelfmark_results = lambda *args, **kwargs: types.SimpleNamespace(to_template_dict=lambda: {})

    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql.expression", sqlalchemy_expression_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql.functions", sqlalchemy_functions_module)
    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.render_template", render_template_module)
    monkeypatch.setitem(sys.modules, "cps.usermanagement", usermanagement_module)
    monkeypatch.setitem(sys.modules, "cps.pagination", pagination_module)
    monkeypatch.setitem(sys.modules, "cps.cw_login", cw_login_module)
    monkeypatch.setitem(sys.modules, "cps.string_helper", string_helper_module)
    monkeypatch.setitem(sys.modules, "cps.services.shelfmark_search", shelfmark_service_module)

    module_name = "cps.search"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._render_calls = render_calls
    return module


def test_render_search_results_keeps_library_search_local(search_module, monkeypatch):
    monkeypatch.setattr(
        search_module,
        "_build_shelfmark_section",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local search should not build Shelfmark results")),
    )

    rendered = search_module.render_search_results("Dune", order=[None, "stored"])

    assert rendered["template"] == "search.html"
    assert rendered["shelfmark_section"] is None
    assert rendered["entries"] == ["entry"]
