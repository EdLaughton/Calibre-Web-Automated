# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json

from cps.utils.shelfmark_import_provenance import (
    build_calibredb_identifier_args,
    extract_import_manifest_identifiers,
    finalize_import_manifest,
    load_import_manifest,
    summarize_import_manifest_identifiers,
)


def test_extract_import_manifest_identifiers_preserves_stable_provenance():
    manifest = {
        "identifiers": {"isbn": "9780441172719"},
        "provenance": {
            "provider": "hardcover",
            "provider_id": "123",
            "hardcover_slug": "dune",
            "hardcover_edition": "456",
            "identifiers": [{"type": "asin", "value": "B001"}],
        },
    }

    identifiers = extract_import_manifest_identifiers(manifest)

    assert identifiers == [
        "isbn:9780441172719",
        "hardcover-id:123",
        "hardcover-slug:dune",
        "hardcover-edition:456",
        "asin:B001",
    ]
    assert summarize_import_manifest_identifiers(identifiers) == (
        "hardcover-id=123, hardcover-slug=dune, hardcover-edition=456"
    )


def test_build_calibredb_identifier_args_filters_invalid_values():
    args = build_calibredb_identifier_args(
        ["hardcover-id:123", "bad-value", "", "isbn:9780441172719"]
    )

    assert args == [
        "--identifier",
        "hardcover-id:123",
        "--identifier",
        "isbn:9780441172719",
    ]


def test_load_and_finalize_import_manifest_scope_the_correct_sidecar(tmp_path):
    manifest_path = tmp_path / "dune.epub.cwa.json"
    manifest_path.write_text(
        json.dumps({"provenance": {"provider": "hardcover", "provider_id": "123"}}),
        encoding="utf-8",
    )

    manifest = load_import_manifest(str(manifest_path))
    failed_manifest_path = finalize_import_manifest(str(manifest_path), success=False)

    assert manifest == {"provenance": {"provider": "hardcover", "provider_id": "123"}}
    assert failed_manifest_path == str(tmp_path / "dune.epub.cwa.failed.json")
    assert not manifest_path.exists()
    assert (tmp_path / "dune.epub.cwa.failed.json").exists()


def test_finalize_import_manifest_removes_successful_sidecar(tmp_path):
    manifest_path = tmp_path / "left-hand.epub.cwa.json"
    manifest_path.write_text("{}", encoding="utf-8")

    failed_manifest_path = finalize_import_manifest(str(manifest_path), success=True)

    assert failed_manifest_path is None
    assert not manifest_path.exists()
