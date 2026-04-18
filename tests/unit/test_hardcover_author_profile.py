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


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "services" / "hardcover.py"


@pytest.fixture
def hardcover_module(monkeypatch):
    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []
    cps_module.config = types.SimpleNamespace(config_hardcover_token="token")
    cps_module.logger = types.SimpleNamespace(create=lambda: types.SimpleNamespace(warning=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None))

    clean_html_module = types.ModuleType("cps.clean_html")
    clean_html_module.clean_string = lambda value, book_id=0: value

    cw_login_module = types.ModuleType("cps.cw_login")
    cw_login_module.current_user = types.SimpleNamespace(hardcover_token=None)

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.config", cps_module.config)
    monkeypatch.setitem(sys.modules, "cps.logger", cps_module.logger)
    monkeypatch.setitem(sys.modules, "cps.clean_html", clean_html_module)
    monkeypatch.setitem(sys.modules, "cps.cw_login", cw_login_module)

    spec = importlib.util.spec_from_file_location("cps.services.hardcover_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.services.hardcover_test", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_find_author_profile_accepts_string_cached_image(hardcover_module, monkeypatch):
    client = object.__new__(hardcover_module.HardcoverClient)
    monkeypatch.setattr(
        client,
        "_select_author_document",
        lambda author_name: {"id": 37, "name": "Terry Pratchett"},
    )
    monkeypatch.setattr(
        client,
        "get_author_by_id",
        lambda author_id: {
            "id": 37,
            "name": "Terry Pratchett",
            "slug": "terry-pratchett",
            "bio": "<p>Discworld creator.</p>",
            "cached_image": "https://assets.hardcover.app/author/terry.jpg",
        },
    )

    profile = client.find_author_profile("Terry Pratchett")

    assert profile is not None
    assert profile.image_url == "https://assets.hardcover.app/author/terry.jpg"
    assert profile.safe_about == "<p>Discworld creator.</p>"
    assert profile.link == "https://hardcover.app/authors/terry-pratchett"


def test_find_author_profile_accepts_dict_cached_image(hardcover_module, monkeypatch):
    client = object.__new__(hardcover_module.HardcoverClient)
    monkeypatch.setattr(
        client,
        "_select_author_document",
        lambda author_name: {"id": 38, "name": "N. K. Jemisin"},
    )
    monkeypatch.setattr(
        client,
        "get_author_by_id",
        lambda author_id: {
            "id": 38,
            "name": "N. K. Jemisin",
            "slug": "n-k-jemisin",
            "bio": None,
            "cached_image": {"url": "https://assets.hardcover.app/author/jemisin.jpg"},
        },
    )

    profile = client.find_author_profile("N. K. Jemisin")

    assert profile is not None
    assert profile.image_url == "https://assets.hardcover.app/author/jemisin.jpg"
    assert profile.safe_about is None


def test_author_by_id_query_treats_cached_image_as_jsonb_scalar(hardcover_module):
    assert "cached_image" in hardcover_module.AUTHOR_BY_ID_QUERY
    assert "cached_image {" not in hardcover_module.AUTHOR_BY_ID_QUERY
