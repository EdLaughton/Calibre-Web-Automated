# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

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


def build_post_save_location(
    *,
    book_id: int,
    detail_view: bool,
    url_for: Callable[..., str],
) -> str:
    endpoint = "web.show_book" if detail_view else "edit-book.show_edit_book"
    return url_for(endpoint, book_id=book_id)
