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


def test_load_custom_columns_without_autoflush_uses_no_autoflush_context():
    datatype_field = mock.Mock()
    datatype_field.notin_.return_value = "datatype-filter"
    id_field = mock.Mock()

    custom_columns_model = mock.Mock()
    custom_columns_model.datatype = datatype_field
    custom_columns_model.id = id_field

    query = mock.Mock()
    query.filter.return_value = query
    query.all.return_value = ["custom-column"]

    session = mock.Mock()
    session.query.return_value = query
    session.no_autoflush = mock.MagicMock()

    result = editbook_save_utils.load_custom_columns_without_autoflush(
        session=session,
        custom_columns_model=custom_columns_model,
        cc_exceptions=("comments",),
        column_id=7,
    )

    assert result == ["custom-column"]
    session.no_autoflush.__enter__.assert_called_once_with()
    session.no_autoflush.__exit__.assert_called_once()
    session.query.assert_called_once_with(custom_columns_model)
    assert query.filter.call_count == 2


def test_ensure_calibre_session_ready_keeps_active_transaction():
    logger = mock.Mock()
    transaction = mock.Mock(is_active=True)
    session = mock.Mock()
    session.get_transaction.return_value = transaction

    calibre_db_instance = mock.Mock()
    calibre_db_instance.session = session

    result = editbook_save_utils.ensure_calibre_session_ready(
        calibre_db_instance=calibre_db_instance,
        logger=logger,
        book_id=1121,
        phase="request start",
    )

    assert result is session
    calibre_db_instance.ensure_session.assert_called_once_with()
    logger.warning.assert_not_called()


def test_ensure_calibre_session_ready_recovers_closed_transaction():
    logger = mock.Mock()
    transaction = mock.Mock(is_active=False)
    session = mock.Mock()
    session.get_transaction.return_value = transaction

    recovered_session = mock.Mock()
    calibre_db_instance = mock.Mock()
    calibre_db_instance.session = session

    call_count = {"value": 0}

    def _ensure_session():
        call_count["value"] += 1
        if call_count["value"] == 2:
            calibre_db_instance.session = recovered_session

    calibre_db_instance.ensure_session.side_effect = _ensure_session

    result = editbook_save_utils.ensure_calibre_session_ready(
        calibre_db_instance=calibre_db_instance,
        logger=logger,
        book_id=1121,
        phase="request start",
    )

    assert result is recovered_session
    assert calibre_db_instance.ensure_session.call_count == 2
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    logger.warning.assert_any_call(
        "Manual metadata apply found closed transaction for book %s during %s; recreating session",
        1121,
        "request start",
    )
