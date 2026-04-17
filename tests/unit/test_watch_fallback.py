# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "watch_fallback.py"


def _load_watch_fallback_module():
    module_name = "test_watch_fallback_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


watch_fallback = _load_watch_fallback_module()


def test_iter_files_skips_appledouble_and_sidecar_manifests(tmp_path):
    real_book = tmp_path / "Equal Rites.epub"
    appledouble = tmp_path / "._Equal Rites.epub"
    sidecar = tmp_path / "Equal Rites.epub.cwa.json"
    failed_sidecar = tmp_path / "Equal Rites.epub.cwa.failed.json"

    real_book.write_text("book", encoding="utf-8")
    appledouble.write_text("junk", encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")
    failed_sidecar.write_text("{}", encoding="utf-8")

    discovered = list(
        watch_fallback.iter_files(
            str(tmp_path),
            recursive=True,
            extensions=None,
            ignore_prefixes=("._",),
            ignore_suffixes=(".cwa.json", ".cwa.failed.json"),
        )
    )

    assert str(real_book) in discovered
    assert str(appledouble) not in discovered
    assert str(sidecar) not in discovered
    assert str(failed_sidecar) not in discovered


def test_iter_files_respects_extension_filter_after_ignore_rules(tmp_path):
    epub_path = tmp_path / "The Truth.epub"
    mobi_path = tmp_path / "The Truth.mobi"
    txt_path = tmp_path / "notes.txt"

    epub_path.write_text("epub", encoding="utf-8")
    mobi_path.write_text("mobi", encoding="utf-8")
    txt_path.write_text("notes", encoding="utf-8")

    discovered = list(
        watch_fallback.iter_files(
            str(tmp_path),
            recursive=True,
            extensions={"epub", "mobi"},
            ignore_prefixes=("._",),
            ignore_suffixes=(".cwa.json", ".cwa.failed.json"),
        )
    )

    assert str(epub_path) in discovered
    assert str(mobi_path) in discovered
    assert str(txt_path) not in discovered
