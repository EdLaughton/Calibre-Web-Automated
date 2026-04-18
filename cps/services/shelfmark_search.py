# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from flask import url_for
from flask_babel import gettext as _

from cps import config, logger

from .shelfmark_client import (
    DEFAULT_SHELFMARK_SEARCH_LIMIT,
    ShelfmarkClient,
    ShelfmarkClientConfig,
    ShelfmarkClientError,
    build_shelfmark_item_key,
)
from .shelfmark_queue import ShelfmarkQueueSummary, load_queue_rows_for_items

log = logger.create()


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
    query: str,
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
        }

    if library_match is not None:
        return {
            "mode": "open_existing",
            "label": _("Open existing CWA book"),
            "button_class": "btn-success",
            "href": url_for("web.show_book", book_id=library_match.book_id),
            "disabled": False,
            "hint": "",
        }

    if queue_summary is not None and queue_summary.status not in {"failed", "cancelled", "rejected"}:
        return {
            "mode": "queue_state",
            "label": queue_summary.label,
            "button_class": "btn-default",
            "href": "",
            "disabled": True,
            "hint": queue_summary.detail,
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
        "return_to": url_for("shelfmark_search.search_page", query=query),
    }


def _build_result_facts(result: Mapping[str, Any]) -> list[str]:
    facts: list[str] = []
    publish_year = _normalize_text(result.get("publish_year"))
    provider_display_name = _normalize_text(result.get("provider_display_name")) or _normalize_text(result.get("provider"))
    if publish_year:
        facts.append(publish_year)
    if provider_display_name:
        facts.append(provider_display_name)
    language = _normalize_text(result.get("language"))
    if language:
        facts.append(language)
    return facts


def search_shelfmark(
    config_data: ShelfmarkClientConfig,
    query: str,
    *,
    limit: int = DEFAULT_SHELFMARK_SEARCH_LIMIT,
) -> dict[str, Any]:
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return {
            "query": "",
            "results": [],
            "error": "",
            "total_found": 0,
            "searched": False,
        }

    client = ShelfmarkClient(config_data)
    payload = client.search_books(normalized_query, limit=limit)
    books = payload.get("books")
    if not isinstance(books, Sequence):
        raise ShelfmarkClientError(_("Shelfmark returned an unexpected metadata search response."))

    normalized_results = [dict(book) for book in books if isinstance(book, Mapping)]
    item_pairs = [
        (_normalize_text(book.get("provider")).lower(), _normalize_text(book.get("provider_id")))
        for book in normalized_results
        if _normalize_text(book.get("provider")) and _normalize_text(book.get("provider_id"))
    ]
    library_matches = find_library_matches(normalized_results)
    queue_rows = load_queue_rows_for_items(item_pairs)

    view_results: list[dict[str, Any]] = []
    for raw_result in normalized_results:
        key = build_shelfmark_item_key(raw_result.get("provider"), raw_result.get("provider_id"))
        if not key:
            continue
        authors = raw_result.get("authors")
        if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
            authors = [_normalize_text(raw_result.get("author"))] if _normalize_text(raw_result.get("author")) else []
        authors = [_normalize_text(author) for author in authors if _normalize_text(author)]
        raw_result["authors"] = authors
        library_match = library_matches.get(key)
        queue_summary = queue_rows.get(key)
        action = _action_for_result(raw_result, query=normalized_query, library_match=library_match, queue_summary=queue_summary)
        view_results.append(
            {
                "key": key,
                "provider": _normalize_text(raw_result.get("provider")).lower(),
                "provider_id": _normalize_text(raw_result.get("provider_id")),
                "title": _normalize_text(raw_result.get("title")),
                "subtitle": _normalize_text(raw_result.get("subtitle")),
                "authors": authors,
                "cover_url": _normalize_text(raw_result.get("cover_url")),
                "series_name": _normalize_text(raw_result.get("series_name")),
                "series_position": raw_result.get("series_position"),
                "facts": _build_result_facts(raw_result),
                "detail_url": url_for(
                    "shelfmark_search.book_detail",
                    provider=_normalize_text(raw_result.get("provider")).lower(),
                    provider_id=_normalize_text(raw_result.get("provider_id")),
                    query=normalized_query,
                ),
                "action": action,
                "queue_summary": queue_summary,
                "library_match": library_match,
            }
        )

    return {
        "query": normalized_query,
        "results": view_results,
        "error": "",
        "total_found": int(payload.get("total_found") or len(view_results)),
        "searched": True,
    }
