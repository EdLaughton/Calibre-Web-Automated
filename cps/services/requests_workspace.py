# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import time
from datetime import date, timedelta
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from flask import url_for
from flask_babel import gettext as _
from sqlalchemy.sql.expression import func, text

from cps import calibre_db, db, logger
from cps.services.hardcover import get_hardcover_client
from cps.services.shelfmark_search import (
    ShelfmarkResultView,
    apply_primary_series_context,
    build_owned_series_map,
    build_shelfmark_quality_state,
    build_shelfmark_result_view,
    build_shelfmark_series_membership_contexts,
    build_shelfmark_triage_state,
    get_shelfmark_client_config,
    lookup_visible_library_matches,
    lookup_visible_owned_series,
    search_shelfmark_contextual_results,
)


log = logger.create()

REQUESTS_SERIES_CONTEXT_LIMIT = 4
REQUESTS_AUTHOR_CONTEXT_LIMIT = 4
REQUESTS_DISCOVER_LIMIT = 12
REQUESTS_NEW_LIMIT = 12
REQUESTS_MAX_SERIES = 8
REQUESTS_MAX_AUTHORS = 8
REQUESTS_CONTEXT_RELEASE_LIMIT = 4
REQUESTS_CONTEXT_POPULAR_LIMIT = 3
REQUESTS_RECENT_WINDOW_DAYS = 180
REQUESTS_SECTION_CACHE_TTL_SECONDS = 60

_REQUESTS_SECTION_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}


@dataclass(frozen=True)
class RequestsOwnedSeriesSeed:
    key: str
    name: str
    book_count: int
    owned_positions: tuple[float, ...]
    max_position: float | None
    contiguous_position: int | None

    @property
    def has_gap(self) -> bool:
        if self.contiguous_position is None or self.max_position is None:
            return False
        return self.max_position > self.contiguous_position

    def hint(self) -> str:
        parts: list[str] = [
            _(
                "%(count)s books in your library",
                count=self.book_count,
            )
        ]
        if self.contiguous_position:
            parts.append(_("Owned through %(position)s", position=_format_position(self.contiguous_position)))
        return " \u00b7 ".join(parts)


@dataclass(frozen=True)
class RequestsOwnedAuthorSeed:
    author_id: int
    name: str
    book_count: int

    def hint(self) -> str:
        label = _("book") if self.book_count == 1 else _("books")
        return _("You already own %(count)s %(label)s by this author", count=self.book_count, label=label)


@dataclass(frozen=True)
class RequestsCandidate:
    key: str
    result: ShelfmarkResultView
    reason_label: str
    reason_detail: str | None = None
    reason_icon: str = "glyphicon glyphicon-book"
    source_kind: str = ""
    group_key: str | None = None
    group_title: str | None = None
    group_hint: str | None = None
    priority_bucket: str = "normal"
    sort_key: tuple[Any, ...] = field(default_factory=tuple)

    def to_template_dict(self) -> dict[str, Any]:
        result_payload = self.result.to_template_dict()
        result_payload["recommendation_reason_label"] = self.reason_label
        result_payload["recommendation_reason_detail"] = self.reason_detail
        result_payload["recommendation_reason_icon"] = self.reason_icon
        return {
            "key": self.key,
            "result": result_payload,
            "reason_label": self.reason_label,
            "reason_detail": self.reason_detail,
            "reason_icon": self.reason_icon,
            "source_kind": self.source_kind,
            "group_key": self.group_key,
            "group_title": self.group_title,
            "group_hint": self.group_hint,
            "priority_bucket": self.priority_bucket,
        }


@dataclass(frozen=True)
class RequestsGroup:
    key: str
    title: str
    hint: str | None = None
    candidates: tuple[RequestsCandidate, ...] = field(default_factory=tuple)

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "hint": self.hint,
            "count": len(self.candidates),
            "candidates": [candidate.to_template_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class RequestsSection:
    key: str
    title: str
    subtitle: str
    empty_message: str
    layout: str = "cards"
    compact: bool = False
    see_more_url: str | None = None
    candidates: tuple[RequestsCandidate, ...] = field(default_factory=tuple)
    groups: tuple[RequestsGroup, ...] = field(default_factory=tuple)

    @property
    def has_content(self) -> bool:
        return bool(self.candidates or self.groups)

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "empty_message": self.empty_message,
            "layout": self.layout,
            "compact": self.compact,
            "see_more_url": self.see_more_url,
            "has_content": self.has_content,
            "candidates": [candidate.to_template_dict() for candidate in self.candidates],
            "groups": [group.to_template_dict() for group in self.groups],
        }


@dataclass(frozen=True)
class RequestsSectionShell:
    key: str
    title: str
    subtitle: str
    empty_message: str
    load_url: str
    loading_message: str
    layout: str = "cards"
    compact: bool = False
    see_more_url: str | None = None

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "empty_message": self.empty_message,
            "load_url": self.load_url,
            "loading_message": self.loading_message,
            "layout": self.layout,
            "compact": self.compact,
            "see_more_url": self.see_more_url,
        }


@dataclass(frozen=True)
class RequestsWorkspaceView:
    enabled: bool
    active_view: str
    eyebrow: str
    title: str
    subtitle: str
    sections: tuple[RequestsSectionShell, ...] = field(default_factory=tuple)
    message: str | None = None

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "active_view": self.active_view,
            "eyebrow": self.eyebrow,
            "title": self.title,
            "subtitle": self.subtitle,
            "sections": [section.to_template_dict() for section in self.sections],
            "message": self.message,
        }


