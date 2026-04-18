# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _build_hardcover_overlay(provider: str, provider_id: str) -> HardcoverOverlay | None:
    if provider != "hardcover" or not provider_id:
        return None
    try:
        results = Hardcover().search(f"hardcover-id:{provider_id}")
    except Exception as exc:
        log.debug("Hardcover overlay enrichment failed for %s: %s", provider_id, exc)
        return None
    if not results:
        return None
    result = results[0]
    tags = tuple(value for value in getattr(result, "tags", []) if _normalize_text(value))
    languages = getattr(result, "languages", []) or []
    return HardcoverOverlay(
        hardcover_id=_normalize_text(getattr(result, "identifiers", {}).get("hardcover-id") if hasattr(result, "identifiers") else provider_id) or provider_id,
        series=_normalize_text(getattr(result, "series", "")),
        series_index=getattr(result, "series_index", None),
        published_date=_normalize_text(getattr(result, "publishedDate", "")),
        publisher=_normalize_text(getattr(result, "publisher", "")),
        language=_normalize_text(languages[0] if languages else ""),
        tags=tags,
        description=_normalize_text(getattr(result, "description", "")),
    )


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
        hardcover_overlay = _build_hardcover_overlay(provider, provider_id)
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
        }
    elif library_match:
        action = {
            "mode": "open_existing",
            "label": _("Open existing CWA book"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=library_match.book_id),
            "disabled": False,
            "hint": "",
        }
    elif queue_summary and queue_summary.status not in {"failed", "cancelled", "rejected"}:
        action = {
            "mode": "queue_state",
            "label": queue_summary.label,
            "button_class": "btn-default",
            "href": "",
            "disabled": True,
            "hint": queue_summary.detail,
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
        }

    view = {
        "provider": provider,
        "provider_id": provider_id,
        "title": _normalize_text(detail_payload.get("title")),
        "subtitle": _normalize_text(detail_payload.get("subtitle")),
        "authors": authors,
        "description": _normalize_text(detail_payload.get("description")),
        "cover_url": _normalize_text(detail_payload.get("cover_url")),
        "publisher": _normalize_text(detail_payload.get("publisher")),
        "publish_year": _normalize_text(detail_payload.get("publish_year")),
        "language": _normalize_text(detail_payload.get("language")),
        "series_name": _normalize_text(detail_payload.get("series_name")),
        "series_position": detail_payload.get("series_position"),
        "series_count": detail_payload.get("series_count"),
        "genres": tuple(detail_payload.get("genres") or []),
        "isbn_10": _normalize_text(detail_payload.get("isbn_10")),
        "isbn_13": _normalize_text(detail_payload.get("isbn_13")),
        "source_url": _normalize_text(detail_payload.get("source_url")),
        "action": action,
        "library_match": library_match,
        "queue_summary": queue_summary,
        "hardcover_overlay": hardcover_overlay,
    }
    return view
