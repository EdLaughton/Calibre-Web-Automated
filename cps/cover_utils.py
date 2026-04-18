from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol


class LoggerLike(Protocol):
    def debug(self, msg: str, *args) -> None: ...
    def info(self, msg: str, *args) -> None: ...
    def warning(self, msg: str, *args) -> None: ...


@dataclass(frozen=True)
class CoverUpdateOutcome:
    applied: bool
    modify_date: bool
    error: str | None = None
    cleared_cover: bool = False
    normalized_cover_url: str | None = None


def normalize_utc_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def is_cached_thumbnail_stale(
    book_last_modified: datetime | None,
    thumbnail_generated_at: datetime | None,
) -> bool:
    normalized_book_modified = normalize_utc_timestamp(book_last_modified)
    normalized_thumbnail_generated = normalize_utc_timestamp(thumbnail_generated_at)
    if normalized_book_modified is None or normalized_thumbnail_generated is None:
        return False
    return normalized_book_modified > normalized_thumbnail_generated


def apply_selected_cover_url(
    *,
    book_id: int,
    book_path: str,
    cover_url: str | None,
    logger: LoggerLike,
    save_cover_from_url: Callable[[str, str], tuple[bool, str | None]],
    refresh_thumbnail_cache: Callable[[int], None],
) -> CoverUpdateOutcome:
    normalized_cover_url = (cover_url or "").strip()
    if not normalized_cover_url:
        logger.debug(
            "Cover update skipped for book %s because no selected cover payload was present",
            book_id,
        )
        return CoverUpdateOutcome(
            applied=False,
            modify_date=False,
            normalized_cover_url=None,
        )

    if normalized_cover_url.endswith("/static/generic_cover.svg"):
        logger.info(
            "Metadata save for book %s: generic cover selected; clearing existing cover flag",
            book_id,
        )
        return CoverUpdateOutcome(
            applied=True,
            modify_date=False,
            cleared_cover=True,
            normalized_cover_url=normalized_cover_url,
        )

    logger.info(
        "Metadata save for book %s: selected provider cover will be applied",
        book_id,
    )
    result, error = save_cover_from_url(normalized_cover_url, book_path)
    if not result:
        logger.warning(
            "Metadata save for book %s: cover write failed error=%s",
            book_id,
            error,
        )
        return CoverUpdateOutcome(
            applied=False,
            modify_date=False,
            error=error,
            normalized_cover_url=normalized_cover_url,
        )

    logger.info("Downloaded provider cover for book %s", book_id)
    logger.info("Wrote updated cover for book %s", book_id)
    refresh_thumbnail_cache(book_id)
    logger.info("Queued cached thumbnail invalidation/regeneration for book %s", book_id)
    return CoverUpdateOutcome(
        applied=True,
        modify_date=True,
        normalized_cover_url=normalized_cover_url,
    )