def _format_position(value: float | int | None) -> str:
    if value is None:
        return "?"
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def _result_key(result: ShelfmarkResultView) -> str:
    return result.hardcover_id or f"{result.provider}:{result.provider_id}"


def _detail_url_for_result(result: Mapping[str, Any], *, query: str, state_url: str | None) -> str | None:
    provider = str(result.get("provider") or "hardcover").strip()
    provider_id = str(result.get("provider_id") or result.get("id") or "").strip()
    if not provider_id:
        return None
    return url_for(
        "search.shelfmark_external_detail",
        provider=provider,
        provider_id=provider_id,
        query=query,
        return_to=state_url,
    )


def _result_popularity(result: ShelfmarkResultView) -> int:
    return int(result.readers_count or result.ratings_count or 0)


def _parse_release_date(raw_release_date: str | None) -> date | None:
    if not raw_release_date:
        return None
    try:
        return date.fromisoformat(str(raw_release_date).split("T", 1)[0])
    except ValueError:
        return None


def _resolve_release_date(
    result: ShelfmarkResultView,
    *,
    raw_release_date: str | None = None,
) -> date | None:
    return _parse_release_date(raw_release_date or result.release_date)


def _release_bucket_for_result(
    result: ShelfmarkResultView,
    *,
    raw_release_date: str | None = None,
    today: date | None = None,
) -> str | None:
    current_day = today or date.today()
    release_day = _resolve_release_date(result, raw_release_date=raw_release_date)
    if release_day is not None:
        if release_day >= current_day:
            return "upcoming"
        if release_day >= current_day - timedelta(days=REQUESTS_RECENT_WINDOW_DAYS):
            return "recent"
        return None
    if result.publish_year is None:
        return None
    if result.publish_year > current_day.year:
        return "upcoming"
    if result.publish_year == current_day.year:
        return "recent"
    return None


def _owned_series_seeds(limit: int = REQUESTS_MAX_SERIES) -> tuple[RequestsOwnedSeriesSeed, ...]:
    rows = (
        calibre_db.session.query(
            db.Series.name.label("series_name"),
            db.Books.id.label("book_id"),
            db.Books.series_index.label("series_position"),
        )
        .join(db.books_series_link, db.books_series_link.c.series == db.Series.id)
        .join(db.Books, db.books_series_link.c.book == db.Books.id)
        .filter(calibre_db.common_filters())
        .order_by(db.Series.name.asc(), db.Books.series_index.asc(), db.Books.id.asc())
        .all()
    )
    owned_series = build_owned_series_map(
        {
            "series_name": row.series_name,
            "book_id": row.book_id,
            "series_position": row.series_position,
        }
        for row in rows
    )
    ranked = sorted(
        owned_series.values(),
        key=lambda item: (
            0 if item.max_position and item.contiguous_position and item.max_position > item.contiguous_position else 1,
            -item.book_count,
            -(item.contiguous_position or 0),
            item.series_name.casefold(),
        ),
    )
    return tuple(
        RequestsOwnedSeriesSeed(
            key=item.key,
            name=item.series_name,
            book_count=item.book_count,
            owned_positions=item.owned_positions,
            max_position=item.max_position,
            contiguous_position=item.contiguous_position,
        )
        for item in ranked[: max(1, int(limit or REQUESTS_MAX_SERIES))]
    )


def _owned_author_seeds(limit: int = REQUESTS_MAX_AUTHORS) -> tuple[RequestsOwnedAuthorSeed, ...]:
    rows = (
        calibre_db.session.query(
            db.Authors.id.label("author_id"),
            db.Authors.name.label("author_name"),
            func.count(db.books_authors_link.c.book).label("book_count"),
        )
        .join(db.books_authors_link, db.Authors.id == db.books_authors_link.c.author)
        .join(db.Books, db.books_authors_link.c.book == db.Books.id)
        .filter(calibre_db.common_filters())
        .group_by(text("books_authors_link.author"))
        .order_by(func.count(db.books_authors_link.c.book).desc(), db.Authors.sort.asc())
        .all()
    )
    return tuple(
        RequestsOwnedAuthorSeed(
            author_id=int(row.author_id),
            name=(row.author_name or "").replace("|", ","),
            book_count=int(row.book_count or 0),
        )
        for row in rows[: max(1, int(limit or REQUESTS_MAX_AUTHORS))]
        if row.author_name
    )


def _is_missing_volume(seed: RequestsOwnedSeriesSeed, result: ShelfmarkResultView) -> bool:
    context = result.best_series_context or result.series_context
    return bool(context and context.is_next_missing and seed.has_gap)


def _is_next_in_series(seed: RequestsOwnedSeriesSeed, result: ShelfmarkResultView) -> bool:
    context = result.best_series_context or result.series_context
    if not context:
        return False
    if context.is_next_missing and not seed.has_gap:
        return True
    if context.is_continuation and not seed.has_gap:
        return True
    return False


def _gap_reason_detail(seed: RequestsOwnedSeriesSeed, result: ShelfmarkResultView) -> str:
    position = result.series_position or (result.best_series_context.series_position if result.best_series_context else None)
    if position is None:
        return _("Missing inside a series you already own")
    lower = [owned for owned in seed.owned_positions if owned < position]
    higher = [owned for owned in seed.owned_positions if owned > position]
    if lower and higher:
        return _(
            "Missing between volumes %(before)s and %(after)s",
            before=_format_position(max(lower)),
            after=_format_position(min(higher)),
        )
    if lower:
        return _("Missing after volume %(volume)s", volume=_format_position(max(lower)))
    return _("Missing volume in a series you already own")


