# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from types import ModuleType, SimpleNamespace
import importlib.util
import pathlib
import sys


def _install_stub(name, attrs=None):
    module = ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(module, key, value)
    sys.modules[name] = module
    return module


def _url_for(endpoint, **kwargs):
    if endpoint == "web.show_book":
        return f"/book/{kwargs['book_id']}"
    if endpoint == "web.books_list":
        return f"/{kwargs['data']}/{kwargs['book_id']}"
    if endpoint == "search.simple_search":
        return f"/search?query={kwargs['query']}"
    raise AssertionError(f"Unexpected endpoint {endpoint}")


def _load_module():
    if "cps.services.search_autocomplete" in sys.modules:
        return sys.modules["cps.services.search_autocomplete"]

    _install_stub("cps")
    _install_stub("cps.calibre_db", {"session": None, "ensure_session": lambda: None, "create_functions": lambda *_args, **_kwargs: None})
    _install_stub("cps.config")
    _install_stub("cps.db")
    _install_stub("cps.services")
    _install_stub("flask", {"url_for": _url_for})
    _install_stub("sqlalchemy", {"case": lambda *args, **kwargs: None, "distinct": lambda value: value, "func": SimpleNamespace(lower=lambda value: value)})
    _install_stub("sqlalchemy.orm", {"joinedload": lambda *args, **kwargs: None})

    module_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "services" / "search_autocomplete.py"
    spec = importlib.util.spec_from_file_location("cps.services.search_autocomplete", module_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps.services"
    sys.modules["cps.services.search_autocomplete"] = module
    spec.loader.exec_module(module)
    return module


def _book(book_id, title, authors=None, series_name=None, series_index=None):
    series = []
    if series_name:
        series.append(SimpleNamespace(name=series_name))
    return SimpleNamespace(
        id=book_id,
        title=title,
        authors=authors or [],
        ordered_authors=authors or [],
        series=series,
        series_index=series_index,
    )


def _author(author_id, name):
    return SimpleNamespace(id=author_id, name=name)


def _series(series_id, name):
    return SimpleNamespace(id=series_id, name=name)


def _labels():
    return {
        "book": "Book",
        "author": "Author",
        "series": "Series",
        "show_all": 'Show all results for "%(query)s"',
        "author_count_singular": "1 book",
        "author_count_plural": "%(count)d books",
        "series_count_singular": "1 book",
        "series_count_plural": "%(count)d books",
    }


def test_book_primary_title_matches_exact_db_title():
    module = _load_module()
    payload = module.build_suggestion_payload(
        "churn",
        [
            _book(
                4,
                "The Churn",
                authors=[_author(2, "James S. A. Corey")],
                series_name="The Expanse",
                series_index=3.5,
            )
        ],
        [],
        [],
        _labels(),
    )

    assert payload["suggestions"][0]["type"] == "book"
    assert payload["suggestions"][0]["primary_text"] == "The Churn"
    assert payload["suggestions"][0]["secondary_text"] == "James S. A. Corey | The Expanse #3.5"


def test_author_and_series_suggestions_route_to_correct_pages():
    module = _load_module()
    payload = module.build_suggestion_payload(
        "exp",
        [],
        [(_author(10, "Expanse Team"), 2)],
        [(_series(11, "The Expanse"), 9)],
        _labels(),
    )

    assert payload["suggestions"][0]["href"] == "/author/10"
    assert payload["suggestions"][1]["href"] == "/series/11"


def test_exact_matches_rank_before_prefix_and_contains():
    module = _load_module()
    payload = module.build_suggestion_payload(
        "expanse",
        [_book(1, "Expanse")],
        [(_author(2, "Expanse Editor"), 1)],
        [(_series(3, "The Expanse Saga"), 8)],
        _labels(),
    )

    ordered = [(item["type"], item["primary_text"]) for item in payload["suggestions"]]
    assert ordered == [
        ("book", "Expanse"),
        ("author", "Expanse Editor"),
        ("series", "The Expanse Saga"),
    ]
    assert [item["match_rank"] for item in payload["suggestions"]] == [0, 1, 2]


def test_contains_matches_sort_after_prefix_matches():
    module = _load_module()
    payload = module.build_suggestion_payload(
        "ring",
        [
            _book(1, "Ringworld"),
            _book(2, "The Ringing City"),
        ],
        [],
        [],
        _labels(),
    )

    assert [item["primary_text"] for item in payload["suggestions"]] == [
        "Ringworld",
        "The Ringing City",
    ]


def test_per_type_cap_prevents_book_flooding():
    module = _load_module()
    books = [_book(index, f"Foundation {index}") for index in range(1, 8)]
    payload = module.build_suggestion_payload(
        "foundation",
        books,
        [(_author(50, "Foundation Writer"), 2)],
        [(_series(60, "Foundation Series"), 7)],
        _labels(),
    )

    assert len([item for item in payload["suggestions"] if item["type"] == "book"]) == 4
    assert any(item["type"] == "author" for item in payload["suggestions"])
    assert any(item["type"] == "series" for item in payload["suggestions"])


def test_show_all_row_is_available_for_query():
    module = _load_module()
    payload = module.build_suggestion_payload("churn", [], [], [], _labels())

    assert payload["suggestions"] == []
    assert payload["show_all"]["href"] == "/search?query=churn"
