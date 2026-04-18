# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import OrderedDict, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from time import monotonic
from typing import Any

from flask import url_for
from flask_babel import gettext as _

from cps import config, logger
from cps.metadata_provider.hardcover import Hardcover

from .shelfmark_client import (
    DEFAULT_SHELFMARK_SEARCH_LIMIT,
    ShelfmarkClient,
    ShelfmarkClientConfig,
    ShelfmarkClientError,
    build_shelfmark_item_key,
)
from .shelfmark_queue import ACTIVE_QUEUE_STATUSES, ShelfmarkQueueSummary, load_queue_rows_for_items

log = logger.create()

DEFAULT_REQUEST_SEARCH_SORT = "popularity"
DEFAULT_REQUEST_FILTER_HAS_COVER = True
DEFAULT_REQUEST_FILTER_HIDE_OWNED = True
DEFAULT_REQUEST_VISIBLE_PAGE = 1
REQUEST_SEARCH_SORT_OPTIONS = (
    ("popularity", "Most popular"),
    ("relevance", "Most relevant"),
    ("rating", "Highest rated"),
    ("newest", "Newest"),
    ("oldest", "Oldest"),
)
HARDCOVER_QUERY_CACHE_TTL_SECONDS = 300
HARDCOVER_QUERY_CACHE_MAX_ENTRIES = 48
HARDCOVER_QUERY_MIN_LENGTH = 3
HARDCOVER_RESULT_EXCERPT_LENGTH = 240
REQUEST_SEARCH_PAGE_CACHE_TTL_SECONDS = 120
REQUEST_SEARCH_PAGE_CACHE_MAX_ENTRIES = 128

_HARDCOVER_QUERY_CACHE: OrderedDict[str, tuple[float, tuple[dict[str, Any], ...]]] = OrderedDict()
_REQUEST_SEARCH_PAGE_CACHE: OrderedDict[
    tuple[str, str, str, int, int],
    tuple[float, dict[str, Any]],
] = OrderedDict()
_NON_BOOK_ENTITY_TYPES = {
    "author",
    "authors",
    "series",
    "publisher",
    "publishers",
    "genre",
    "genres",
    "tag",
    "tags",
    "list",
    "lists",
    "shelf",
    "shelves",
}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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


def _normalize_flag(value: Any, *, default: bool) -> bool:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_int(value: Any) -> int | None:
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def normalize_request_search_sort(value: Any) -> str:
    normalized = _normalize_text(value).lower()
    if normalized in {item[0] for item in REQUEST_SEARCH_SORT_OPTIONS}:
        return normalized
    return DEFAULT_REQUEST_SEARCH_SORT


def get_request_search_sort_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {"value": value, "label": _(label)}
        for value, label in REQUEST_SEARCH_SORT_OPTIONS
    )


def _provider_display_name(value: Any) -> str:
    provider = _normalize_text(value).replace("_", " ").replace("-", " ")
    if not provider:
        return ""
    return provider if any(char.isupper() for char in provider) else provider.title()


