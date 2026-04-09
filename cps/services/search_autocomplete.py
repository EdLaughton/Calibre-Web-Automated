# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass

from flask import url_for
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import joinedload

from .. import calibre_db, config, db


PER_TYPE_LIMIT = 4
TOTAL_LIMIT = 9
FETCH_LIMIT = 8

ENTITY_PRIORITY = {
    "book": 0,
    "author": 1,
    "series": 2,
}

ICON_BY_TYPE = {
    "book": "book",
    "author": "user",
    "series": "th-list",
}


@dataclass(frozen=True)
class SuggestionEntry:
    entity_type: str
    entity_id: int
    primary_text: str
    secondary_text: str
    href: str
    match_rank: int
    sort_value: str


def _normalize(value):
    return (value or "").strip().lower()


def _match_rank(value, query):
    normalized_value = _normalize(value)
    if not normalized_value or not query:
        return None
    if normalized_value == query:
        return 0
    if normalized_value.startswith(query):
        return 1
    if query in normalized_value:
        return 2
    return None


def _series_context(series_name, series_index):
    if not series_name:
        return ""
    if series_index in (None, ""):
        return series_name
    try:
        formatted_index = "{:g}".format(float(series_index))
        return f"{series_name} #{formatted_index}"
    except (TypeError, ValueError):
        return series_name


def _author_text(authors):
    names = []
    for author in authors or []:
        name = getattr(author, "name", "")
        if name:
            names.append(name.replace("|", ","))
    return ", ".join(names)


def _book_secondary_text(book):
    parts = []
    ordered_authors = getattr(book, "ordered_authors", None) or getattr(book, "authors", [])
    authors = _author_text(ordered_authors)
    if authors:
        parts.append(authors)

    series_items = getattr(book, "series", None) or []
    if series_items:
        series_name = getattr(series_items[0], "name", "")
        series_context = _series_context(series_name, getattr(book, "series_index", None))
        if series_context:
            parts.append(series_context)
    return " | ".join(parts)


def build_suggestion_payload(query, books, authors, series, labels, per_type_limit=PER_TYPE_LIMIT, total_limit=TOTAL_LIMIT):
    normalized_query = _normalize(query)
    if not normalized_query:
        return {
            "query": query or "",
            "suggestions": [],
            "show_all": None,
        }

    suggestions = []
    type_counts = {
        "book": 0,
        "author": 0,
        "series": 0,
    }

    for book in books:
        title = getattr(book, "title", "") or ""
        rank = _match_rank(title, normalized_query)
        if rank is None or type_counts["book"] >= per_type_limit:
            continue
        suggestions.append(SuggestionEntry(
            entity_type="book",
            entity_id=int(book.id),
            primary_text=title,
            secondary_text=_book_secondary_text(book),
            href=url_for("web.show_book", book_id=int(book.id)),
            match_rank=rank,
            sort_value=_normalize(title),
        ))
        type_counts["book"] += 1

    for author, book_count in authors:
        name = getattr(author, "name", "") or ""
        rank = _match_rank(name, normalized_query)
        if rank is None or type_counts["author"] >= per_type_limit:
            continue
        secondary = labels["author_count_singular"] if int(book_count or 0) == 1 else labels["author_count_plural"] % {"count": int(book_count or 0)}
        suggestions.append(SuggestionEntry(
            entity_type="author",
            entity_id=int(author.id),
            primary_text=name.replace("|", ","),
            secondary_text=secondary,
            href=url_for("web.books_list", data="author", sort_param="stored", book_id=int(author.id)),
            match_rank=rank,
            sort_value=_normalize(name),
        ))
        type_counts["author"] += 1

    for series_entry, book_count in series:
        name = getattr(series_entry, "name", "") or ""
        rank = _match_rank(name, normalized_query)
        if rank is None or type_counts["series"] >= per_type_limit:
            continue
        secondary = labels["series_count_singular"] if int(book_count or 0) == 1 else labels["series_count_plural"] % {"count": int(book_count or 0)}
        suggestions.append(SuggestionEntry(
            entity_type="series",
            entity_id=int(series_entry.id),
            primary_text=name,
            secondary_text=secondary,
            href=url_for("web.books_list", data="series", sort_param="stored", book_id=int(series_entry.id)),
            match_rank=rank,
            sort_value=_normalize(name),
        ))
        type_counts["series"] += 1

    suggestions.sort(key=lambda item: (item.match_rank, ENTITY_PRIORITY[item.entity_type], item.sort_value))
    suggestions = suggestions[:total_limit]

    return {
        "query": query or "",
        "suggestions": [
            {
                "id": f"{item.entity_type}-{item.entity_id}",
                "type": item.entity_type,
                "label": labels[item.entity_type],
                "icon": ICON_BY_TYPE[item.entity_type],
                "primary_text": item.primary_text,
                "secondary_text": item.secondary_text,
                "href": item.href,
                "match_rank": item.match_rank,
            }
            for item in suggestions
        ],
        "show_all": {
            "label": labels["show_all"] % {"query": query or ""},
            "href": url_for("search.simple_search", query=(query or "")),
        },
    }


