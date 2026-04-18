# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from time import monotonic
from typing import Any

from flask import url_for
from flask_babel import gettext as _

from cps import logger
from cps.metadata_provider.hardcover import Hardcover

from .shelfmark_client import ShelfmarkClient, ShelfmarkClientConfig
from .shelfmark_queue import load_queue_rows_for_items
from .shelfmark_search import LibraryMatch, build_request_payload, find_library_matches

log = logger.create()

_DETAIL_CACHE: OrderedDict[tuple[str, str], tuple[float, dict[str, Any], HardcoverOverlay | None]] = OrderedDict()
_DETAIL_CACHE_TTL_SECONDS = 300
_DETAIL_CACHE_MAX_ENTRIES = 128


@dataclass(frozen=True)
class HardcoverOverlay:
    hardcover_id: str
    series: str
    series_index: float | int | None
    published_date: str
    publisher: str
    language: str
    tags: tuple[str, ...]
    description: str
    cover_url: str
    source_url: str
    rating: float | int | None = None
    ratings_count: int | None = None
    readers_count: int | None = None
    pages: int | None = None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"[^0-9Xx]", "", _normalize_text(value)).upper()


def _normalize_for_match(value: Any) -> str:
    text = _normalize_text(value).replace("|", ",")
    text = re.sub(r"[\W_]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _published_year(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    match = re.search(r"(\d{4})", text)
    return match.group(1) if match else text


def _description_plain_text(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _provider_display_name(value: Any) -> str:
    provider = _normalize_text(value).replace("_", " ").replace("-", " ")
    if not provider:
        return ""
    return provider if any(char.isupper() for char in provider) else provider.title()


def _normalize_numeric(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = _normalize_text(value).replace(",", "")
    if not text:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return None


def _extract_numeric(payload: Mapping[str, Any], *keys: str) -> float | int | None:
    for key in keys:
        if key in payload:
            numeric = _normalize_numeric(payload.get(key))
            if numeric is not None:
                return numeric
    return None


def _cache_get(provider: str, provider_id: str) -> tuple[dict[str, Any], HardcoverOverlay | None] | None:
    key = (provider, provider_id)
    cached = _DETAIL_CACHE.get(key)
    if cached is None:
        return None
    cached_at, value, hardcover_overlay = cached
    if monotonic() - cached_at > _DETAIL_CACHE_TTL_SECONDS:
        _DETAIL_CACHE.pop(key, None)
        return None
    _DETAIL_CACHE.move_to_end(key)
    return dict(value), hardcover_overlay


def _cache_set(
    provider: str,
    provider_id: str,
    *,
    detail_payload: Mapping[str, Any],
    hardcover_overlay: HardcoverOverlay | None,
) -> None:
    key = (provider, provider_id)
    _DETAIL_CACHE[key] = (monotonic(), dict(detail_payload), hardcover_overlay)
    _DETAIL_CACHE.move_to_end(key)
    while len(_DETAIL_CACHE) > _DETAIL_CACHE_MAX_ENTRIES:
        _DETAIL_CACHE.popitem(last=False)


def _hardcover_overlay_from_record(result: Any, *, fallback_id: str = "") -> HardcoverOverlay:
    tags = tuple(value for value in getattr(result, "tags", []) if _normalize_text(value))
    languages = getattr(result, "languages", []) or []
    identifiers = getattr(result, "identifiers", {}) if hasattr(result, "identifiers") else {}
    return HardcoverOverlay(
        hardcover_id=_normalize_text(identifiers.get("hardcover-id") if isinstance(identifiers, Mapping) else "") or fallback_id,
        series=_normalize_text(getattr(result, "series", "")),
        series_index=getattr(result, "series_index", None),
        published_date=_normalize_text(getattr(result, "publishedDate", "")),
        publisher=_normalize_text(getattr(result, "publisher", "")),
        language=_normalize_text(languages[0] if languages else ""),
        tags=tags,
        description=_description_plain_text(getattr(result, "description", "")),
        cover_url=_normalize_text(getattr(result, "cover", "")),
        source_url=_normalize_text(getattr(result, "url", "")),
        rating=getattr(result, "rating", None) or getattr(result, "average_rating", None),
        ratings_count=(
            _normalize_numeric(getattr(result, "ratings_count", None))
            or _normalize_numeric(getattr(result, "ratingsCount", None))
            or _normalize_numeric(getattr(result, "ratings", None))
        ),
        readers_count=(
            _normalize_numeric(getattr(result, "readers_count", None))
            or _normalize_numeric(getattr(result, "readersCount", None))
            or _normalize_numeric(getattr(result, "readers", None))
            or _normalize_numeric(getattr(result, "users_count", None))
        ),
        pages=_normalize_numeric(getattr(result, "pages", None)),
    )


def _match_hardcover_search_result(detail_payload: Mapping[str, Any], results: Sequence[Any]) -> HardcoverOverlay | None:
    if not results:
        return None

    hardcover_id = _normalize_text(detail_payload.get("hardcover_id"))
    isbn = (
        _normalize_identifier(detail_payload.get("isbn"))
        or _normalize_identifier(detail_payload.get("isbn_13"))
        or _normalize_identifier(detail_payload.get("isbn_10"))
    )
    authors = detail_payload.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(detail_payload.get("author"))] if _normalize_text(detail_payload.get("author")) else []
    expected_author = _normalize_for_match(authors[0] if authors else "")
    expected_title = _normalize_for_match(detail_payload.get("title"))

    for result in results:
        identifiers = getattr(result, "identifiers", {}) if hasattr(result, "identifiers") else {}
        candidate_hardcover_id = _normalize_text(identifiers.get("hardcover-id") if isinstance(identifiers, Mapping) else "")
        if hardcover_id and candidate_hardcover_id == hardcover_id:
            return _hardcover_overlay_from_record(result, fallback_id=hardcover_id)
    for result in results:
        identifiers = getattr(result, "identifiers", {}) if hasattr(result, "identifiers") else {}
        candidate_isbn = _normalize_identifier(identifiers.get("isbn") if isinstance(identifiers, Mapping) else "")
        if isbn and candidate_isbn == isbn:
            return _hardcover_overlay_from_record(result, fallback_id=hardcover_id)
    for result in results:
        if _normalize_for_match(getattr(result, "title", "")) != expected_title:
            continue
        candidate_authors = getattr(result, "authors", []) or []
        candidate_author = _normalize_for_match(candidate_authors[0] if candidate_authors else "")
        if expected_author and candidate_author and candidate_author != expected_author:
            continue
        return _hardcover_overlay_from_record(result, fallback_id=hardcover_id)
    return None


def _build_hardcover_overlay(
    detail_payload: Mapping[str, Any],
    provider: str,
    provider_id: str,
) -> HardcoverOverlay | None:
    hardcover_id = _normalize_text(detail_payload.get("hardcover_id"))
    if not hardcover_id and provider == "hardcover":
        hardcover_id = provider_id

    if hardcover_id:
        try:
            results = Hardcover().search(f"hardcover-id:{hardcover_id}")
        except Exception as exc:
            log.debug("Hardcover overlay enrichment failed for %s: %s", hardcover_id, exc)
            results = []
        if results:
            return _hardcover_overlay_from_record(results[0], fallback_id=hardcover_id)

    title = _normalize_text(detail_payload.get("title"))
    authors = detail_payload.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(detail_payload.get("author"))] if _normalize_text(detail_payload.get("author")) else []
    authors = [_normalize_text(author) for author in authors if _normalize_text(author)]
    if not title:
        return None

    query = " ".join(part for part in (title, authors[0] if authors else "") if part)
    try:
        results = Hardcover().search(query)
    except Exception as exc:
        log.debug("Hardcover overlay enrichment failed for %s/%s: %s", provider, provider_id, exc)
        return None
    return _match_hardcover_search_result(detail_payload, results or [])


def _detail_status_badges(library_match: LibraryMatch | None, queue_summary: Any) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    if queue_summary and queue_summary.imported_book_id:
        badges.append({"label": _("Imported"), "class": "label label-success"})
    elif library_match:
        badges.append({"label": _("In library"), "class": "label label-success"})

    if queue_summary and not queue_summary.imported_book_id:
        if queue_summary.status in {"failed", "cancelled", "rejected"}:
            badges.append({"label": _("Retry available"), "class": "label label-warning"})
        elif queue_summary.status in {"downloading", "complete", "importing"}:
            badges.append({"label": queue_summary.label, "class": "label label-info"})
        elif queue_summary.status not in {"failed", "cancelled", "rejected"}:
            badges.append({"label": queue_summary.label, "class": "label label-default"})
    return badges


def _normalize_series_memberships(
    detail_payload: Mapping[str, Any],
    hardcover_overlay: HardcoverOverlay | None,
) -> tuple[dict[str, Any], ...]:
    memberships: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add_membership(
        *,
        name: Any,
        position: Any = None,
        count: Any = None,
        url: Any = None,
        display: Any = None,
    ) -> None:
        series_name = _normalize_text(name)
        if not series_name:
            return
        position_text = _normalize_text(position)
        series_url = _normalize_text(url)
        display_text = _normalize_text(display) or series_name
        if position_text and f"#{position_text}" not in display_text:
            display_text = f"{display_text} #{position_text}"
        series_count = _normalize_numeric(count)
        detail_text = (
            _("%(count)s books", count=f"{int(series_count):,}")
            if series_count
            else ""
        )
        dedupe_key = (series_name.lower(), position_text, series_url)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        memberships.append(
            {
                "name": series_name,
                "display": display_text,
                "position": position_text,
                "count": int(series_count) if series_count else None,
                "detail": detail_text,
                "url": series_url,
            }
        )

    for key in ("series_memberships", "series_entries", "series"):
        raw_value = detail_payload.get(key)
        if not isinstance(raw_value, Sequence) or isinstance(raw_value, (str, bytes)):
            continue
        for item in raw_value:
            if isinstance(item, Mapping):
                nested_series = item.get("series") if isinstance(item.get("series"), Mapping) else {}
                _add_membership(
                    name=(
                        item.get("name")
                        or item.get("series_name")
                        or item.get("display")
                        or nested_series.get("name")
                        or nested_series.get("title")
                    ),
                    position=(
                        item.get("position")
                        or item.get("series_position")
                        or item.get("index")
                        or item.get("number")
                    ),
                    count=item.get("count") or item.get("series_count") or item.get("size"),
                    url=item.get("url") or item.get("series_url") or nested_series.get("url"),
                    display=item.get("display"),
                )
            else:
                _add_membership(name=item)

    if not memberships:
        _add_membership(
            name=_normalize_text(detail_payload.get("series_name")) or (hardcover_overlay.series if hardcover_overlay else ""),
            position=detail_payload.get("series_position") if detail_payload.get("series_position") not in ("", None) else (hardcover_overlay.series_index if hardcover_overlay else None),
            count=detail_payload.get("series_count"),
            url=detail_payload.get("series_url"),
        )

    return tuple(memberships)


def _build_detail_stats(
    detail_payload: Mapping[str, Any],
    hardcover_overlay: HardcoverOverlay | None,
) -> tuple[dict[str, str], ...]:
    stats: list[dict[str, str]] = []

    rating = _extract_numeric(detail_payload, "rating", "average_rating") or (hardcover_overlay.rating if hardcover_overlay else None)
    if rating is not None:
        stats.append({"label": _("Rating"), "value": f"{float(rating):.1f}"})

    ratings_count = _extract_numeric(detail_payload, "ratings_count", "ratingsCount", "ratings") or (hardcover_overlay.ratings_count if hardcover_overlay else None)
    if ratings_count is not None:
        stats.append({"label": _("Ratings"), "value": f"{int(ratings_count):,}"})

    readers_count = (
        _extract_numeric(detail_payload, "readers_count", "readersCount", "readers", "users_count")
        or (hardcover_overlay.readers_count if hardcover_overlay else None)
    )
    if readers_count is not None:
        stats.append({"label": _("Readers"), "value": f"{int(readers_count):,}"})

    pages = _extract_numeric(detail_payload, "pages", "page_count") or (hardcover_overlay.pages if hardcover_overlay else None)
    if pages is not None:
        stats.append({"label": _("Pages"), "value": f"{int(pages):,}"})

    return tuple(stats)


def get_shelfmark_detail_view(
    config_data: ShelfmarkClientConfig,
    provider: str,
    provider_id: str,
) -> dict[str, Any]:
    cached = _cache_get(provider, provider_id)
    if cached is not None:
        detail_payload, hardcover_overlay = cached
    else:
        client = ShelfmarkClient(config_data)
        detail_payload = dict(client.fetch_book(provider, provider_id))
        authors = detail_payload.get("authors")
        if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
            authors = [_normalize_text(detail_payload.get("author"))] if _normalize_text(detail_payload.get("author")) else []
        authors = [_normalize_text(author) for author in authors if _normalize_text(author)]
        detail_payload["authors"] = authors
        hardcover_overlay = _build_hardcover_overlay(detail_payload, provider, provider_id)
        _cache_set(
            provider,
            provider_id,
            detail_payload=detail_payload,
            hardcover_overlay=hardcover_overlay,
        )

    authors = detail_payload.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(detail_payload.get("author"))] if _normalize_text(detail_payload.get("author")) else []
    authors = [_normalize_text(author) for author in authors if _normalize_text(author)]
    detail_payload["authors"] = authors

    library_match = find_library_matches([detail_payload]).get(f"{provider}:{provider_id}")
    queue_summary = load_queue_rows_for_items([(provider, provider_id)]).get(f"{provider}:{provider_id}")

    if queue_summary and queue_summary.imported_book_id:
        action = {
            "mode": "open_existing",
            "label": _("Imported"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=queue_summary.imported_book_id),
            "disabled": False,
            "hint": queue_summary.detail,
            "icon_class": "glyphicon glyphicon-book",
        }
    elif library_match:
        action = {
            "mode": "open_existing",
            "label": _("Open existing CWA book"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=library_match.book_id),
            "disabled": False,
            "hint": "",
            "icon_class": "glyphicon glyphicon-book",
        }
    elif queue_summary and queue_summary.status not in {"failed", "cancelled", "rejected"}:
        action = {
            "mode": "queue_state",
            "label": queue_summary.label,
            "button_class": "btn-default",
            "href": "",
            "disabled": True,
            "hint": queue_summary.detail,
            "icon_class": "glyphicon glyphicon-time",
        }
    else:
        payload = build_request_payload(detail_payload)
        action = {
            "mode": "request",
            "label": _("Request in Shelfmark"),
            "button_class": "btn-primary",
            "href": "",
            "disabled": False,
            "hint": queue_summary.detail if queue_summary else "",
            "payload_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            "icon_class": "glyphicon glyphicon-send",
        }

    display_description = _description_plain_text(detail_payload.get("description"))
    if hardcover_overlay and len(hardcover_overlay.description) > len(display_description):
        display_description = hardcover_overlay.description

    display_cover_url = _normalize_text(detail_payload.get("cover_url")) or (hardcover_overlay.cover_url if hardcover_overlay else "")
    series_memberships = _normalize_series_memberships(detail_payload, hardcover_overlay)
    primary_series = series_memberships[0] if series_memberships else {}
    series_name = _normalize_text(detail_payload.get("series_name")) or _normalize_text(primary_series.get("name")) or (hardcover_overlay.series if hardcover_overlay else "")
    series_position = detail_payload.get("series_position")
    if series_position in ("", None) and hardcover_overlay is not None:
        series_position = hardcover_overlay.series_index
    if series_position in ("", None):
        series_position = primary_series.get("position")
    series_count = _normalize_numeric(detail_payload.get("series_count"))
    if series_count is None:
        series_count = primary_series.get("count")
    provider_display_name = _provider_display_name(provider)
    facts = [
        value
        for value in (
            _published_year(detail_payload.get("publish_year")) or (hardcover_overlay.published_date[:4] if hardcover_overlay and hardcover_overlay.published_date else ""),
            f"{series_name} #{series_position}" if series_name and series_position not in ("", None) else series_name,
            provider_display_name,
        )
        if value
    ]
    detail_stats = _build_detail_stats(detail_payload, hardcover_overlay)

    view = {
        "provider": provider,
        "provider_id": provider_id,
        "provider_display_name": provider_display_name,
        "title": _normalize_text(detail_payload.get("title")),
        "subtitle": _normalize_text(detail_payload.get("subtitle")),
        "authors": authors,
        "description": display_description,
        "cover_url": display_cover_url,
        "publisher": _normalize_text(detail_payload.get("publisher")) or (hardcover_overlay.publisher if hardcover_overlay else ""),
        "publish_year": _published_year(detail_payload.get("publish_year")) or (hardcover_overlay.published_date[:4] if hardcover_overlay and hardcover_overlay.published_date else ""),
        "language": _normalize_text(detail_payload.get("language")) or (hardcover_overlay.language if hardcover_overlay else ""),
        "series_name": series_name,
        "series_position": series_position,
        "series_count": int(series_count) if series_count is not None else None,
        "series_memberships": series_memberships,
        "genres": tuple(detail_payload.get("genres") or []),
        "isbn_10": _normalize_text(detail_payload.get("isbn_10")),
        "isbn_13": _normalize_text(detail_payload.get("isbn_13")),
        "source_url": _normalize_text(detail_payload.get("source_url")) or (hardcover_overlay.source_url if hardcover_overlay else ""),
        "action": action,
        "library_match": library_match,
        "queue_summary": queue_summary,
        "hardcover_overlay": hardcover_overlay,
        "facts": facts,
        "detail_stats": detail_stats,
        "status_badges": _detail_status_badges(library_match, queue_summary),
        "display_tags": tuple(detail_payload.get("genres") or ()) or (hardcover_overlay.tags if hardcover_overlay else ()),
        "description_source": _("Shelfmark and Hardcover") if hardcover_overlay else _("Shelfmark"),
    }
    return view