def _next_reason_detail(seed: RequestsOwnedSeriesSeed) -> str:
    if seed.contiguous_position:
        return _(
            "Next after volume %(position)s in a series you own",
            position=_format_position(seed.contiguous_position),
        )
    return _("Continue a series you already own")


def _build_series_candidate(
    seed: RequestsOwnedSeriesSeed,
    result: ShelfmarkResultView,
    *,
    section_key: str,
) -> RequestsCandidate | None:
    if result.already_in_library:
        return None
    if _is_missing_volume(seed, result):
        reason_label = _("Missing volume")
        reason_detail = _gap_reason_detail(seed, result)
        priority_bucket = "critical"
        priority_order = 0
    elif _is_next_in_series(seed, result):
        reason_label = _("Next in series")
        reason_detail = _next_reason_detail(seed)
        priority_bucket = "high"
        priority_order = 1
    else:
        return None

    position_value = result.series_position if result.series_position is not None else float("inf")
    popularity_value = -(result.readers_count or result.ratings_count or 0)
    return RequestsCandidate(
        key=f"{section_key}:{seed.key}:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=reason_detail,
        reason_icon="glyphicon glyphicon-bookmark",
        source_kind="series",
        group_key=seed.key,
        group_title=seed.name,
        group_hint=seed.hint(),
        priority_bucket=priority_bucket,
        sort_key=(priority_order, -seed.book_count, position_value, popularity_value, result.title.casefold()),
    )


def _build_author_candidate(
    seed: RequestsOwnedAuthorSeed,
    result: ShelfmarkResultView,
) -> RequestsCandidate | None:
    if result.already_in_library:
        return None
    popularity = _result_popularity(result)
    return RequestsCandidate(
        key=f"authors-popular:{seed.author_id}:{_result_key(result)}",
        result=result,
        reason_label=_("Popular missing title"),
        reason_detail=seed.hint(),
        reason_icon="glyphicon glyphicon-user",
        source_kind="author",
        group_key=str(seed.author_id),
        group_title=seed.name,
        group_hint=seed.hint(),
        priority_bucket="high" if seed.book_count >= 3 else "normal",
        sort_key=(-seed.book_count, -(popularity or 0), result.title.casefold()),
    )


def _build_series_release_candidate(
    seed: RequestsOwnedSeriesSeed,
    result: ShelfmarkResultView,
    *,
    bucket: str,
) -> RequestsCandidate | None:
    if result.already_in_library:
        return None
    release_value = _release_sort_value(result.release_date, result.publish_year)
    popularity = _result_popularity(result)
    reason_label = _("Upcoming release") if bucket == "upcoming" else _("New release")
    sort_key = (
        -seed.book_count,
        release_value if bucket == "upcoming" else -(release_value or 0),
        -(popularity or 0),
        result.title.casefold(),
    )
    return RequestsCandidate(
        key=f"series-{bucket}:{seed.key}:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=_("Series you already own"),
        reason_icon="glyphicon glyphicon-bookmark",
        source_kind="series",
        group_key=seed.key,
        group_title=seed.name,
        group_hint=seed.hint(),
        priority_bucket="high" if bucket == "upcoming" else "normal",
        sort_key=sort_key,
    )


def _build_author_release_candidate(
    seed: RequestsOwnedAuthorSeed,
    result: ShelfmarkResultView,
    *,
    bucket: str,
) -> RequestsCandidate | None:
    if result.already_in_library:
        return None
    release_value = _release_sort_value(result.release_date, result.publish_year)
    popularity = _result_popularity(result)
    reason_label = _("Upcoming release") if bucket == "upcoming" else _("New release")
    sort_key = (
        -seed.book_count,
        release_value if bucket == "upcoming" else -(release_value or 0),
        -(popularity or 0),
        result.title.casefold(),
    )
    return RequestsCandidate(
        key=f"authors-{bucket}:{seed.author_id}:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=_("Author you already own"),
        reason_icon="glyphicon glyphicon-user",
        source_kind="author",
        group_key=str(seed.author_id),
        group_title=seed.name,
        group_hint=seed.hint(),
        priority_bucket="high" if bucket == "upcoming" else "normal",
        sort_key=sort_key,
    )


def _build_context_hot_candidate(
    result: ShelfmarkResultView,
    *,
    seed_name: str,
    seed_hint: str,
    source_kind: str,
    seed_key: str,
) -> RequestsCandidate | None:
    if result.already_in_library or not result.cover_url:
        return None
    popularity = _result_popularity(result)
    reason_label = (
        _("Hot from a series you own")
        if source_kind == "series"
        else _("Hot from an author you own")
    )
    return RequestsCandidate(
        key=f"hot-{source_kind}:{seed_key}:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=_("%(seed)s \u00b7 %(hint)s", seed=seed_name, hint=seed_hint),
        reason_icon="glyphicon glyphicon-fire",
        source_kind=source_kind,
        priority_bucket="high" if popularity >= 2500 else "normal",
        sort_key=(-(popularity or 0), seed_name.casefold(), result.title.casefold()),
    )


