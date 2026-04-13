# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import sys
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "cover_utils.py"


def _load_cover_utils_module():
    module_name = "test_cover_utils_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cover_utils = _load_cover_utils_module()


def _make_logger():
    return mock.Mock(debug=mock.Mock(), info=mock.Mock(), warning=mock.Mock())


def test_apply_selected_cover_url_writes_cover_and_refreshes_cache():
    logger = _make_logger()
    save_cover_from_url = mock.Mock(return_value=(True, None))
    refresh_thumbnail_cache = mock.Mock()

    outcome = cover_utils.apply_selected_cover_url(
        book_id=1116,
        book_path="Pratchett/Night Watch (1116)",
        cover_url="https://covers.example/night-watch.jpg",
        logger=logger,
        save_cover_from_url=save_cover_from_url,
        refresh_thumbnail_cache=refresh_thumbnail_cache,
    )

    assert outcome.applied is True
    assert outcome.modify_date is True
    assert outcome.error is None
    assert outcome.cleared_cover is False
    save_cover_from_url.assert_called_once_with(
        "https://covers.example/night-watch.jpg",
        "Pratchett/Night Watch (1116)",
    )
    refresh_thumbnail_cache.assert_called_once_with(1116)
    logger.info.assert_any_call(
        "Metadata save for book %s: selected provider cover will be applied",
        1116,
    )
    logger.info.assert_any_call("Downloaded provider cover for book %s", 1116)
    logger.info.assert_any_call("Wrote updated cover for book %s", 1116)
    logger.info.assert_any_call(
        "Queued cached thumbnail invalidation/regeneration for book %s",
        1116,
    )


def test_apply_selected_cover_url_skips_when_no_cover_payload_present():
    logger = _make_logger()
    save_cover_from_url = mock.Mock()
    refresh_thumbnail_cache = mock.Mock()

    outcome = cover_utils.apply_selected_cover_url(
        book_id=1116,
        book_path="Pratchett/Night Watch (1116)",
        cover_url="   ",
        logger=logger,
        save_cover_from_url=save_cover_from_url,
        refresh_thumbnail_cache=refresh_thumbnail_cache,
    )

    assert outcome.applied is False
    assert outcome.modify_date is False
    assert outcome.error is None
    save_cover_from_url.assert_not_called()
    refresh_thumbnail_cache.assert_not_called()
    logger.debug.assert_called_once_with(
        "Cover update skipped for book %s because no selected cover payload was present",
        1116,
    )


def test_apply_selected_cover_url_keeps_generic_cover_clear_path():
    logger = _make_logger()
    save_cover_from_url = mock.Mock()
    refresh_thumbnail_cache = mock.Mock()

    outcome = cover_utils.apply_selected_cover_url(
        book_id=1116,
        book_path="Pratchett/Night Watch (1116)",
        cover_url="https://library.example/static/generic_cover.svg",
        logger=logger,
        save_cover_from_url=save_cover_from_url,
        refresh_thumbnail_cache=refresh_thumbnail_cache,
    )

    assert outcome.applied is True
    assert outcome.modify_date is False
    assert outcome.cleared_cover is True
    save_cover_from_url.assert_not_called()
    refresh_thumbnail_cache.assert_not_called()


def test_apply_selected_cover_url_returns_error_without_refresh_on_failure():
    logger = _make_logger()
    save_cover_from_url = mock.Mock(return_value=(False, "Error Downloading Cover"))
    refresh_thumbnail_cache = mock.Mock()

    outcome = cover_utils.apply_selected_cover_url(
        book_id=1116,
        book_path="Pratchett/Night Watch (1116)",
        cover_url="https://covers.example/night-watch.jpg",
        logger=logger,
        save_cover_from_url=save_cover_from_url,
        refresh_thumbnail_cache=refresh_thumbnail_cache,
    )

    assert outcome.applied is False
    assert outcome.modify_date is False
    assert outcome.error == "Error Downloading Cover"
    refresh_thumbnail_cache.assert_not_called()
    logger.warning.assert_called_once_with(
        "Metadata save for book %s: cover write failed error=%s",
        1116,
        "Error Downloading Cover",
    )


def test_is_cached_thumbnail_stale_detects_outdated_thumbnail():
    book_last_modified = datetime(2026, 4, 13, 15, 30, tzinfo=timezone.utc)
    thumbnail_generated_at = book_last_modified - timedelta(minutes=5)

    assert cover_utils.is_cached_thumbnail_stale(book_last_modified, thumbnail_generated_at) is True


def test_is_cached_thumbnail_stale_ignores_missing_or_newer_thumbnail():
    book_last_modified = datetime(2026, 4, 13, 15, 30, tzinfo=timezone.utc)

    assert cover_utils.is_cached_thumbnail_stale(book_last_modified, None) is False
    assert cover_utils.is_cached_thumbnail_stale(
        book_last_modified,
        book_last_modified + timedelta(minutes=5),
    ) is False