def _description_plain_text(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _excerpt_text(value: Any, *, limit: int = HARDCOVER_RESULT_EXCERPT_LENGTH) -> str:
    text = _description_plain_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _published_year(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    match = re.search(r"(\d{4})", text)
    return match.group(1) if match else text


def _cache_get_hardcover_query(query: str) -> tuple[dict[str, Any], ...] | None:
    cached = _HARDCOVER_QUERY_CACHE.get(query)
    if cached is None:
        return None
    cached_at, value = cached
    if monotonic() - cached_at > HARDCOVER_QUERY_CACHE_TTL_SECONDS:
        _HARDCOVER_QUERY_CACHE.pop(query, None)
        return None
    _HARDCOVER_QUERY_CACHE.move_to_end(query)
    return tuple(dict(item) for item in value)


def _cache_set_hardcover_query(query: str, results: Sequence[Mapping[str, Any]]) -> None:
    _HARDCOVER_QUERY_CACHE[query] = (monotonic(), tuple(dict(item) for item in results))
    _HARDCOVER_QUERY_CACHE.move_to_end(query)
    while len(_HARDCOVER_QUERY_CACHE) > HARDCOVER_QUERY_CACHE_MAX_ENTRIES:
        _HARDCOVER_QUERY_CACHE.popitem(last=False)


def _cache_get_request_search_page(
    base_url: str,
    query: str,
    sort: str,
    page: int,
    limit: int,
) -> dict[str, Any] | None:
    key = (base_url, query, sort, page, limit)
    cached = _REQUEST_SEARCH_PAGE_CACHE.get(key)
    if cached is None:
        return None
    cached_at, payload = cached
    if monotonic() - cached_at > REQUEST_SEARCH_PAGE_CACHE_TTL_SECONDS:
        _REQUEST_SEARCH_PAGE_CACHE.pop(key, None)
        return None
    _REQUEST_SEARCH_PAGE_CACHE.move_to_end(key)
    return dict(payload)


def _cache_set_request_search_page(
    base_url: str,
    query: str,
    sort: str,
    page: int,
    limit: int,
    payload: Mapping[str, Any],
) -> None:
    key = (base_url, query, sort, page, limit)
    _REQUEST_SEARCH_PAGE_CACHE[key] = (monotonic(), dict(payload))
    _REQUEST_SEARCH_PAGE_CACHE.move_to_end(key)
    while len(_REQUEST_SEARCH_PAGE_CACHE) > REQUEST_SEARCH_PAGE_CACHE_MAX_ENTRIES:
        _REQUEST_SEARCH_PAGE_CACHE.popitem(last=False)


def _normalize_hardcover_record(record: Any) -> dict[str, Any]:
    identifiers = getattr(record, "identifiers", {}) if hasattr(record, "identifiers") else {}
    languages = getattr(record, "languages", []) or []
    authors = [_normalize_text(value) for value in (getattr(record, "authors", []) or []) if _normalize_text(value)]
    return {
        "hardcover_id": _normalize_text(identifiers.get("hardcover-id") if isinstance(identifiers, Mapping) else "") or _normalize_text(getattr(record, "id", "")),
        "isbn": _normalize_identifier(identifiers.get("isbn") if isinstance(identifiers, Mapping) else ""),
        "title": _normalize_text(getattr(record, "title", "")),
        "authors": authors,
        "description": _description_plain_text(getattr(record, "description", "")),
        "cover_url": _normalize_text(getattr(record, "cover", "")),
        "series_name": _normalize_text(getattr(record, "series", "")),
        "series_position": getattr(record, "series_index", None),
        "publish_year": _published_year(getattr(record, "publishedDate", "")),
        "publisher": _normalize_text(getattr(record, "publisher", "")),
        "language": _normalize_text(languages[0] if languages else ""),
        "format": _normalize_text(getattr(record, "format", "")),
        "subtitle": _normalize_text(getattr(record, "subtitle", "")),
        "pages": getattr(record, "pages", None),
        "rating": getattr(record, "rating", None) or getattr(record, "average_rating", None),
        "ratings_count": (
            getattr(record, "ratings_count", None)
            or getattr(record, "ratingsCount", None)
            or getattr(record, "ratings", None)
        ),
        "readers_count": (
            getattr(record, "readers_count", None)
            or getattr(record, "readersCount", None)
            or getattr(record, "readers", None)
            or getattr(record, "users_count", None)
        ),
        "source_url": _normalize_text(getattr(record, "url", "")),
    }


def _search_hardcover_enrichment(query: str) -> tuple[dict[str, Any], ...]:
    normalized_query = _normalize_text(query)
    if len(normalized_query) < HARDCOVER_QUERY_MIN_LENGTH:
        return ()

    cached = _cache_get_hardcover_query(normalized_query)
    if cached is not None:
        return cached

    try:
        results = Hardcover().search(normalized_query)
    except Exception as exc:  # pragma: no cover - defensive: provider library throws broad exceptions
        log.debug("Hardcover search enrichment failed for '%s': %s", normalized_query, exc)
        return ()

    normalized_results = tuple(
        _normalize_hardcover_record(record)
        for record in (results or [])
        if record is not None
    )
    _cache_set_hardcover_query(normalized_query, normalized_results)
    return normalized_results


def _match_hardcover_enrichment(
    result: Mapping[str, Any],
    hardcover_results: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not hardcover_results:
        return None

    hardcover_id = _normalize_text(result.get("hardcover_id"))
    if not hardcover_id and _normalize_text(result.get("provider")).lower() == "hardcover":
        hardcover_id = _normalize_text(result.get("provider_id"))
    isbn = (
        _normalize_identifier(result.get("isbn"))
        or _normalize_identifier(result.get("isbn_13"))
        or _normalize_identifier(result.get("isbn_10"))
    )
    normalized_titles = _normalize_title_variants(result.get("title"))
    authors = result.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(result.get("author"))] if _normalize_text(result.get("author")) else []
    normalized_author = _normalize_for_match(authors[0] if authors else "")

    for candidate in hardcover_results:
        if hardcover_id and _normalize_text(candidate.get("hardcover_id")) == hardcover_id:
            return candidate
    for candidate in hardcover_results:
        if isbn and _normalize_identifier(candidate.get("isbn")) == isbn:
            return candidate
    for candidate in hardcover_results:
        if _normalize_for_match(candidate.get("title")) not in normalized_titles:
            continue
        candidate_authors = candidate.get("authors") or []
        if normalized_author and _normalize_for_match(candidate_authors[0] if candidate_authors else "") != normalized_author:
            continue
        return candidate
    return None


def _entity_kind(result: Mapping[str, Any]) -> str:
    for key in (
        "entity_type",
        "result_type",
        "type",
        "kind",
        "metadata_type",
        "match_type",
    ):
        normalized = _normalize_text(result.get(key)).lower()
        if normalized:
            return normalized
    return ""


def _is_probable_non_book_result(result: Mapping[str, Any], *, query: str) -> bool:
    entity_kind = _entity_kind(result)
    if entity_kind in _NON_BOOK_ENTITY_TYPES:
        return True

    title = _normalize_text(result.get("title"))
    normalized_title = _normalize_for_match(title)
    if not normalized_title:
        return True

    authors = result.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(result.get("author"))] if _normalize_text(result.get("author")) else []
    normalized_authors = [_normalize_for_match(author) for author in authors if _normalize_text(author)]
    primary_author = normalized_authors[0] if normalized_authors else ""
    joined_authors = " ".join(value for value in normalized_authors if value)

    if primary_author and normalized_title == primary_author:
        return True
    if joined_authors and normalized_title == joined_authors:
        return True
    if (
        normalized_title == _normalize_for_match(query)
        and not normalized_authors
        and not _normalize_text(result.get("subtitle"))
        and not _normalize_text(result.get("description"))
        and not _normalize_text(result.get("series_name"))
    ):
        return True
    return False


def _merge_result_enrichment(
    result: Mapping[str, Any],
    hardcover_match: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(result)
    if hardcover_match is None:
        merged["description"] = _description_plain_text(merged.get("description"))
        return merged

    for key in (
        "subtitle",
        "cover_url",
        "series_name",
        "series_position",
        "series_count",
        "publisher",
        "language",
        "format",
        "pages",
        "rating",
        "ratings_count",
        "readers_count",
        "source_url",
    ):
        if not _normalize_text(merged.get(key)) and hardcover_match.get(key):
            merged[key] = hardcover_match.get(key)

    if not _published_year(merged.get("publish_year")) and hardcover_match.get("publish_year"):
        merged["publish_year"] = hardcover_match.get("publish_year")

    description = _description_plain_text(merged.get("description"))
    overlay_description = _description_plain_text(hardcover_match.get("description"))
    merged["description"] = overlay_description if len(overlay_description) > len(description) else description
    if not merged.get("hardcover_id") and hardcover_match.get("hardcover_id"):
        merged["hardcover_id"] = hardcover_match.get("hardcover_id")
    if not merged.get("authors") and hardcover_match.get("authors"):
        merged["authors"] = list(hardcover_match.get("authors") or [])
    return merged


def _normalize_authors(result: Mapping[str, Any]) -> list[str]:
    authors = result.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(result.get("author"))] if _normalize_text(result.get("author")) else []
    return [_normalize_text(author) for author in authors if _normalize_text(author)]


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


def _extract_numeric_field(result: Mapping[str, Any], *keys: str) -> float | int | None:
    for key in keys:
        if key in result:
            numeric = _normalize_numeric(result.get(key))
            if numeric is not None:
                return numeric
    return None


def _pluralized_count(value: float | int | None, singular: str, plural: str) -> str:
    if value is None:
        return ""
    integer = int(value)
    label = singular if integer == 1 else plural
    return _("%(count)s %(label)s", count=f"{integer:,}", label=label)


def _format_rating(value: float | int | None) -> str:
    if value is None:
        return ""
    return _("%(rating).1f rating", rating=float(value))


def _normalize_series_memberships(result: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
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
        normalized_count = _normalize_int(count)
        detail_text = (
            _("%(count)s books", count=f"{normalized_count:,}")
            if normalized_count
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
                "count": normalized_count,
                "detail": detail_text,
                "url": series_url,
            }
        )

    for key in ("series_memberships", "series_entries", "series"):
        raw_value = result.get(key)
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
            name=result.get("series_name"),
            position=result.get("series_position"),
            count=result.get("series_count"),
            url=result.get("series_url"),
        )
    return tuple(memberships)


