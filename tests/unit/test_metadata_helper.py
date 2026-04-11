# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "metadata_helper.py"


def test_fetch_and_apply_metadata_prefers_exact_hardcover_lookup(monkeypatch):
    logger_instance = types.SimpleNamespace(
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )

    book = types.SimpleNamespace(
        id=1,
        title="Mort",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        identifiers=[types.SimpleNamespace(type="hardcover-id", val="379631")],
    )

    class DummyCalibreDB:
        session_factory = object()

        def __init__(self, expire_on_commit=False, init=True):
            self.session = types.SimpleNamespace(close=lambda: None)

        def get_book(self, book_id):
            assert book_id == 1
            return book

    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(
            return_value=[
                types.SimpleNamespace(
                    identifiers={"hardcover-id": "379631", "hardcover-edition": "91234"},
                    title="Mort",
                )
            ]
        ),
    )
    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[]),
    )

    cps_module = types.ModuleType("cps")
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)
    cps_module.db = types.SimpleNamespace(CalibreDB=DummyCalibreDB)

    search_metadata_module = types.ModuleType("cps.search_metadata")
    search_metadata_module.cl = [hardcover_provider, google_provider]

    provenance_module = types.ModuleType("cps.utils.shelfmark_import_provenance")
    provenance_module.select_exact_hardcover_result = lambda results, identifiers: results[0] if results else None
    utils_module = types.ModuleType("cps.utils")

    cwa_db_module = types.ModuleType("cwa_db")

    class DummyCwaDb:
        def get_cwa_settings(self):
            return {
                "auto_metadata_fetch_enabled": True,
                "metadata_provider_hierarchy": '["hardcover","google"]',
                "metadata_providers_enabled": "{}",
            }

    cwa_db_module.CWA_DB = DummyCwaDb

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.search_metadata", search_metadata_module)
    monkeypatch.setitem(sys.modules, "cps.utils", utils_module)
    monkeypatch.setitem(sys.modules, "cps.utils.shelfmark_import_provenance", provenance_module)
    monkeypatch.setitem(sys.modules, "cwa_db", cwa_db_module)

    module_name = "test_metadata_helper_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    hardcover_provider.search.assert_called_once_with("hardcover-id:379631", "", "en")
    google_provider.search.assert_not_called()
    apply_metadata.assert_called_once()