def _book_match_order(query):
    lowered_title = func.lower(db.Books.title)
    return case(
        (lowered_title == query, 0),
        (lowered_title.like(query + "%"), 1),
        else_=2,
    )


def _named_match_order(column, query):
    lowered_column = func.lower(column)
    return case(
        (lowered_column == query, 0),
        (lowered_column.like(query + "%"), 1),
        else_=2,
    )


def fetch_book_suggestions(query, limit=FETCH_LIMIT):
    normalized_query = _normalize(query)
    if not normalized_query:
        return []

    like_pattern = f"%{normalized_query}%"
    books = (
        calibre_db.session.query(db.Books)
        .options(joinedload(db.Books.authors), joinedload(db.Books.series))
        .filter(calibre_db.common_filters())
        .filter(func.lower(db.Books.title).ilike(like_pattern))
        .order_by(_book_match_order(normalized_query), func.lower(db.Books.title).asc())
        .limit(limit)
        .all()
    )
    return calibre_db.order_authors(books, list_return=True)


def fetch_author_suggestions(query, limit=FETCH_LIMIT):
    normalized_query = _normalize(query)
    if not normalized_query:
        return []

    like_pattern = f"%{normalized_query}%"
    return (
        calibre_db.session.query(
            db.Authors,
            func.count(distinct(db.Books.id)).label("book_count"),
        )
        .join(db.books_authors_link, db.Authors.id == db.books_authors_link.c.author)
        .join(db.Books, db.Books.id == db.books_authors_link.c.book)
        .filter(calibre_db.common_filters())
        .filter(func.lower(db.Authors.name).ilike(like_pattern))
        .group_by(db.Authors.id)
        .order_by(_named_match_order(db.Authors.name, normalized_query), func.lower(db.Authors.name).asc())
        .limit(limit)
        .all()
    )


def fetch_series_suggestions(query, limit=FETCH_LIMIT):
    normalized_query = _normalize(query)
    if not normalized_query:
        return []

    like_pattern = f"%{normalized_query}%"
    return (
        calibre_db.session.query(
            db.Series,
            func.count(distinct(db.Books.id)).label("book_count"),
        )
        .join(db.books_series_link, db.Series.id == db.books_series_link.c.series)
        .join(db.Books, db.Books.id == db.books_series_link.c.book)
        .filter(calibre_db.common_filters())
        .filter(func.lower(db.Series.name).ilike(like_pattern))
        .group_by(db.Series.id)
        .order_by(_named_match_order(db.Series.name, normalized_query), func.lower(db.Series.name).asc())
        .limit(limit)
        .all()
    )


def get_autocomplete_payload(query, labels):
    normalized_query = _normalize(query)
    if not normalized_query:
        return {
            "query": query or "",
            "suggestions": [],
            "show_all": None,
        }

    calibre_db.ensure_session()
    calibre_db.create_functions(config)

    books = fetch_book_suggestions(normalized_query)
    authors = fetch_author_suggestions(normalized_query)
    series = fetch_series_suggestions(normalized_query)
    return build_suggestion_payload(query, books, authors, series, labels)
