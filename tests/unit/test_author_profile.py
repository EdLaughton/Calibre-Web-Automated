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


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "author_profile.py"


@pytest.fixture
def author_profile_module(monkeypatch):
    logger_module = types.ModuleType("cps.logger")
    logger_module.create = lambda: types.SimpleNamespace(warning=lambda *args, **kwargs: None)

    hardcover_module = types.SimpleNamespace(
        get_author_profile=lambda author_name: None,
        get_author_profile_by_id=lambda author_id: None,
        get_hardcover_client=lambda load_privacy=False: None,
    )
    goodreads_module = types.SimpleNamespace(get_author_info=lambda author_name: None)
    services_module = types.ModuleType("cps.services")
    services_module.hardcover = hardcover_module
    services_module.goodreads_support = goodreads_module

    cps_module = types.ModuleType("cps")
    cps_module.__path__ = []

    flask_babel_module = types.ModuleType("flask_babel")
    flask_babel_module.gettext = lambda value, **kwargs: value % kwargs if kwargs else value

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.logger", logger_module)
    monkeypatch.setitem(sys.modules, "cps.services", services_module)
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel_module)

    spec = importlib.util.spec_from_file_location("cps.author_profile_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.author_profile_test", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, hardcover_module, goodreads_module


def test_build_author_profile_prefers_hardcover_when_available(author_profile_module):
    module, hardcover_module, goodreads_module = author_profile_module
    hardcover_module.get_author_profile = lambda author_name: types.SimpleNamespace(
        name=author_name,
        image_url="https://assets.hardcover.app/author/profile.jpg",
        safe_about="<p>Discworld creator.</p>",
        link="https://hardcover.app/authors/terry-pratchett",
    )
    goodreads_module.get_author_info = lambda author_name: types.SimpleNamespace(
        name=author_name,
        image_url="https://images.gr-assets.com/profile.jpg",
        safe_about="<p>Fallback bio.</p>",
        link="https://goodreads.com/author/show/123",
    )

    profile = module.build_author_profile("Terry Pratchett")

    assert profile is not None
    assert profile.source_label == "Hardcover"
    assert profile.image_url == "https://assets.hardcover.app/author/profile.jpg"
    assert profile.safe_about == "<p>Discworld creator.</p>"


def test_build_author_profile_falls_back_to_goodreads_when_hardcover_has_nothing(author_profile_module):
    module, hardcover_module, goodreads_module = author_profile_module
    hardcover_module.get_author_profile = lambda author_name: types.SimpleNamespace(
        name=author_name,
        image_url=None,
        safe_about=None,
        link="https://hardcover.app/authors/terry-pratchett",
    )
    goodreads_module.get_author_info = lambda author_name: types.SimpleNamespace(
        name=author_name,
        image_url="https://images.gr-assets.com/profile.jpg",
        safe_about="<p>Fallback bio.</p>",
        link="https://goodreads.com/author/show/123",
    )

    profile = module.build_author_profile("Terry Pratchett")

    assert profile is not None
    assert profile.source_label == "Goodreads"
    assert profile.image_url == "https://images.gr-assets.com/profile.jpg"
    assert profile.safe_about == "<p>Fallback bio.</p>"


def test_build_author_profile_tries_display_order_variant_for_hardcover(author_profile_module):
    module, hardcover_module, goodreads_module = author_profile_module
    seen = []

    def fake_lookup(author_name):
        seen.append(author_name)
        if author_name == "Terry Pratchett":
            return types.SimpleNamespace(
                name=author_name,
                image_url="https://assets.hardcover.app/author/profile.jpg",
                safe_about="<p>Discworld creator.</p>",
                link="https://hardcover.app/authors/terry-pratchett",
            )
        return None

    hardcover_module.get_author_profile = fake_lookup
    goodreads_module.get_author_info = lambda author_name: None

    profile = module.build_author_profile("Pratchett, Terry")

    assert profile is not None
    assert profile.source_label == "Hardcover"
    assert profile.name == "Terry Pratchett"
    assert seen == ["Pratchett, Terry", "Terry Pratchett"]


def test_build_author_profile_prefers_local_book_hardcover_ids_to_resolve_author(author_profile_module):
    module, hardcover_module, goodreads_module = author_profile_module

    class DummyIdentifier:
        def __init__(self, type_name, value):
            self.type = type_name
            self.val = value

    class DummyBook:
        def __init__(self, identifiers):
            self.identifiers = identifiers

    hardcover_module.get_hardcover_client = lambda load_privacy=False: types.SimpleNamespace(
        list_books_by_ids=lambda ids: [
            {
                "id": 101,
                "title": "Mort",
                "contributions": [
                    {"author": {"id": 37, "name": "Terry Pratchett"}},
                ],
            }
        ]
    )
    hardcover_module.get_author_profile_by_id = lambda author_id: types.SimpleNamespace(
        name="Terry Pratchett",
        image_url="https://assets.hardcover.app/author/profile.jpg",
        safe_about="<p>Discworld creator.</p>",
        link="https://hardcover.app/authors/terry-pratchett",
    )
    hardcover_module.get_author_profile = lambda author_name: None
    goodreads_module.get_author_info = lambda author_name: None

    profile = module.build_author_profile(
        "Pratchett, Terry",
        library_books=[
            DummyBook([DummyIdentifier("hardcover-id", "101")]),
            DummyBook([DummyIdentifier("isbn", "9780552138901")]),
        ],
    )

    assert profile is not None
    assert profile.source_label == "Hardcover"
    assert profile.name == "Terry Pratchett"
    assert profile.image_url == "https://assets.hardcover.app/author/profile.jpg"
