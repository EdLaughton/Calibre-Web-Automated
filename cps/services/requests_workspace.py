# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

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
REQUESTS_HOME_SECTION_LIMIT = 4
REQUESTS_DISCOVER_LIMIT = 12
REQUESTS_MAX_SERIES = 8
REQUESTS_MAX_AUTHORS = 8


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
class RequestsWorkspaceView:
    enabled: bool
    active_view: str
    title: str
    subtitle: str
    tabs: tuple[dict[str, Any], ...]
    sections: tuple[RequestsSection, ...] = field(default_factory=tuple)
    message: str | None = None

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "active_view": self.active_view,
            "title": self.title,
            "subtitle": self.subtitle,
            "tabs": [dict(tab) for tab in self.tabs],
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
    popularity = result.readers_count or result.ratings_count or 0
    return RequestsCandidate(
        key=f"author:{seed.author_id}:{_result_key(result)}",
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


def _build_discover_candidate(result: ShelfmarkResultView, *, trending: bool) -> RequestsCandidate | None:
    if result.already_in_library or not result.cover_url:
        return None
    popularity = result.readers_count or result.ratings_count or 0
    reason_label = _("Trending now on Hardcover") if trending else _("Popular with Hardcover readers")
    reason_detail = (
        _("Popular now and not already in your library")
        if trending
        else _("Popular missing book with strong Hardcover activity")
    )
    return RequestsCandidate(
        key=f"discover:{_result_key(result)}",
        result=result,
        reason_label=reason_label,
        reason_detail=reason_detail,
        reason_icon="glyphicon glyphicon-fire",
        source_kind="discover",
        priority_bucket="normal",
        sort_key=(-(popularity or 0), result.title.casefold()),
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


def _collect_series_sections(*, state_url: str | None, max_series: int, per_series_limit: int) -> tuple[RequestsSection, RequestsSection]:
    next_groups: dict[str, list[RequestsCandidate]] = {}
    missing_groups: dict[str, list[RequestsCandidate]] = {}
    group_titles: dict[str, str] = {}
    group_hints: dict[str, str] = {}
    for seed in _owned_series_seeds(limit=max_series):
        section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, series_name=seed.name: _detail_url_for_result(
                book,
                query=series_name,
                state_url=state_url,
            ),
            context_type="series",
            context_value=seed.name,
            limit=per_series_limit * 2,
            sort="relevance",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not section.available or not section.results:
            continue
        group_titles[seed.key] = seed.name
        group_hints[seed.key] = seed.hint()
        for result in section.results:
            candidate = _build_series_candidate(seed, result, section_key="series")
            if candidate is None:
                continue
            target = missing_groups if candidate.reason_label == _("Missing volume") else next_groups
            target.setdefault(seed.key, []).append(candidate)

    next_section = RequestsSection(
        key="series-next",
        title=_("Next in series"),
        subtitle=_("Likely next books after the series you already own."),
        empty_message=_("No likely next-in-series request candidates surfaced right now."),
        layout="grouped",
        compact=True,
        groups=_group_candidates(next_groups, title_lookup=group_titles, hint_lookup=group_hints),
    )
    missing_section = RequestsSection(
        key="series-missing",
        title=_("Missing volumes"),
        subtitle=_("Gap fills inside series you already started."),
        empty_message=_("No missing-volume gaps surfaced right now."),
        layout="grouped",
        compact=True,
        groups=_group_candidates(missing_groups, title_lookup=group_titles, hint_lookup=group_hints),
    )
    return next_section, missing_section


def _collect_author_section(*, state_url: str | None, max_authors: int, per_author_limit: int) -> RequestsSection:
    author_groups: dict[str, list[RequestsCandidate]] = {}
    group_titles: dict[str, str] = {}
    group_hints: dict[str, str] = {}
    for seed in _owned_author_seeds(limit=max_authors):
        section = search_shelfmark_contextual_results(
            seed.name,
            detail_url_builder=lambda book, author_name=seed.name: _detail_url_for_result(
                book,
                query=author_name,
                state_url=state_url,
            ),
            context_type="author",
            context_value=seed.name,
            limit=per_author_limit,
            sort="popularity",
            filter_requestable=True,
            filter_has_cover=True,
            query_label=seed.name,
        )
        if not section.available or not section.results:
            continue
        group_key = str(seed.author_id)
        group_titles[group_key] = seed.name
        group_hints[group_key] = seed.hint()
        for result in section.results:
            candidate = _build_author_candidate(seed, result)
            if candidate is None:
                continue
            author_groups.setdefault(group_key, []).append(candidate)

    return RequestsSection(
        key="authors",
        title=_("More from authors you own"),
        subtitle=_("Notable missing works by authors already represented in your library."),
        empty_message=_("No author-led request candidates surfaced right now."),
        layout="grouped",
        compact=True,
        groups=_group_candidates(author_groups, title_lookup=group_titles, hint_lookup=group_hints),
    )


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


def _collect_discover_section(*, state_url: str | None, limit: int) -> RequestsSection:
    client = get_hardcover_client(load_privacy=False)
    if client is None:
        return RequestsSection(
            key="discover",
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
        key="discover",
        title=_("Trending / popular now"),
        subtitle=_("Popular missing books with strong Hardcover momentum."),
        empty_message=_("No trending or popular discovery candidates are available right now."),
        layout="cards",
        candidates=_dedupe_candidates(candidates, limit=limit),
    )


def _limit_grouped_candidates(groups: Sequence[RequestsGroup], *, limit: int) -> tuple[RequestsCandidate, ...]:
    flattened = [candidate for group in groups for candidate in group.candidates]
    return _dedupe_candidates(flattened, limit=limit)


def _build_home_sections(*, state_url: str | None) -> tuple[RequestsSection, ...]:
    next_section, missing_section = _collect_series_sections(
        state_url=state_url,
        max_series=REQUESTS_MAX_SERIES,
        per_series_limit=REQUESTS_SERIES_CONTEXT_LIMIT,
    )
    authors_section = _collect_author_section(
        state_url=state_url,
        max_authors=REQUESTS_MAX_AUTHORS,
        per_author_limit=REQUESTS_AUTHOR_CONTEXT_LIMIT,
    )
    discover_section = _collect_discover_section(
        state_url=state_url,
        limit=REQUESTS_DISCOVER_LIMIT,
    )

    home_seen: set[str] = set()

    def pick(section: RequestsSection, *, limit: int) -> tuple[RequestsCandidate, ...]:
        selected: list[RequestsCandidate] = []
        source = section.candidates or _limit_grouped_candidates(section.groups, limit=limit * 2)
        for candidate in source:
            identity = _result_key(candidate.result)
            if identity in home_seen:
                continue
            home_seen.add(identity)
            selected.append(candidate)
            if len(selected) >= limit:
                break
        return tuple(selected)

    return (
        RequestsSection(
            key="home-next",
            title=_("Continue series"),
            subtitle=_("Likely next books to keep your current series moving."),
            empty_message=_("No series continuations surfaced right now."),
            layout="cards",
            see_more_url=url_for("web.requests_workspace_view", view_name="series"),
            candidates=pick(next_section, limit=REQUESTS_HOME_SECTION_LIMIT),
        ),
        RequestsSection(
            key="home-missing",
            title=_("Missing volumes"),
            subtitle=_("Gap fills inside series you already care about."),
            empty_message=_("No missing-volume gap fills surfaced right now."),
            layout="cards",
            see_more_url=url_for("web.requests_workspace_view", view_name="series"),
            candidates=pick(missing_section, limit=REQUESTS_HOME_SECTION_LIMIT),
        ),
        RequestsSection(
            key="home-authors",
            title=_("More from authors you own"),
            subtitle=_("Popular missing books by authors already represented locally."),
            empty_message=_("No author-led expansions surfaced right now."),
            layout="cards",
            see_more_url=url_for("web.requests_workspace_view", view_name="authors"),
            candidates=pick(authors_section, limit=REQUESTS_HOME_SECTION_LIMIT),
        ),
        RequestsSection(
            key="home-discover",
            title=_("Trending / popular now"),
            subtitle=_("High-signal discovery candidates beyond your current shelves."),
            empty_message=_("No trending or popular discovery candidates surfaced right now."),
            layout="cards",
            see_more_url=url_for("web.requests_workspace_view", view_name="discover"),
            candidates=pick(discover_section, limit=REQUESTS_HOME_SECTION_LIMIT),
        ),
    )


def _build_tabs(active_view: str) -> tuple[dict[str, Any], ...]:
    tabs = (
        ("home", _("Home")),
        ("series", _("Series")),
        ("authors", _("Authors")),
        ("discover", _("Discover")),
    )
    return tuple(
        {
            "key": key,
            "label": label,
            "url": url_for("web.requests_workspace_view", view_name=key) if key != "home" else url_for("web.requests_workspace"),
            "active": key == active_view,
        }
        for key, label in tabs
    )


def build_requests_workspace(active_view: str, *, state_url: str | None) -> RequestsWorkspaceView:
    normalized_view = (active_view or "home").strip().lower()
    if normalized_view not in {"home", "series", "authors", "discover"}:
        normalized_view = "home"

    if not get_shelfmark_client_config().enabled:
        return RequestsWorkspaceView(
            enabled=False,
            active_view=normalized_view,
            title=_("Requests"),
            subtitle=_("Find likely next additions from the series and authors you already care about."),
            tabs=_build_tabs(normalized_view),
            sections=tuple(),
            message=_("Enable Shelfmark Search to use Requests."),
        )

    if normalized_view == "series":
        sections = _collect_series_sections(
            state_url=state_url,
            max_series=REQUESTS_MAX_SERIES,
            per_series_limit=REQUESTS_SERIES_CONTEXT_LIMIT,
        )
        subtitle = _("Track likely next entries and missing gaps across the series you already own.")
    elif normalized_view == "authors":
        sections = (
            _collect_author_section(
                state_url=state_url,
                max_authors=REQUESTS_MAX_AUTHORS,
                per_author_limit=REQUESTS_AUTHOR_CONTEXT_LIMIT,
            ),
        )
        subtitle = _("Surface notable missing books by authors already represented in your library.")
    elif normalized_view == "discover":
        sections = (
            _collect_discover_section(
                state_url=state_url,
                limit=REQUESTS_DISCOVER_LIMIT,
            ),
        )
        subtitle = _("Browse popular missing books worth adding next.")
    else:
        sections = _build_home_sections(state_url=state_url)
        subtitle = _("Find likely next additions from the series and authors you already care about.")

    return RequestsWorkspaceView(
        enabled=True,
        active_view=normalized_view,
        title=_("Requests"),
        subtitle=subtitle,
        tabs=_build_tabs(normalized_view),
        sections=tuple(section for section in sections if section is not None),
        message=None,
    )