def _series_note_from_memberships(memberships: Sequence[Mapping[str, Any]]) -> str:
    if not memberships:
        return ""
    first = memberships[0]
    note = _normalize_text(first.get("display"))
    detail = _normalize_text(first.get("detail"))
    if detail:
        note = f"{note} · {detail}" if note else detail
    return note


def _secondary_series_note(memberships: Sequence[Mapping[str, Any]]) -> str:
    if len(memberships) <= 1:
        return ""
    parts = []
    for membership in memberships[1:]:
        display = _normalize_text(membership.get("display"))
        detail = _normalize_text(membership.get("detail"))
        if detail:
            parts.append(f"{display} · {detail}" if display else detail)
        elif display:
            parts.append(display)
    return " · ".join(part for part in parts if part)


def _build_result_stats(result: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    stats: list[dict[str, str]] = []
    rating = _extract_numeric_field(result, "rating", "average_rating")
    if rating is not None:
        stats.append({"label": _("Rating"), "value": f"{float(rating):.1f}"})
    ratings_count = _extract_numeric_field(result, "ratings_count", "ratingsCount", "ratings")
    if ratings_count is not None:
        stats.append({"label": _("Ratings"), "value": f"{int(ratings_count):,}"})
    readers_count = _extract_numeric_field(result, "readers_count", "readersCount", "readers", "users_count")
    if readers_count is not None:
        stats.append({"label": _("Readers"), "value": f"{int(readers_count):,}"})
    pages = _extract_numeric_field(result, "pages", "page_count")
    if pages is not None:
        stats.append({"label": _("Pages"), "value": f"{int(pages):,}"})
    return tuple(stats)


def _request_search_has_more(
    payload: Mapping[str, Any],
    *,
    raw_page: int,
    limit: int,
    page_result_count: int,
    total_found: int,
) -> bool:
    if "has_more" in payload:
        return _normalize_flag(payload.get("has_more"), default=False)
    if total_found:
        return raw_page * limit < total_found
    return page_result_count >= limit and page_result_count > 0


def _fetch_request_search_payload(
    client: ShelfmarkClient,
    query: str,
    *,
    limit: int,
    page: int,
    sort: str,
) -> dict[str, Any]:
    client_config = getattr(client, "config", None)
    cache_base_url = _normalize_text(getattr(client_config, "base_url", ""))
    cached = _cache_get_request_search_page(cache_base_url, query, sort, page, limit)
    if cached is not None:
        return cached

    payload = client.search_books(query, limit=limit, page=page, sort=sort)
    if not isinstance(payload, Mapping):
        raise ShelfmarkClientError(_("Shelfmark returned an unexpected metadata search response."))
    normalized_payload = dict(payload)
    _cache_set_request_search_page(cache_base_url, query, sort, page, limit, normalized_payload)
    return normalized_payload

def _normalize_title_variants(value: Any) -> set[str]:
    title = _normalize_for_match(value)
    variants = {title} if title else set()
    if ":" in _normalize_text(value):
        variants.add(_normalize_for_match(_normalize_text(value).split(":", 1)[0]))
    return {variant for variant in variants if variant}


def _parse_identifier_map(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {
            _normalize_text(identifier_type).lower(): _normalize_text(identifier_value)
            for identifier_type, identifier_value in value.items()
            if _normalize_text(identifier_type) and _normalize_text(identifier_value)
        }

    text = _normalize_text(value)
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {
        _normalize_text(identifier_type).lower(): _normalize_text(identifier_value)
        for identifier_type, identifier_value in parsed.items()
        if _normalize_text(identifier_type) and _normalize_text(identifier_value)
    }


def _library_metadata_db_path() -> str | None:
    calibre_dir = _normalize_text(getattr(config, "config_calibre_dir", ""))
    if not calibre_dir:
        return None
    metadata_db = os.path.join(calibre_dir, "metadata.db")
    return metadata_db if os.path.exists(metadata_db) else None


@dataclass(frozen=True)
class LibraryMatch:
    book_id: int
    title: str
    author: str
    reason: str


def _fetch_library_exact_matches(
    connection: sqlite3.Connection,
    *,
    hardcover_ids: set[str],
    isbn_values: set[str],
) -> dict[tuple[str, str], LibraryMatch]:
    match_map: dict[tuple[str, str], LibraryMatch] = {}

    clauses: list[str] = []
    params: list[str] = []
    if hardcover_ids:
        clauses.append(
            "(identifiers.type = 'hardcover-id' AND identifiers.val IN (%s))"
            % ",".join("?" for _ in hardcover_ids)
        )
        params.extend(sorted(hardcover_ids))
    if isbn_values:
        clauses.append(
            "(identifiers.type = 'isbn' AND identifiers.val IN (%s))"
            % ",".join("?" for _ in isbn_values)
        )
        params.extend(sorted(isbn_values))
    if not clauses:
        return match_map

    rows = connection.execute(
        """
        SELECT identifiers.type, identifiers.val, books.id, books.title
        FROM identifiers
        JOIN books ON books.id = identifiers.book
        WHERE %s
        """
        % " OR ".join(clauses),
        params,
    ).fetchall()

    book_ids = [int(row[2]) for row in rows]
    author_rows = _fetch_book_authors(connection, book_ids)
    for identifier_type, identifier_value, book_id, title in rows:
        book_id = int(book_id)
        match_map[(str(identifier_type), str(identifier_value))] = LibraryMatch(
            book_id=book_id,
            title=_normalize_text(title),
            author=_normalize_text(author_rows.get(book_id, "")),
            reason=str(identifier_type),
        )
    return match_map


def _fetch_book_authors(connection: sqlite3.Connection, book_ids: Sequence[int]) -> dict[int, str]:
    if not book_ids:
        return {}
    rows = connection.execute(
        """
        SELECT books_authors_link.book, authors.name
        FROM books_authors_link
        JOIN authors ON authors.id = books_authors_link.author
        WHERE books_authors_link.book IN (%s)
        ORDER BY books_authors_link.book, books_authors_link.id
        """
        % ",".join("?" for _ in book_ids),
        [int(book_id) for book_id in book_ids],
    ).fetchall()
    authors_by_book: dict[int, list[str]] = defaultdict(list)
    for book_id, author_name in rows:
        authors_by_book[int(book_id)].append(_normalize_text(author_name).replace("|", ","))
    return {
        book_id: ", ".join(values)
        for book_id, values in authors_by_book.items()
    }


def _fetch_title_candidates(
    connection: sqlite3.Connection,
    raw_titles: set[str],
) -> list[tuple[int, str, str]]:
    if not raw_titles:
        return []

    lowered_titles = sorted({_normalize_text(title).lower() for title in raw_titles if _normalize_text(title)})
    if not lowered_titles:
        return []

    rows = connection.execute(
        """
        SELECT books.id, books.title
        FROM books
        WHERE lower(books.title) IN (%s)
        """
        % ",".join("?" for _ in lowered_titles),
        lowered_titles,
    ).fetchall()

    book_ids = [int(row[0]) for row in rows]
    author_map = _fetch_book_authors(connection, book_ids)
    return [
        (int(book_id), _normalize_text(title), author_map.get(int(book_id), ""))
        for book_id, title in rows
    ]


def find_library_matches(results: Sequence[Mapping[str, Any]]) -> dict[str, LibraryMatch]:
    metadata_db = _library_metadata_db_path()
    if metadata_db is None:
        return {}

    hardcover_ids = {
        _normalize_text(result.get("hardcover_id")) or _normalize_text(result.get("provider_id"))
        for result in results
        if (
            (
                _normalize_text(result.get("provider")).lower() == "hardcover"
                and _normalize_text(result.get("provider_id"))
            )
            or _normalize_text(result.get("hardcover_id"))
        )
    }
    isbn_values = {
        _normalize_identifier(result.get("isbn")) or _normalize_identifier(result.get("isbn_13")) or _normalize_identifier(result.get("isbn_10"))
        for result in results
    }
    isbn_values.discard("")
    raw_titles = {
        _normalize_text(result.get("title"))
        for result in results
        if _normalize_text(result.get("title"))
    }

    with sqlite3.connect(metadata_db, timeout=30) as connection:
        exact_matches = _fetch_library_exact_matches(
            connection,
            hardcover_ids=hardcover_ids,
            isbn_values=isbn_values,
        )
        title_candidates = _fetch_title_candidates(connection, raw_titles)

    matches: dict[str, LibraryMatch] = {}
    for result in results:
        key = build_shelfmark_item_key(result.get("provider"), result.get("provider_id"))
        if not key:
            continue

        hardcover_id = _normalize_text(result.get("hardcover_id"))
        hardcover_provider = _normalize_text(result.get("provider")).lower() == "hardcover"
        provider_id = _normalize_text(result.get("provider_id"))
        hardcover_lookup_id = hardcover_id or (provider_id if hardcover_provider else "")
        if hardcover_lookup_id:
            exact = exact_matches.get(("hardcover-id", hardcover_lookup_id))
            if exact:
                matches[key] = exact
                continue

        isbn = _normalize_identifier(result.get("isbn")) or _normalize_identifier(result.get("isbn_13")) or _normalize_identifier(result.get("isbn_10"))
        if isbn:
            exact = exact_matches.get(("isbn", isbn))
            if exact:
                matches[key] = exact
                continue

        expected_titles = _normalize_title_variants(result.get("title"))
        expected_author = _normalize_for_match((result.get("authors") or [result.get("author") or ""])[0])
        for book_id, title, author in title_candidates:
            if _normalize_for_match(title) not in expected_titles:
                continue
            if expected_author and _normalize_for_match(author).split(",")[0] != expected_author:
                continue
            matches[key] = LibraryMatch(
                book_id=book_id,
                title=title,
                author=author,
                reason="title_author",
            )
            break

    return matches


def reconcile_queue_rows_with_library(rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    metadata_db = _library_metadata_db_path()
    if metadata_db is None or not rows:
        return []

    title_rows = []
    for row in rows:
        identifiers = _parse_identifier_map(row.get("identifiers_json"))
        title_rows.append(
            {
                "provider": row.get("provider"),
                "provider_id": row.get("provider_id"),
                "title": row.get("title"),
                "authors": [_normalize_text(row.get("author"))] if _normalize_text(row.get("author")) else [],
                "hardcover_id": identifiers.get("hardcover-id", ""),
                "isbn": identifiers.get("isbn", ""),
                "isbn_13": "",
                "isbn_10": "",
            }
        )
    title_matches = find_library_matches(title_rows)
    imported: list[tuple[int, int]] = []
    for row in rows:
        key = build_shelfmark_item_key(row.get("provider"), row.get("provider_id"))
        match = title_matches.get(key)
        if match is not None:
            imported.append((int(row["id"]), match.book_id))
    return imported


def build_request_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    authors = result.get("authors")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        authors = [_normalize_text(result.get("author"))] if _normalize_text(result.get("author")) else []
    authors = [_normalize_text(author) for author in authors if _normalize_text(author)]
    return {
        "book_data": {
            "title": _normalize_text(result.get("title")) or _("Unknown title"),
            "author": _normalize_text(authors[0] if authors else "") or _("Unknown author"),
            "content_type": "ebook",
            "provider": _normalize_text(result.get("provider")).lower(),
            "provider_id": _normalize_text(result.get("provider_id")),
            "year": _normalize_text(result.get("publish_year")),
            "preview": _normalize_text(result.get("cover_url")),
            "series_name": _normalize_text(result.get("series_name")),
            "series_position": result.get("series_position"),
            "series_count": result.get("series_count"),
            "subtitle": _normalize_text(result.get("subtitle")),
            "source_url": _normalize_text(result.get("source_url")),
            "isbn_10": _normalize_text(result.get("isbn_10")),
            "isbn_13": _normalize_text(result.get("isbn_13")),
        },
        "release_data": None,
        "context": {
            "source": "*",
            "content_type": "ebook",
            "request_level": "book",
        },
    }


def _action_for_result(
    result: Mapping[str, Any],
    *,
    return_to: str,
    library_match: LibraryMatch | None,
    queue_summary: ShelfmarkQueueSummary | None,
) -> dict[str, Any]:
    if queue_summary and queue_summary.imported_book_id:
        return {
            "mode": "open_existing",
            "label": _("Imported"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=queue_summary.imported_book_id),
            "disabled": False,
            "hint": queue_summary.detail,
            "icon_class": "glyphicon glyphicon-book",
        }

    if library_match is not None:
        return {
            "mode": "open_existing",
            "label": _("Open existing CWA book"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=library_match.book_id),
            "disabled": False,
            "hint": "",
            "icon_class": "glyphicon glyphicon-book",
        }

    if queue_summary is not None and queue_summary.status not in {"failed", "cancelled", "rejected"}:
        return {
            "mode": "queue_state",
            "label": queue_summary.label,
            "button_class": "btn-default",
            "href": "",
            "disabled": True,
            "hint": queue_summary.detail,
            "icon_class": "glyphicon glyphicon-time",
        }

    payload = build_request_payload(result)
    return {
        "mode": "request",
        "label": _("Request in Shelfmark"),
        "button_class": "btn-primary",
        "href": "",
        "disabled": False,
        "hint": queue_summary.detail if queue_summary and queue_summary.detail else "",
        "payload_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
        "return_to": return_to,
        "icon_class": "glyphicon glyphicon-send",
    }


def _build_result_facts(result: Mapping[str, Any]) -> list[str]:
    facts: list[str] = []
    publish_year = _published_year(result.get("publish_year"))
    provider_display_name = _provider_display_name(result.get("provider_display_name")) or _provider_display_name(result.get("provider"))
    format_label = _normalize_text(result.get("format"))
    pages_label = _pluralized_count(_extract_numeric_field(result, "pages", "page_count"), "page", "pages")
    rating_label = _format_rating(_extract_numeric_field(result, "rating", "average_rating"))
    if publish_year:
        facts.append(publish_year)
    if format_label:
        facts.append(format_label)
    if pages_label:
        facts.append(pages_label)
    if rating_label:
        facts.append(rating_label)
    if provider_display_name:
        provider_lower = provider_display_name.lower()
        format_lower = format_label.lower()
        if not format_lower or provider_lower != format_lower:
            facts.append(provider_display_name)
    language = _normalize_text(result.get("language"))
    if language:
        facts.append(language)
    deduped: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        normalized = fact.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(fact)
    return deduped


def _series_note(result: Mapping[str, Any]) -> str:
    series_name = _normalize_text(result.get("series_name"))
    if not series_name:
        return ""
    series_position = _normalize_text(result.get("series_position"))
    series_count = _normalize_text(result.get("series_count"))
    note = series_name
    if series_position:
        note += f" #{series_position}"
    if series_count:
        note += _(" · %(count)s books", count=series_count)
    return note


def _row_class(library_match: LibraryMatch | None, queue_summary: ShelfmarkQueueSummary | None) -> str:
    if queue_summary and queue_summary.imported_book_id:
        return "shelfmark-result-card--success"
    if library_match is not None:
        return "shelfmark-result-card--success"
    if queue_summary is not None and queue_summary.status in ACTIVE_QUEUE_STATUSES:
        return "shelfmark-result-card--info"
    if queue_summary is not None and queue_summary.status in {"failed", "cancelled", "rejected"}:
        return "shelfmark-result-card--warning"
    return ""


def _status_badges(
    library_match: LibraryMatch | None,
    queue_summary: ShelfmarkQueueSummary | None,
) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    if queue_summary and queue_summary.imported_book_id:
        badges.append({"label": _("Imported"), "class": "label label-success"})
    elif library_match is not None:
        badges.append({"label": _("In library"), "class": "label label-success"})
    elif queue_summary is not None:
        if queue_summary.status in {"failed", "cancelled", "rejected"}:
            badges.append({"label": _("Retry available"), "class": "label label-warning"})
        elif queue_summary.status in {"downloading", "complete", "importing"}:
            badges.append({"label": queue_summary.label, "class": "label label-info"})
        else:
            badges.append({"label": queue_summary.label, "class": "label label-default"})
    return badges


def search_shelfmark(
    config_data: ShelfmarkClientConfig,
    query: str,
    *,
    limit: int = DEFAULT_SHELFMARK_SEARCH_LIMIT,
    page: int = DEFAULT_REQUEST_VISIBLE_PAGE,
    sort: str = DEFAULT_REQUEST_SEARCH_SORT,
    has_cover_only: bool = DEFAULT_REQUEST_FILTER_HAS_COVER,
    hide_owned: bool = DEFAULT_REQUEST_FILTER_HIDE_OWNED,
) -> dict[str, Any]:
    normalized_query = _normalize_text(query)
    page_size = max(1, _normalize_int(limit) or DEFAULT_SHELFMARK_SEARCH_LIMIT)
    current_page = max(DEFAULT_REQUEST_VISIBLE_PAGE, _normalize_int(page) or DEFAULT_REQUEST_VISIBLE_PAGE)
    selected_sort = normalize_request_search_sort(sort)
    filter_has_cover = bool(has_cover_only)
    filter_hide_owned = bool(hide_owned)
    if not normalized_query:
        return {
            "query": "",
            "results": [],
            "error": "",
            "total_found": 0,
            "searched": False,
            "visible_count": 0,
            "page_result_count": 0,
            "selected_sort": selected_sort,
            "filter_has_cover": filter_has_cover,
            "filter_hide_owned": filter_hide_owned,
            "filtered_non_books": 0,
            "filtered_owned": 0,
            "filtered_coverless": 0,
            "page": current_page,
            "total_pages": 0,
            "visible_start": 0,
            "visible_end": 0,
            "has_previous": False,
            "previous_page": None,
            "has_next": False,
            "next_page": None,
        }

    client = ShelfmarkClient(config_data)
    raw_results: list[dict[str, Any]] = []
    total_found = 0
    raw_page = DEFAULT_REQUEST_VISIBLE_PAGE
    while True:
        payload = _fetch_request_search_payload(
            client,
            normalized_query,
            limit=page_size,
            page=raw_page,
            sort=selected_sort,
        )
        books = payload.get("books")
        if not isinstance(books, Sequence) or isinstance(books, (str, bytes)):
            raise ShelfmarkClientError(_("Shelfmark returned an unexpected metadata search response."))

        page_results = [dict(book) for book in books if isinstance(book, Mapping)]
        raw_results.extend(page_results)
        total_found = max(total_found, _normalize_int(payload.get("total_found")) or 0, len(raw_results))
        if not _request_search_has_more(
            payload,
            raw_page=raw_page,
            limit=page_size,
            page_result_count=len(page_results),
            total_found=total_found,
        ):
            break
        raw_page += 1

    hardcover_results = _search_hardcover_enrichment(normalized_query)
    candidate_results: list[dict[str, Any]] = []
    filtered_non_books = 0
    for raw_result in raw_results:
        normalized_result = dict(raw_result)
        normalized_result["provider"] = _normalize_text(normalized_result.get("provider")).lower()
        normalized_result["provider_id"] = _normalize_text(normalized_result.get("provider_id"))
        normalized_result["authors"] = _normalize_authors(normalized_result)
        if _is_probable_non_book_result(raw_result, query=normalized_query):
            filtered_non_books += 1
            continue
        normalized_result = _merge_result_enrichment(
            normalized_result,
            _match_hardcover_enrichment(normalized_result, hardcover_results),
        )
        normalized_result["authors"] = _normalize_authors(normalized_result)
        candidate_results.append(normalized_result)

    library_matches = find_library_matches(candidate_results)
    unique_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for result in candidate_results:
        provider = _normalize_text(result.get("provider")).lower()
        provider_id = _normalize_text(result.get("provider_id"))
        if not provider or not provider_id:
            continue
        pair = (provider, provider_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    queue_rows = load_queue_rows_for_items(unique_pairs)

    filtered_owned = 0
    filtered_coverless = 0
    visible_candidates: list[tuple[str, dict[str, Any], LibraryMatch | None, ShelfmarkQueueSummary | None]] = []
    for result in candidate_results:
        key = build_shelfmark_item_key(result.get("provider"), result.get("provider_id"))
        if not key:
            continue
        library_match = library_matches.get(key)
        queue_summary = queue_rows.get(key)
        if filter_hide_owned and library_match is not None:
            filtered_owned += 1
            continue
        if filter_has_cover and not _normalize_text(result.get("cover_url")):
            filtered_coverless += 1
            continue
        visible_candidates.append((key, result, library_match, queue_summary))

    visible_total_count = len(visible_candidates)
    total_pages = max(1, math.ceil(visible_total_count / page_size)) if visible_total_count else 0
    current_page = min(current_page, total_pages) if total_pages else DEFAULT_REQUEST_VISIBLE_PAGE
    page_start = (current_page - 1) * page_size
    page_end = page_start + page_size
    page_candidates = visible_candidates[page_start:page_end]

    view_results: list[dict[str, Any]] = []
    visible_start = page_start + 1 if page_candidates else 0
    visible_end = page_start + len(page_candidates) if page_candidates else 0
    for key, raw_result, library_match, queue_summary in page_candidates:
        series_memberships = _normalize_series_memberships(raw_result)
        detail_url = url_for(
            "shelfmark_search.book_detail",
            provider=_normalize_text(raw_result.get("provider")).lower(),
            provider_id=_normalize_text(raw_result.get("provider_id")),
            query=normalized_query,
            page=current_page,
            sort=selected_sort,
            has_cover=int(filter_has_cover),
            hide_owned=int(filter_hide_owned),
        )
        return_to = url_for(
            "shelfmark_search.search_page",
            query=normalized_query,
            page=current_page,
            sort=selected_sort,
            has_cover=int(filter_has_cover),
            hide_owned=int(filter_hide_owned),
        )
        action = _action_for_result(
            raw_result,
            return_to=return_to,
            library_match=library_match,
            queue_summary=queue_summary,
        )
        view_results.append(
            {
                "key": key,
                "provider": _normalize_text(raw_result.get("provider")).lower(),
                "provider_id": _normalize_text(raw_result.get("provider_id")),
                "title": _normalize_text(raw_result.get("title")),
                "subtitle": _normalize_text(raw_result.get("subtitle")),
                "authors": _normalize_authors(raw_result),
                "cover_url": _normalize_text(raw_result.get("cover_url")),
                "description": _excerpt_text(raw_result.get("description")),
                "series_name": _normalize_text(raw_result.get("series_name")),
                "series_position": raw_result.get("series_position"),
                "series_count": raw_result.get("series_count"),
                "series_memberships": series_memberships,
                "series_note": _series_note_from_memberships(series_memberships),
                "secondary_series_note": _secondary_series_note(series_memberships),
                "facts": _build_result_facts(raw_result),
                "detail_stats": _build_result_stats(raw_result),
                "detail_url": detail_url,
                "action": action,
                "queue_summary": queue_summary,
                "library_match": library_match,
                "row_class": _row_class(library_match, queue_summary),
                "status_badges": _status_badges(library_match, queue_summary),
            }
        )

    return {
        "query": normalized_query,
        "results": view_results,
        "error": "",
        "total_found": total_found,
        "visible_count": visible_total_count,
        "page_result_count": len(view_results),
        "searched": True,
        "selected_sort": selected_sort,
        "filter_has_cover": filter_has_cover,
        "filter_hide_owned": filter_hide_owned,
        "filtered_non_books": filtered_non_books,
        "filtered_owned": filtered_owned,
        "filtered_coverless": filtered_coverless,
        "page": current_page,
        "total_pages": total_pages,
        "visible_start": visible_start,
        "visible_end": visible_end,
        "has_previous": current_page > DEFAULT_REQUEST_VISIBLE_PAGE,
        "previous_page": current_page - 1 if current_page > DEFAULT_REQUEST_VISIBLE_PAGE else None,
        "has_next": bool(total_pages and current_page < total_pages),
        "next_page": current_page + 1 if total_pages and current_page < total_pages else None,
    }