def _build_discover_candidate(result: ShelfmarkResultView, *, trending: bool) -> RequestsCandidate | None:
    if result.already_in_library or not result.cover_url:
        return None
    popularity = _result_popularity(result)
    reason_label = _("Trending now on Hardcover") if trending else _("Popular with Hardcover readers")
    reason_detail = (
        _("Popular now and not already in your library")
        if trending
        else _("Popular missing book with strong Hardcover activity")
    )
    return RequestsCandidate(
        key=f"hot-general:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=reason_detail,
        reason_icon="glyphicon glyphicon-fire",
        source_kind="discover",
        priority_bucket="normal",
        sort_key=(-(popularity or 0), result.title.casefold()),
    )


def _release_sort_value(raw_release_date: str | None, publish_year: int | None) -> int:
    if raw_release_date:
        try:
            return date.fromisoformat(str(raw_release_date).split("T", 1)[0]).toordinal()
        except ValueError:
            pass
    if publish_year:
        return date(int(publish_year), 1, 1).toordinal()
    return 0


def _build_new_candidate(
    result: ShelfmarkResultView,
    *,
    raw_release_date: str | None,
) -> RequestsCandidate | None:
    if result.already_in_library or not result.cover_url:
        return None
    bucket = _release_bucket_for_result(result, raw_release_date=raw_release_date)
    if bucket not in {"upcoming", "recent"}:
        return None
    popularity = _result_popularity(result)
    release_value = _release_sort_value(raw_release_date, result.publish_year)
    reason_label = _("Coming soon") if bucket == "upcoming" else _("New release")
    reason_detail = (
        _("High-signal upcoming book missing from your library")
        if bucket == "upcoming"
        else _("Recently released book missing from your library")
    )
    return RequestsCandidate(
        key=f"new-{bucket}:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=reason_detail,
        reason_icon="glyphicon glyphicon-time",
        source_kind="new",
        priority_bucket="normal",
        sort_key=(
            release_value if bucket == "upcoming" else -(release_value or 0),
            -(popularity or 0),
            result.title.casefold(),
        ),
    )


def _dedupe_candidates(
    candidates: Sequence[RequestsCandidate],
    *,
    limit: int | None = None,
) -> tuple[RequestsCandidate, ...]:
    seen: set[str] = set()
    deduped: list[RequestsCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.sort_key):
        identity = _result_key(candidate.result)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(candidate)
        if limit is not None and len(deduped) >= limit:
            break
    return tuple(deduped)


def _group_candidates(
    groups: dict[str, list[RequestsCandidate]],
    *,
    title_lookup: Mapping[str, str],
    hint_lookup: Mapping[str, str],
) -> tuple[RequestsGroup, ...]:
    ordered_groups: list[RequestsGroup] = []
    for key, candidates in groups.items():
        deduped = _dedupe_candidates(candidates)
        if not deduped:
            continue
        ordered_groups.append(
            RequestsGroup(
                key=key,
                title=title_lookup.get(key) or key,
                hint=hint_lookup.get(key),
                candidates=deduped,
            )
        )
    ordered_groups.sort(
        key=lambda group: (
            min((candidate.sort_key for candidate in group.candidates), default=(float("inf"),)),
            group.title.casefold(),
        )
    )
    return tuple(ordered_groups)


def _cache_value(cache_key: tuple[Any, ...], builder):
    now = time.monotonic()
    cached = _REQUESTS_SECTION_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    value = builder()
    _REQUESTS_SECTION_CACHE[cache_key] = (now + REQUESTS_SECTION_CACHE_TTL_SECONDS, value)
    return value


def _build_grouped_requests_section(
    *,
    key: str,
    title: str,
    subtitle: str,
    empty_message: str,
    groups: dict[str, list[RequestsCandidate]],
    title_lookup: Mapping[str, str],
    hint_lookup: Mapping[str, str],
) -> RequestsSection:
    return RequestsSection(
        key=key,
        title=title,
        subtitle=subtitle,
        empty_message=empty_message,
        layout="grouped",
        compact=True,
        groups=_group_candidates(groups, title_lookup=title_lookup, hint_lookup=hint_lookup),
    )


