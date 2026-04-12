# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "cps"
    / "utils"
    / "shelfmark_import_provenance.py"
)


def _load_module():
    module_name = "test_shelfmark_import_provenance_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_import_manifest_identifiers_prefers_explicit_provenance():
    module = _load_module()
    manifest = {
        "identifiers": {
            "isbn": "9780552131063",
            "hardcover-id": "379631",
        },
        "provenance": {
            "provider": "hardcover",
            "provider_id": "379631",
            "hardcover_edition": "91234",
            "identifiers": [
                {"type": "hardcover-slug", "value": "mort"},
                "hardcover-edition:91234",
            ],
        },
    }

    assert module.extract_import_manifest_identifiers(manifest) == [
        "isbn:9780552131063",
        "hardcover-id:379631",
        "hardcover-edition:91234",
        "hardcover-slug:mort",
    ]


def test_select_exact_hardcover_result_prefers_matching_edition():
    module = _load_module()
    exact_result = SimpleNamespace(
        identifiers={"hardcover-id": "379631", "hardcover-edition": "91234"},
        title="Mort",
    )
    other_result = SimpleNamespace(
        identifiers={"hardcover-id": "379631", "hardcover-edition": "99999"},
        title="Mort (Other Edition)",
    )

    selected = module.select_exact_hardcover_result(
        [other_result, exact_result],
        {"hardcover-id": "379631", "hardcover-edition": "91234"},
    )

    assert selected is exact_result


def test_select_exact_hardcover_result_prefers_matching_slug_when_edition_missing():
    module = _load_module()
    slug_match = SimpleNamespace(
        identifiers={"hardcover-id": "379631", "hardcover-slug": "mort"},
        title="Mort",
    )
    other_result = SimpleNamespace(
        identifiers={"hardcover-id": "379631", "hardcover-slug": "mort-collector-edition"},
        title="Mort (Collector's Edition)",
    )

    selected = module.select_exact_hardcover_result(
        [other_result, slug_match],
        {"hardcover-id": "379631", "hardcover-slug": "mort"},
    )

    assert selected is slug_match


def test_select_exact_hardcover_result_returns_none_without_matching_book_id():
    module = _load_module()
    unrelated_result = SimpleNamespace(
        identifiers={"hardcover-id": "999999", "hardcover-slug": "other-book"},
        title="Other Book",
    )

    selected = module.select_exact_hardcover_result(
        [unrelated_result],
        {"hardcover-id": "379631"},
    )

    assert selected is None


def test_summarize_import_manifest_identifiers_surfaces_hardcover_fields():
    module = _load_module()

    summary = module.summarize_import_manifest_identifiers(
        [
            "isbn:9780552131063",
            "hardcover-id:379631",
            "hardcover-edition:91234",
            "hardcover-slug:mort",
        ]
    )

    assert summary == "hardcover-id=379631, hardcover-edition=91234, hardcover-slug=mort"
