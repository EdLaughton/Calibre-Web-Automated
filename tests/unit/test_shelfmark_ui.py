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


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "shelfmark_ui.py"
WEB_MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "web.py"


class _FakeArgs(dict):
    def to_dict(self, flat=True):
        return dict(self)

    def getlist(self, name):
        value = self.get(name)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]


def _fake_url_for(endpoint, **kwargs):
    path = "/" + endpoint.replace(".", "/")
    if not kwargs:
        return path
    query = "&".join(f"{key}={value}" for key, value in sorted(kwargs.items()))
    return f"{path}?{query}"


@pytest.fixture
def shelfmark_ui_module(monkeypatch):
    calls = {}

    class FakeSearchResponse:
        def __init__(self, payload):
            self._payload = payload

        def to_template_dict(self):
            return dict(self._payload)

    def fake_contextual_search(query, **kwargs):
        calls["query"] = query
        calls["kwargs"] = kwargs
        limit = kwargs["limit"]
        all_results = [
            {
                "provider": "hardcover",
                "provider_id": str(index),
                "title": f"Book {index}",
                "cover_url": f"https://covers.example.com/{index}.jpg",
                "already_in_library": False,
                "request_payload": {"book_data": {"provider": "hardcover", "provider_id": str(index)}},
                "action": {"mode": "request"},
                "workflow_state": {"key": "available"},
                "library_state": {"row_class": "info"},
            }
            for index in range(1, 13)
        ]
        return FakeSearchResponse(
            {
                "enabled": True,
                "available": True,
                "results": all_results[:limit],
                "has_more": len(all_results) > limit,
                "page": 1,
                "page_size": limit,
                "page_result_count": min(len(all_results), limit),
                "filter_requestable": True,
                "filter_has_cover": True,
                "preferred_release_settings": {},
                "open_search_url": "https://library.example.com/shelfmark",
            }
        )

    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []
    services_module = types.ModuleType("cps.services")
    services_module.__path__ = []
    shelfmark_search_module = types.ModuleType("cps.services.shelfmark_search")
    shelfmark_search_module.DEFAULT_SHELFMARK_CONTEXTUAL_LIMIT = 8
    shelfmark_search_module.DEFAULT_SHELFMARK_FILTER_HAS_COVER = True
    shelfmark_search_module.DEFAULT_SHELFMARK_FILTER_REQUESTABLE = True
    shelfmark_search_module.DEFAULT_SHELFMARK_SERIES_FILTER = "default"
    shelfmark_search_module.DEFAULT_SHELFMARK_SORT = "relevance"
    shelfmark_search_module.fetch_shelfmark_detail = lambda *args, **kwargs: None
    shelfmark_search_module.get_shelfmark_client_config = lambda: types.SimpleNamespace(enabled=True)
    shelfmark_search_module.get_shelfmark_preferred_release_settings = lambda: types.SimpleNamespace(
        to_template_dict=lambda: {"enabled": False}
    )
    shelfmark_search_module.result_matches_shelfmark_filters = lambda *args, **kwargs: True
    shelfmark_search_module.search_shelfmark_contextual_results = fake_contextual_search
    shelfmark_search_module.search_shelfmark_results = lambda *args, **kwargs: FakeSearchResponse({"enabled": False})

    flask_module = types.ModuleType("flask")
    flask_module.request = types.SimpleNamespace(
        args=_FakeArgs(),
        endpoint="web.books_list",
        view_args={},
        path="/author/stored/1",
    )
    flask_module.url_for = _fake_url_for
    flask_module.render_template = lambda template_name, **kwargs: (
        f"template:{template_name}:"
        f"{kwargs.get('shelfmark_section', {}).get('section_title', '')}:"
        f"{kwargs.get('shelfmark_section', {}).get('section_subtitle', '')}"
    )

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.gettext = lambda value, **kwargs: value % kwargs if kwargs else value

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.services", services_module)
    monkeypatch.setitem(sys.modules, "cps.services.shelfmark_search", shelfmark_search_module)
    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)

    spec = importlib.util.spec_from_file_location("cps.shelfmark_ui_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.shelfmark_ui_test", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._calls = calls
    return module


def test_build_author_contextual_section_page_uses_popularity_and_builds_load_more(shelfmark_ui_module):
    section = shelfmark_ui_module.build_author_contextual_shelfmark_section_page(
        "Terry Pratchett",
        author_id=7,
        state_url="/author/stored/7",
    )

    assert shelfmark_ui_module._calls["query"] == "Terry Pratchett"
    assert shelfmark_ui_module._calls["kwargs"]["sort"] == "popularity"
    assert shelfmark_ui_module._calls["kwargs"]["filter_requestable"] is True
    assert shelfmark_ui_module._calls["kwargs"]["filter_has_cover"] is True
    assert shelfmark_ui_module._calls["kwargs"]["context_type"] == "author"
    assert shelfmark_ui_module._calls["kwargs"]["context_value"] == "Terry Pratchett"
    assert section["section_subtitle"] == "Missing most popular requestable books by this author from Shelfmark"
    assert shelfmark_ui_module._calls["kwargs"]["limit"] == 9
    assert [result["title"] for result in section["results"]] == [f"Book {index}" for index in range(1, 9)]
    assert section["load_more_url"] == "/web/author_shelfmark_section?append=1&author_id=7&offset=8&return_to=/author/stored/7"


def test_build_series_contextual_section_page_slices_follow_on_batch_without_duplicates(shelfmark_ui_module):
    section = shelfmark_ui_module.build_series_contextual_shelfmark_section_page(
        "Discworld",
        series_id=5,
        state_url="/series/stored/5",
        offset=8,
    )

    assert shelfmark_ui_module._calls["kwargs"]["limit"] == 17
    assert [result["title"] for result in section["results"]] == [f"Book {index}" for index in range(9, 13)]
    assert [result["row_index"] for result in section["results"]] == [8, 9, 10, 11]
    assert section["load_more_url"] is None


def test_build_contextual_section_drops_self_looping_load_more_when_no_follow_on_batch(
    shelfmark_ui_module,
    monkeypatch,
):
    class FakeSparseResponse:
        def __init__(self, payload):
            self._payload = payload

        def to_template_dict(self):
            return dict(self._payload)

    sparse_results = [
        {
            "provider": "hardcover",
            "provider_id": str(index),
            "title": f"Book {index}",
            "cover_url": f"https://covers.example.com/{index}.jpg",
            "already_in_library": False,
            "request_payload": {"book_data": {"provider": "hardcover", "provider_id": str(index)}},
            "action": {"mode": "request"},
            "workflow_state": {"key": "available"},
            "library_state": {"row_class": "info"},
        }
        for index in range(1, 25)
    ]

    def fake_sparse_contextual_search(query, **kwargs):
        return FakeSparseResponse(
            {
                "enabled": True,
                "available": True,
                "results": sparse_results,
                "has_more": True,
                "page": 1,
                "page_size": kwargs["limit"],
                "page_result_count": len(sparse_results),
                "filter_requestable": True,
                "filter_has_cover": True,
                "preferred_release_settings": {},
                "open_search_url": "https://library.example.com/shelfmark",
            }
        )

    monkeypatch.setattr(
        shelfmark_ui_module,
        "search_shelfmark_contextual_results",
        fake_sparse_contextual_search,
    )

    section = shelfmark_ui_module.build_author_contextual_shelfmark_section_page(
        "Craig Alanson",
        author_id=373,
        state_url="/author/stored/373",
        offset=24,
    )

    assert section["results"] == []
    assert section["load_more_url"] is None
    assert section["has_more_contextual"] is False


def test_render_contextual_partial_uses_template_renderer(shelfmark_ui_module):
    section = {
        "section_title": "Shelfmark",
        "section_subtitle": "Missing most popular requestable books by this author from Shelfmark",
        "results": [{"title": "Book 1"}],
    }

    rendered = shelfmark_ui_module.render_contextual_shelfmark_partial(section)

    assert rendered == (
        "template:shelfmark_contextual_async_section.html:"
        "Shelfmark:Missing most popular requestable books by this author from Shelfmark"
    )


def test_render_contextual_append_handles_empty_and_unavailable_states(shelfmark_ui_module):
    assert shelfmark_ui_module.render_contextual_shelfmark_append({"available": False}) == ("", 503)
    assert shelfmark_ui_module.render_contextual_shelfmark_append(
        {"available": True, "results": [], "load_more_url": None}
    ) == ("", 200)


def test_web_contextual_endpoints_use_shared_render_helpers():
    source = WEB_MODULE_PATH.read_text(encoding="utf-8")

    assert "return render_contextual_shelfmark_partial(section)" in source
    assert "return render_contextual_shelfmark_append(section)" in source
    assert "_render_contextual_shelfmark_partial" not in source
    assert "_render_contextual_shelfmark_append" not in source