def _collect_series_bundle(
    *,
    state_url: str | None,
    max_series: int,
    relevance_limit: int,
    release_limit: int,
) -> dict[str, RequestsSection]:
    next_groups: dict[str, list[RequestsCandidate]] = {}
    missing_groups: dict[str, list[RequestsCandidate]] = {}
    upcoming_groups: dict[str, list[RequestsCandidate]] = {}
    new_groups: dict[str, list[RequestsCandidate]] = {}
    group_titles: dict[str, str] = {}
    group_hints: dict[str, str] = {}

    for seed in _owned_series_seeds(limit=max_series):
        group_titles[seed.key] = seed.name
        group_hints[seed.key] = seed.hint()

        relevance_section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, series_name=seed.name: _detail_url_for_result(
                book,
                query=series_name,
                state_url=state_url,
            ),
            context_type="series",
            context_value=seed.name,
            limit=relevance_limit * 2,
            sort="relevance",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if relevance_section.available and relevance_section.results:
            for result in relevance_section.results:
                candidate = _build_series_candidate(seed, result, section_key="series")
                if candidate is None:
                    continue
                target = missing_groups if candidate.reason_label == _("Missing volume") else next_groups
                target.setdefault(seed.key, []).append(candidate)

        release_section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, series_name=seed.name: _detail_url_for_result(
                book,
                query=series_name,
                state_url=state_url,
            ),
            context_type="series",
            context_value=seed.name,
            limit=release_limit,
            sort="newest",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not release_section.available or not release_section.results:
            continue
        for result in release_section.results:
            bucket = _release_bucket_for_result(result)
            if bucket not in {"upcoming", "recent"}:
                continue
            candidate = _build_series_release_candidate(seed, result, bucket=bucket)
            if candidate is None:
                continue
            target = upcoming_groups if bucket == "upcoming" else new_groups
            target.setdefault(seed.key, []).append(candidate)

    return {
        "series-next": _build_grouped_requests_section(
            key="series-next",
            title=_("Next in series"),
            subtitle=_("Likely continuations after the farthest point you already own."),
            empty_message=_("No likely next-in-series requests surfaced right now."),
            groups=next_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
        "series-missing": _build_grouped_requests_section(
            key="series-missing",
            title=_("Missing volumes"),
            subtitle=_("Gap fills inside series you already started."),
            empty_message=_("No missing-volume gaps surfaced right now."),
            groups=missing_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
        "series-upcoming": _build_grouped_requests_section(
            key="series-upcoming",
            title=_("Upcoming in your series"),
            subtitle=_("Forthcoming entries tied to series already in your library."),
            empty_message=_("No upcoming books in your series surfaced right now."),
            groups=upcoming_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
        "series-new-releases": _build_grouped_requests_section(
            key="series-new-releases",
            title=_("New releases in your series"),
            subtitle=_("Recently released books tied to series already in your library."),
            empty_message=_("No recent series releases surfaced right now."),
            groups=new_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
    }


def _collect_author_bundle(
    *,
    state_url: str | None,
    max_authors: int,
    popularity_limit: int,
    release_limit: int,
) -> dict[str, RequestsSection]:
    popular_groups: dict[str, list[RequestsCandidate]] = {}
    upcoming_groups: dict[str, list[RequestsCandidate]] = {}
    new_groups: dict[str, list[RequestsCandidate]] = {}
    group_titles: dict[str, str] = {}
    group_hints: dict[str, str] = {}

    for seed in _owned_author_seeds(limit=max_authors):
        group_key = str(seed.author_id)
        group_titles[group_key] = seed.name
        group_hints[group_key] = seed.hint()

        popular_section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, author_name=seed.name: _detail_url_for_result(
                book,
                query=author_name,
                state_url=state_url,
            ),
            context_type="author",
            context_value=seed.name,
            limit=popularity_limit,
            sort="popularity",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if popular_section.available and popular_section.results:
            for result in popular_section.results:
                candidate = _build_author_candidate(seed, result)
                if candidate is None:
                    continue
                popular_groups.setdefault(group_key, []).append(candidate)

        release_section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, author_name=seed.name: _detail_url_for_result(
                book,
                query=author_name,
                state_url=state_url,
            ),
            context_type="author",
            context_value=seed.name,
            limit=release_limit,
            sort="newest",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not release_section.available or not release_section.results:
            continue
        for result in release_section.results:
            bucket = _release_bucket_for_result(result)
            if bucket not in {"upcoming", "recent"}:
                continue
            candidate = _build_author_release_candidate(seed, result, bucket=bucket)
            if candidate is None:
                continue
            target = upcoming_groups if bucket == "upcoming" else new_groups
            target.setdefault(group_key, []).append(candidate)

    return {
        "authors-popular": _build_grouped_requests_section(
            key="authors-popular",
            title=_("More from authors you own"),
            subtitle=_("Notable missing works by authors already represented in your library."),
            empty_message=_("No author-led request candidates surfaced right now."),
            groups=popular_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
        "authors-upcoming": _build_grouped_requests_section(
            key="authors-upcoming",
            title=_("Upcoming from your authors"),
            subtitle=_("Forthcoming books by authors already in your library."),
            empty_message=_("No upcoming books from your authors surfaced right now."),
            groups=upcoming_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
        "authors-new-releases": _build_grouped_requests_section(
            key="authors-new-releases",
            title=_("New releases from your authors"),
            subtitle=_("Recently released books by authors already in your library."),
            empty_message=_("No recent releases from your authors surfaced right now."),
            groups=new_groups,
            title_lookup=group_titles,
            hint_lookup=group_hints,
        ),
    }


def _build_hardcover_result(book: Mapping[str, Any], *, state_url: str | None, detail_query: str) -> ShelfmarkResultView | None:
    hardcover_id = str(book.get("id") or "").strip()
    if not hardcover_id:
        return None
    enriched_book = dict(book)
    enriched_book.setdefault("provider", "hardcover")
    enriched_book.setdefault("provider_id", hardcover_id)
    library_match = lookup_visible_library_matches([hardcover_id]).get(hardcover_id)
    result = build_shelfmark_result_view(
        enriched_book,
        library_match=library_match,
        detail_url=_detail_url_for_result(
            enriched_book,
            query=detail_query,
            state_url=state_url,
        ),
        shelfmark_browser_base_url=get_shelfmark_client_config().browser_base_url,
    )
    owned_series = lookup_visible_owned_series(
        [membership.name for membership in result.series_memberships]
    )
    contexts = build_shelfmark_series_membership_contexts((result,), owned_series)[0]
    result = apply_primary_series_context(replace(result, series_contexts=contexts))
    result = replace(result, quality_state=build_shelfmark_quality_state(result))
    return replace(
        result,
        triage_state=build_shelfmark_triage_state(result, quality_state=result.quality_state),
    )


def _collect_hot_section(*, state_url: str | None, limit: int) -> RequestsSection:
    client = get_hardcover_client(load_privacy=False)
    if client is None:
        return RequestsSection(
            key="hot-general",
            title=_("Trending / popular now"),
            subtitle=_("Popular missing books worth considering next."),
            empty_message=_("Hardcover discovery data is unavailable right now."),
            layout="cards",
        )

    books: list[dict] = []
    trending = True
    try:
        books = client.list_trending_books(limit=limit)
    except Exception as exc:
        log.warning("Hardcover trending lookup failed for Requests workspace: %s", exc)
        books = []

    if not books:
        trending = False
        try:
            books = client.list_popular_books(limit=limit)
        except Exception as exc:
            log.warning("Hardcover popular-books lookup failed for Requests workspace: %s", exc)
            books = []

    candidates: list[RequestsCandidate] = []
    for book in books:
        result = _build_hardcover_result(
            book,
            state_url=state_url,
            detail_query=str(book.get("title") or ""),
        )
        if result is None:
            continue
        candidate = _build_discover_candidate(result, trending=trending)
        if candidate is None:
            continue
        candidates.append(candidate)

    return RequestsSection(
        key="hot-general",
        title=_("Trending / popular now"),
        subtitle=_("Popular missing books with strong Hardcover momentum."),
        empty_message=_("No trending or popular discovery candidates are available right now."),
        layout="cards",
        candidates=_dedupe_candidates(candidates, limit=limit),
    )


def _collect_hot_context_section(*, state_url: str | None, limit: int) -> RequestsSection:
    candidates: list[RequestsCandidate] = []

    for seed in _owned_series_seeds(limit=max(1, REQUESTS_MAX_SERIES // 2)):
        section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, series_name=seed.name: _detail_url_for_result(
                book,
                query=series_name,
                state_url=state_url,
            ),
            context_type="series",
            context_value=seed.name,
            limit=REQUESTS_CONTEXT_POPULAR_LIMIT,
            sort="popularity",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not section.available or not section.results:
            continue
        for result in section.results:
            candidate = _build_context_hot_candidate(
                result,
                seed_name=seed.name,
                seed_hint=seed.hint(),
                source_kind="series",
                seed_key=seed.key,
            )
            if candidate is not None:
                candidates.append(candidate)

    for seed in _owned_author_seeds(limit=max(1, REQUESTS_MAX_AUTHORS // 2)):
        section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, author_name=seed.name: _detail_url_for_result(
                book,
                query=author_name,
                state_url=state_url,
            ),
            context_type="author",
            context_value=seed.name,
            limit=REQUESTS_CONTEXT_POPULAR_LIMIT,
            sort="popularity",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not section.available or not section.results:
            continue
        for result in section.results:
            candidate = _build_context_hot_candidate(
                result,
                seed_name=seed.name,
                seed_hint=seed.hint(),
                source_kind="author",
                seed_key=str(seed.author_id),
            )
            if candidate is not None:
                candidates.append(candidate)

    return RequestsSection(
        key="hot-context",
        title=_("Hot from your authors and series"),
        subtitle=_("Popularity-led picks tied to authors and series already in your library."),
        empty_message=_("No strong popularity-led matches from your authors or series surfaced right now."),
        layout="cards",
        candidates=_dedupe_candidates(candidates, limit=limit),
    )


def _collect_new_sections(*, state_url: str | None, limit: int) -> dict[str, RequestsSection]:
    client = get_hardcover_client(load_privacy=False)
    if client is None:
        return {
            "new-upcoming": RequestsSection(
                key="new-upcoming",
                title=_("Upcoming you may like"),
                subtitle=_("High-signal forthcoming books from Hardcover."),
                empty_message=_("Hardcover discovery data is unavailable right now."),
                layout="cards",
            ),
            "new-releases": RequestsSection(
                key="new-releases",
                title=_("New releases you may like"),
                subtitle=_("Recently released books with strong Hardcover activity."),
                empty_message=_("Hardcover discovery data is unavailable right now."),
                layout="cards",
            ),
        }

    books: list[dict] = []
    try:
        books = client.list_popular_books(limit=max(limit * 4, limit))
    except Exception as exc:
        log.warning("Hardcover recent-books lookup failed for Requests workspace: %s", exc)
        books = []

    upcoming_candidates: list[RequestsCandidate] = []
    new_release_candidates: list[RequestsCandidate] = []
    for book in (book for book in books if isinstance(book, Mapping)):
        result = _build_hardcover_result(
            book,
            state_url=state_url,
            detail_query=str(book.get("title") or ""),
        )
        if result is None:
            continue
        candidate = _build_new_candidate(
            result,
            raw_release_date=book.get("release_date"),
        )
        if candidate is None:
            continue
        target = upcoming_candidates if candidate.key.startswith("new-upcoming:") else new_release_candidates
        target.append(candidate)

    return {
        "new-upcoming": RequestsSection(
            key="new-upcoming",
            title=_("Upcoming you may like"),
            subtitle=_("High-signal forthcoming books from Hardcover."),
            empty_message=_("No upcoming books worth watching surfaced right now."),
            layout="cards",
            candidates=_dedupe_candidates(upcoming_candidates, limit=limit),
        ),
        "new-releases": RequestsSection(
            key="new-releases",
            title=_("New releases you may like"),
            subtitle=_("Recently released books with strong Hardcover activity."),
            empty_message=_("No recent releases worth watching surfaced right now."),
            layout="cards",
            candidates=_dedupe_candidates(new_release_candidates, limit=limit),
        ),
    }


def _cached_series_bundle(*, state_url: str | None, cache_scope: Any) -> dict[str, RequestsSection]:
    return _cache_value(
        (
            "series-bundle",
            cache_scope,
            state_url,
            REQUESTS_MAX_SERIES,
            REQUESTS_SERIES_CONTEXT_LIMIT,
            REQUESTS_CONTEXT_RELEASE_LIMIT,
        ),
        lambda: _collect_series_bundle(
            state_url=state_url,
            max_series=REQUESTS_MAX_SERIES,
            relevance_limit=REQUESTS_SERIES_CONTEXT_LIMIT,
            release_limit=REQUESTS_CONTEXT_RELEASE_LIMIT,
        ),
    )


def _cached_author_bundle(*, state_url: str | None, cache_scope: Any) -> dict[str, RequestsSection]:
    return _cache_value(
        (
            "author-bundle",
            cache_scope,
            state_url,
            REQUESTS_MAX_AUTHORS,
            REQUESTS_AUTHOR_CONTEXT_LIMIT,
            REQUESTS_CONTEXT_RELEASE_LIMIT,
        ),
        lambda: _collect_author_bundle(
            state_url=state_url,
            max_authors=REQUESTS_MAX_AUTHORS,
            popularity_limit=REQUESTS_AUTHOR_CONTEXT_LIMIT,
            release_limit=REQUESTS_CONTEXT_RELEASE_LIMIT,
        ),
    )


def _cached_hot_section(*, state_url: str | None, cache_scope: Any, limit: int) -> RequestsSection:
    return _cache_value(
        ("hot-section", cache_scope, state_url, limit),
        lambda: _collect_hot_section(
            state_url=state_url,
            limit=limit,
        ),
    )


def _cached_hot_context_section(*, state_url: str | None, cache_scope: Any, limit: int) -> RequestsSection:
    return _cache_value(
        ("hot-context-section", cache_scope, state_url, limit, REQUESTS_CONTEXT_POPULAR_LIMIT),
        lambda: _collect_hot_context_section(
            state_url=state_url,
            limit=limit,
        ),
    )


def _cached_new_sections(*, state_url: str | None, cache_scope: Any, limit: int) -> dict[str, RequestsSection]:
    return _cache_value(
        ("new-sections", cache_scope, state_url, limit),
        lambda: _collect_new_sections(
            state_url=state_url,
            limit=limit,
        ),
    )


def normalize_requests_view(active_view: str | None) -> str:
    normalized_view = (active_view or "series").strip().lower()
    if normalized_view == "discover":
        return "hot"
    if normalized_view == "home":
        return "series"
    if normalized_view not in {"series", "authors", "hot", "new"}:
        return "series"
    return normalized_view


def _requests_state_url_for_view(active_view: str, state_url: str | None) -> str:
    if state_url:
        return state_url
    return url_for("web.requests_workspace_view", view_name=active_view)


def _requests_view_title(active_view: str) -> str:
    if active_view == "authors":
        return _("Authors")
    if active_view == "series":
        return _("Series")
    if active_view == "hot":
        return _("Hot")
    if active_view == "new":
        return _("New")
    return _("Requests")


def _requests_view_subtitle(active_view: str) -> str:
    if active_view == "authors":
        return _("Find more by authors you already own, including upcoming and newly released books.")
    if active_view == "series":
        return _("Continue the series you own, fill gaps, and catch upcoming or newly released entries.")
    if active_view == "hot":
        return _("Browse the strongest popularity-led requests, both broadly and from the library you already own.")
    if active_view == "new":
        return _("Focus on upcoming and newly released books, both broadly and within your authors and series.")
    return _("Browse requests shaped around the books you already own.")


def _build_section_shell(
    *,
    active_view: str,
    state_url: str,
    key: str,
    title: str,
    subtitle: str,
    empty_message: str,
    see_more_url: str | None = None,
    layout: str = "cards",
    compact: bool = False,
) -> RequestsSectionShell:
    return RequestsSectionShell(
        key=key,
        title=title,
        subtitle=subtitle,
        empty_message=empty_message,
        load_url=url_for(
            "web.requests_workspace_section",
            view_name=active_view,
            section_key=key,
            return_to=state_url,
        ),
        loading_message=_("Loading recommendations…"),
        layout=layout,
        compact=compact,
        see_more_url=see_more_url,
    )


def _build_section_shells(active_view: str, *, state_url: str) -> tuple[RequestsSectionShell, ...]:
    if active_view == "authors":
        return (
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="authors-popular",
                title=_("More from authors you own"),
                subtitle=_("Notable missing works by authors already represented in your library."),
                empty_message=_("No author-led request candidates surfaced right now."),
                layout="grouped",
                compact=True,
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="authors-upcoming",
                title=_("Upcoming from your authors"),
                subtitle=_("Forthcoming books by authors already in your library."),
                empty_message=_("No upcoming books from your authors surfaced right now."),
                layout="grouped",
                compact=True,
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="authors-new-releases",
                title=_("New releases from your authors"),
                subtitle=_("Recently released books by authors already in your library."),
                empty_message=_("No recent releases from your authors surfaced right now."),
                layout="grouped",
                compact=True,
            ),
        )
    if active_view == "series":
        return (
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="series-next",
                title=_("Next in series"),
                subtitle=_("Likely continuations after the farthest point you already own."),
                empty_message=_("No likely next-in-series requests surfaced right now."),
                layout="grouped",
                compact=True,
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="series-missing",
                title=_("Missing volumes"),
                subtitle=_("Gap fills inside series you already started."),
                empty_message=_("No missing-volume gaps surfaced right now."),
                layout="grouped",
                compact=True,
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="series-upcoming",
                title=_("Upcoming in your series"),
                subtitle=_("Forthcoming entries tied to series already in your library."),
                empty_message=_("No upcoming books in your series surfaced right now."),
                layout="grouped",
                compact=True,
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="series-new-releases",
                title=_("New releases in your series"),
                subtitle=_("Recently released books tied to series already in your library."),
                empty_message=_("No recent series releases surfaced right now."),
                layout="grouped",
                compact=True,
            ),
        )
    if active_view == "hot":
        return (
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="hot-general",
                title=_("Trending / popular now"),
                subtitle=_("Popular missing books with strong Hardcover momentum."),
                empty_message=_("No trending or popular discovery candidates are available right now."),
                layout="cards",
            ),
            _build_section_shell(
                active_view=active_view,
                state_url=state_url,
                key="hot-context",
                title=_("Hot from your authors and series"),
                subtitle=_("Popularity-led picks tied to authors and series already in your library."),
                empty_message=_("No strong popularity-led matches from your authors or series surfaced right now."),
                layout="cards",
            ),
        )
    return (
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="new-upcoming",
            title=_("Upcoming you may like"),
            subtitle=_("High-signal forthcoming books from Hardcover."),
            empty_message=_("No upcoming books worth watching surfaced right now."),
            layout="cards",
        ),
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="new-releases",
            title=_("New releases you may like"),
            subtitle=_("Recently released books with strong Hardcover activity."),
            empty_message=_("No recent releases worth watching surfaced right now."),
            layout="cards",
        ),
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="authors-upcoming",
            title=_("Upcoming from your authors"),
            subtitle=_("Forthcoming books by authors already in your library."),
            empty_message=_("No upcoming books from your authors surfaced right now."),
            layout="grouped",
            compact=True,
        ),
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="series-upcoming",
            title=_("Upcoming in your series"),
            subtitle=_("Forthcoming entries tied to series already in your library."),
            empty_message=_("No upcoming books in your series surfaced right now."),
            layout="grouped",
            compact=True,
        ),
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="authors-new-releases",
            title=_("New releases from your authors"),
            subtitle=_("Recently released books by authors already in your library."),
            empty_message=_("No recent releases from your authors surfaced right now."),
            layout="grouped",
            compact=True,
        ),
        _build_section_shell(
            active_view=active_view,
            state_url=state_url,
            key="series-new-releases",
            title=_("New releases in your series"),
            subtitle=_("Recently released books tied to series already in your library."),
            empty_message=_("No recent series releases surfaced right now."),
            layout="grouped",
            compact=True,
        ),
    )


def build_requests_section(active_view: str, section_key: str, *, state_url: str | None, cache_scope: Any = None) -> RequestsSection:
    normalized_view = normalize_requests_view(active_view)
    resolved_state_url = _requests_state_url_for_view(normalized_view, state_url)

    if normalized_view == "series":
        sections = _cached_series_bundle(
            state_url=resolved_state_url,
            cache_scope=cache_scope,
        )
        if section_key not in {"series-next", "series-missing", "series-upcoming", "series-new-releases"}:
            raise KeyError(section_key)
        return sections[section_key]

    if normalized_view == "authors":
        sections = _cached_author_bundle(
            state_url=resolved_state_url,
            cache_scope=cache_scope,
        )
        if section_key not in {"authors-popular", "authors-upcoming", "authors-new-releases"}:
            raise KeyError(section_key)
        return sections[section_key]

    if normalized_view == "hot":
        if section_key == "hot-general":
            return _cached_hot_section(
                state_url=resolved_state_url,
                cache_scope=cache_scope,
                limit=REQUESTS_DISCOVER_LIMIT,
            )
        if section_key == "hot-context":
            return _cached_hot_context_section(
                state_url=resolved_state_url,
                cache_scope=cache_scope,
                limit=REQUESTS_DISCOVER_LIMIT,
            )
        raise KeyError(section_key)
    if normalized_view == "new":
        if section_key in {"new-upcoming", "new-releases"}:
            return _cached_new_sections(
                state_url=resolved_state_url,
                cache_scope=cache_scope,
                limit=REQUESTS_NEW_LIMIT,
            )[section_key]
        if section_key in {"authors-upcoming", "authors-new-releases"}:
            return _cached_author_bundle(
                state_url=resolved_state_url,
                cache_scope=cache_scope,
            )[section_key]
        if section_key in {"series-upcoming", "series-new-releases"}:
            return _cached_series_bundle(
                state_url=resolved_state_url,
                cache_scope=cache_scope,
            )[section_key]
        raise KeyError(section_key)

    raise KeyError(section_key)


def build_requests_workspace(active_view: str, *, state_url: str | None) -> RequestsWorkspaceView:
    normalized_view = normalize_requests_view(active_view)
    resolved_state_url = _requests_state_url_for_view(normalized_view, state_url)

    if not get_shelfmark_client_config().enabled:
        return RequestsWorkspaceView(
            enabled=False,
            active_view=normalized_view,
            eyebrow=_("Requests"),
            title=_requests_view_title(normalized_view),
            subtitle=_requests_view_subtitle(normalized_view),
            sections=tuple(),
            message=_("Enable Shelfmark Search to use Requests."),
        )

    return RequestsWorkspaceView(
        enabled=True,
        active_view=normalized_view,
        eyebrow=_("Requests"),
        title=_requests_view_title(normalized_view),
        subtitle=_requests_view_subtitle(normalized_view),
        sections=_build_section_shells(normalized_view, state_url=resolved_state_url),
        message=None,
    )
