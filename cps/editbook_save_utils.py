# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, Protocol


class LoggerLike(Protocol):
    def warning(self, msg: str, *args) -> None: ...
    def info(self, msg: str, *args) -> None: ...


def recover_calibre_session(
    *,
    calibre_db_instance: Any,
    logger: LoggerLike,
    book_id: int,
    phase: str,
) -> None:
    session = getattr(calibre_db_instance, "session", None)
    if session is not None:
        try:
            session.rollback()
        except Exception as rollback_error:
            logger.warning(
                "Manual metadata apply rollback failed for book %s during %s: %s",
                book_id,
                phase,
                rollback_error,
            )
        try:
            session.close()
        except Exception as close_error:
            logger.warning(
                "Manual metadata apply session close failed for book %s during %s: %s",
                book_id,
                phase,
                close_error,
            )

    calibre_db_instance.session = None
    try:
        calibre_db_instance.ensure_session()
    except Exception as ensure_error:
        logger.warning(
            "Manual metadata apply session recovery failed for book %s during %s: %s",
            book_id,
            phase,
            ensure_error,
        )


def ensure_calibre_session_ready(
    *,
    calibre_db_instance: Any,
    logger: LoggerLike,
    book_id: int,
    phase: str,
) -> Any:
    calibre_db_instance.ensure_session()
    session = getattr(calibre_db_instance, "session", None)
    if session is None:
        return None

    try:
        transaction = session.get_transaction() if hasattr(session, "get_transaction") else None
    except Exception as transaction_error:
        logger.warning(
            "Manual metadata apply transaction inspection failed for book %s during %s: %s",
            book_id,
            phase,
            transaction_error,
        )
        recover_calibre_session(
            calibre_db_instance=calibre_db_instance,
            logger=logger,
            book_id=book_id,
            phase=phase,
        )
        return getattr(calibre_db_instance, "session", None)

    if transaction is not None and not getattr(transaction, "is_active", True):
        logger.warning(
            "Manual metadata apply found closed transaction for book %s during %s; recreating session",
            book_id,
            phase,
        )
        recover_calibre_session(
            calibre_db_instance=calibre_db_instance,
            logger=logger,
            book_id=book_id,
            phase=phase,
        )
        return getattr(calibre_db_instance, "session", None)

    return session


def build_post_save_location(
    *,
    book_id: int,
    detail_view: bool,
    url_for: Callable[..., str],
) -> str:
    endpoint = "web.show_book" if detail_view else "edit-book.show_edit_book"
    return url_for(endpoint, book_id=book_id)


def load_custom_columns_without_autoflush(
    *,
    session: Any,
    custom_columns_model: Any,
    cc_exceptions: Any,
    column_id: int | None = None,
) -> list[Any]:
    context_manager = session.no_autoflush if hasattr(session, "no_autoflush") else nullcontext()
    with context_manager:
        query = session.query(custom_columns_model).filter(
            custom_columns_model.datatype.notin_(cc_exceptions)
        )
        if column_id is not None:
            query = query.filter(custom_columns_model.id == column_id)
        return query.all()
