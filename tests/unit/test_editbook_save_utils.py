# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "editbook_save_utils.py"


def _load_editbook_save_utils():
    module_name = "test_editbook_save_utils_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


editbook_save_utils = _load_editbook_save_utils()


def test_build_post_save_location_defaults_to_edit_page():
    url_for = mock.Mock(return_value="/admin/book/1121")

    location = editbook_save_utils.build_post_save_location(
        book_id=1121,
        detail_view=False,
        url_for=url_for,
    )

    assert location == "/admin/book/1121"
    url_for.assert_called_once_with("edit-book.show_edit_book", book_id=1121)


def test_build_post_save_location_uses_detail_view_target_when_requested():
    url_for = mock.Mock(return_value="/book/1121")

    location = editbook_save_utils.build_post_save_location(
        book_id=1121,
        detail_view=True,
        url_for=url_for,
    )

    assert location == "/book/1121"
    url_for.assert_called_once_with("web.show_book", book_id=1121)


def test_recover_calibre_session_resets_closed_transaction_and_recreates_session():
    logger = mock.Mock()
    session = mock.Mock()
    calibre_db_instance = mock.Mock()
    calibre_db_instance.session = session

    editbook_save_utils.recover_calibre_session(
        calibre_db_instance=calibre_db_instance,
        logger=logger,
        book_id=1121,
        phase="response redirect",
    )

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    calibre_db_instance.ensure_session.assert_called_once_with()
    logger.warning.assert_not_called()


def test_recover_calibre_session_tolerates_rollback_failure_and_still_recovers():
    logger = mock.Mock()
    session = mock.Mock()
    session.rollback.side_effect = RuntimeError("This transaction is closed")
    calibre_db_instance = mock.Mock()
    calibre_db_instance.session = session

    editbook_save_utils.recover_calibre_session(
        calibre_db_instance=calibre_db_instance,
        logger=logger,
        book_id=1121,
        phase="response redirect",
    )

    session.close.assert_called_once_with()
    calibre_db_instance.ensure_session.assert_called_once_with()
    logger.warning.assert_any_call(
        "Manual metadata apply rollback failed for book %s during %s: %s",
        1121,
        "response redirect",
        session.rollback.side_effect,
    )
