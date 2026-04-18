# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Mapping

from flask import request, url_for
from flask_babel import gettext as _

from .services.shelfmark_search import (
    DEFAULT_SHELFMARK_CONTEXTUAL_LIMIT,
    DEFAULT_SHELFMARK_FILTER_HAS_COVER,
    DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
    DEFAULT_SHELFMARK_SERIES_FILTER,
    DEFAULT_SHELFMARK_SORT,
    fetch_shelfmark_detail,
    get_shelfmark_client_config,
    get_shelfmark_preferred_release_settings,
    result_matches_shelfmark_filters,
    search_shelfmark_contextual_results,
    search_shelfmark_results,
)

DEFAULT_CONTEXTUAL_ASYNC_BATCH_SIZE = DEFAULT_SHELFMARK_CONTEXTUAL_LIMIT


def search_page_has_shell(section):
    if not section or not section.get("enabled"):
        return False
    result_count = len(section.get("results") or [])
    return bool(
        result_count > 0
        or section.get("raw_total_available")
        or section.get("total_available")
        or section.get("has_more")
        or section.get("next_page")
        or section.get("page_result_count")
    )


def apply_shelfmark_render_state(section):
    if not section:
        return section

    is_search = section.get("variant") == "search"
    has_results = bool(section.get("results"))
    has_page_shell = search_page_has_shell(section) if is_search else has_results

    section["has_page_shell"] = has_page_shell
    section["render_modal"] = has_page_shell
    section["render_scripts"] = has_page_shell
    return section


def safe_local_return_url(value):
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return None
    return candidate


def current_request_params(*, include_transient=True):
    params = request.args.to_dict(flat=True)
    if include_transient:
        return params
    params.pop("shelfmark_series_filter", None)
    for key in (
        "shelfmark_detail_provider",
        "shelfmark_detail_id",
        "shelfmark_filter_high_confidence",
        "shelfmark_triage_filter",
    ):
        params.pop(key, None)
    return params


def request_url_for_params(params):
    if not params:
        return url_for(request.endpoint, **(request.view_args or {}))
    return url_for(request.endpoint, **(request.view_args or {}), **params)


def current_request_path(*, include_transient=True):
    return request_url_for_params(current_request_params(include_transient=include_transient))


def current_shelfmark_state_url():
    return current_request_path(include_transient=False)


def requested_shelfmark_page():
    try:
        page = int(request.args.get("shelfmark_page", "1"))
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def requested_shelfmark_page_size():
    try:
        page_size = int(request.args.get("shelfmark_page_size", "12"))
    except (TypeError, ValueError):
        return 12
    return page_size if page_size > 0 else 12


def requested_shelfmark_sort():
    return (request.args.get("shelfmark_sort", DEFAULT_SHELFMARK_SORT) or DEFAULT_SHELFMARK_SORT).strip().lower()


def requested_shelfmark_flag(name, default=False):
    values = request.args.getlist(name)
    if not values:
        return default
    return (values[-1] or "").strip().lower() in {"1", "true", "yes", "on"}


def current_request_url_with(**updates):
    params = current_request_params(include_transient=False)
    params.update({key: str(value) for key, value in updates.items() if value not in (None, "")})
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
    return request_url_for_params(params)


def build_shelfmark_detail_url(book, *, query, return_to=None):
    provider = (book or {}).get("provider")
    provider_id = (book or {}).get("provider_id")
    if not provider or not provider_id:
        return None
    return url_for(
        "search.shelfmark_external_detail",
        provider=provider,
        provider_id=provider_id,
        query=query,
        return_to=safe_local_return_url(return_to),
    )


def build_shelfmark_row_enrichment_url(book, *, query, return_to=None):
    provider = (book or {}).get("provider")
    provider_id = (book or {}).get("provider_id")
    if not provider or not provider_id:
        return None

    params = current_request_params(include_transient=False)
    params["query"] = query
    safe_return_to = safe_local_return_url(return_to)
    if safe_return_to:
        params["return_to"] = safe_return_to
    else:
        params.pop("return_to", None)
    return url_for(
        "search.shelfmark_external_row",
        provider=provider,
        provider_id=provider_id,
        **params,
    )


def build_shelfmark_top_up_url(*, query, return_to=None):
    params = current_request_params(include_transient=False)
    params["query"] = query
    params.pop("shelfmark_source_page", None)
    safe_return_to = safe_local_return_url(return_to)
    if safe_return_to:
        params["return_to"] = safe_return_to
    else:
        params.pop("return_to", None)
    return url_for("search.shelfmark_external_topup", **params)


def build_shelfmark_result_row_class_name(result):
    library_state = result.get("library_state") or {}
    classes = [
        "shelfmark-result-card",
        "js-shelfmark-result-row",
        "shelfmark-result-card--%s" % (library_state.get("row_class") or "info"),
    ]
    if result.get("workflow_state") and not result.get("already_in_library"):
        classes.append("js-shelfmark-status-target")
    if result.get("request_payload") and not result.get("already_in_library"):
        classes.append("js-shelfmark-batch-row")
    if result.get("needs_progressive_enrichment"):
        classes.append("js-shelfmark-progressive-row")
    if result.get("needs_progressive_enrichment") or result.get("progressive_filter_pending"):
        classes.append("shelfmark-result-card--refining")
    return " ".join(classes)


def populate_shelfmark_row_state(result):
    result["row_class_name"] = build_shelfmark_result_row_class_name(result)
    result["row_status_provider"] = (
        "hardcover"
        if result.get("workflow_state") and not result.get("already_in_library")
        else ""
    )
    result["row_status_provider_id"] = result.get("hardcover_id") or ""
    result["row_status_in_library"] = "1" if result.get("already_in_library") else "0"
    result["row_has_cover"] = "1" if result.get("cover_url") else "0"


def decorate_shelfmark_result_rows(section, *, query, enable_progressive_enrichment):
    results = section.get("results") or []
    state_url = section.get("state_url")
    for index, result in enumerate(results):
        result["row_index"] = index
        populate_shelfmark_row_state(result)
        result["row_enrichment_url"] = (
            build_shelfmark_row_enrichment_url(
                result,
                query=query,
                return_to=state_url,
            )
            if enable_progressive_enrichment and result.get("needs_progressive_enrichment")
            else None
        )


def _display_page_has_possible_next(section, display_page, page_size):
    raw_total = section.get("raw_total_available") or section.get("total_available") or 0
    if raw_total and raw_total > (display_page * page_size):
        return True
    return bool(section.get("has_more"))


def build_search_page_shelfmark_section(query, **kwargs):
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    display_page = requested_shelfmark_page()
    requested_page_size = requested_shelfmark_page_size()
    section = search_shelfmark_results(
        query,
        page=1,
        page_size=requested_page_size,
        sort=requested_shelfmark_sort(),
        series_filter=DEFAULT_SHELFMARK_SERIES_FILTER,
        filter_requestable=requested_shelfmark_flag(
            "shelfmark_filter_requestable",
            default=DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
        ),
        filter_has_cover=requested_shelfmark_flag(
            "shelfmark_filter_has_cover",
            default=DEFAULT_SHELFMARK_FILTER_HAS_COVER,
        ),
        **kwargs,
    ).to_template_dict()
    if not section.get("enabled"):
        return section

    section["variant"] = "search"
    section["section_title"] = _("Shelfmark Results")
    section["section_subtitle"] = (
        _("Request-ready matches from Shelfmark.")
        if section.get("filter_requestable")
        else _("Additional matches from Shelfmark.")
    )
    section["source_page"] = 1
    section["source_next_page"] = section.get("next_page")
    section["source_total_pages"] = section.get("total_pages")
    section["page"] = display_page
    section["page_size"] = requested_page_size
    section["previous_page"] = display_page - 1 if display_page > 1 else None
    section["has_previous"] = bool(section["previous_page"])
    section["next_page"] = (
        display_page + 1
        if _display_page_has_possible_next(section, display_page, requested_page_size)
        else None
    )
    section["total_pages"] = 0
    section["state_url"] = current_request_url_with(
        shelfmark_page=section.get("page") or 1,
        shelfmark_page_size=section.get("page_size") or 12,
        shelfmark_sort=section.get("selected_sort"),
        shelfmark_filter_requestable="1" if section.get("filter_requestable") else "0",
        shelfmark_filter_has_cover="1" if section.get("filter_has_cover") else "0",
    )
    previous_page = section.get("previous_page")
    next_page = section.get("next_page")
    section["previous_page_url"] = (
        current_request_url_with(shelfmark_page=previous_page)
        if previous_page
        else None
    )
    section["next_page_url"] = (
        current_request_url_with(shelfmark_page=next_page)
        if next_page
        else None
    )
    section["clear_filters_url"] = current_request_url_with(
        shelfmark_page=1,
        shelfmark_sort=None,
        shelfmark_filter_requestable=None,
        shelfmark_filter_has_cover=None,
    )
    section["top_up_url"] = build_shelfmark_top_up_url(
        query=query,
        return_to=section.get("state_url"),
    )
    section["preferred_release_settings"] = preferred_release
    decorate_shelfmark_result_rows(
        section,
        query=query,
        enable_progressive_enrichment=True,
    )
    return apply_shelfmark_render_state(section)


def shelfmark_contextual_enabled():
    return bool(get_shelfmark_client_config().enabled)


def build_contextual_shelfmark_runtime():
    enabled = shelfmark_contextual_enabled()
    return {
        "enabled": enabled,
        "render_modal": enabled,
        "render_scripts": enabled,
        "state_url": current_request_path(include_transient=False),
    }


def build_contextual_shelfmark_loader(initial_url, *, context_type):
    if not initial_url:
        return None
    return {
        "context_type": context_type,
        "container_id": f"shelfmark-contextual-{context_type}",
        "initial_url": initial_url,
        "loading_message": _("Loading Shelfmark results…"),
        "failure_message": _("Shelfmark is unavailable right now."),
        "load_more_failure_message": _("Could not load more Shelfmark results right now."),
    }


def _slice_contextual_section_results(section, *, query, offset, limit):
    results = list(section.get("results") or [])
    batch_results = results[offset:offset + limit]
    section["results"] = batch_results
    section["page"] = 1
    section["page_size"] = limit
    section["page_result_count"] = len(batch_results)
    section["offset"] = offset
    section["variant"] = "contextual"
    section["has_page_shell"] = bool(batch_results)
    section["render_modal"] = False
    section["render_scripts"] = False
    decorate_shelfmark_result_rows(
        section,
        query=query,
        enable_progressive_enrichment=False,
    )
    for index, result in enumerate(section.get("results") or []):
        result["row_index"] = offset + index
    return section


def build_contextual_shelfmark_section_page(
    query,
    *,
    context_type,
    context_value,
    section_title,
    section_subtitle,
    endpoint_name,
    endpoint_kwargs,
    state_url=None,
    offset=0,
    limit=DEFAULT_CONTEXTUAL_ASYNC_BATCH_SIZE,
    sort="relevance",
    empty_message=None,
):
    contextual_limit = max(1, int(limit or DEFAULT_CONTEXTUAL_ASYNC_BATCH_SIZE))
    requested_offset = max(0, int(offset or 0))
    requested_total = requested_offset + contextual_limit
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    return_to = safe_local_return_url(state_url) or current_request_path(include_transient=False)
    section = search_shelfmark_contextual_results(
        query,
        detail_url_builder=lambda book: build_shelfmark_detail_url(
            book,
            query=query,
            return_to=return_to,
        ),
        context_type=context_type,
        context_value=context_value,
        limit=requested_total,
        sort=sort,
        filter_requestable=True,
        filter_has_cover=True,
        empty_message=empty_message,
    ).to_template_dict()

    if not section.get("enabled"):
        return None

    section["section_title"] = section_title
    section["section_subtitle"] = section_subtitle
    section["state_url"] = return_to
    section["preferred_release_settings"] = preferred_release
    section = _slice_contextual_section_results(
        section,
        query=query,
        offset=requested_offset,
        limit=contextual_limit,
    )
    remaining_results = requested_offset + len(section.get("results") or [])
    has_more = bool(section.get("has_more"))
    section["has_more_contextual"] = has_more
    section["next_offset"] = remaining_results if has_more else None
    section["load_more_url"] = (
        url_for(endpoint_name, offset=remaining_results, append=1, return_to=return_to, **endpoint_kwargs)
        if has_more
        else None
    )
    if not section.get("available") and not section.get("message"):
        section["message"] = _("Shelfmark is unavailable right now.")
    return section


def build_author_contextual_shelfmark_section_page(author_name, *, author_id, state_url=None, offset=0):
    return build_contextual_shelfmark_section_page(
        author_name,
        context_type="author",
        context_value=author_name,
        section_title=_("Shelfmark"),
        section_subtitle=_("Missing most popular requestable books by this author from Shelfmark"),
        endpoint_name="web.author_shelfmark_section",
        endpoint_kwargs={"author_id": author_id},
        state_url=state_url,
        offset=offset,
        sort="popularity",
    )


def build_series_contextual_shelfmark_section_page(series_name, *, series_id, state_url=None, offset=0):
    return build_contextual_shelfmark_section_page(
        series_name,
        context_type="series",
        context_value=series_name,
        section_title=_("Shelfmark"),
        section_subtitle=_("Missing requestable books for this series from Shelfmark"),
        endpoint_name="web.series_shelfmark_section",
        endpoint_kwargs={"series_id": series_id},
        state_url=state_url,
        offset=offset,
    )


def build_shelfmark_row_response(result_view, *, preferred_release, requestable_only, has_cover_only):
    result = result_view.to_template_dict()
    populate_shelfmark_row_state(result)
    result["needs_progressive_enrichment"] = False
    result["progressive_filter_pending"] = False
    return {
        "ok": True,
        "matches_filters": result_matches_shelfmark_filters(
            result_view,
            requestable_only=requestable_only,
            has_cover_only=has_cover_only,
            series_filter=DEFAULT_SHELFMARK_SERIES_FILTER,
        ),
        "row_class_name": result["row_class_name"],
        "row_status_provider": result["row_status_provider"],
        "row_status_provider_id": result["row_status_provider_id"],
        "row_status_in_library": result["row_status_in_library"],
        "row_has_cover": result["row_has_cover"],
        "library_book_url": result.get("library_book_url"),
        "library_book_title": result.get("library_book_title"),
        "preferred_release": preferred_release,
        "result": result,
    }


def build_shelfmark_top_up_rows(section, *, preferred_release):
    rows = []
    for result in section.get("results") or []:
        rows.append(
            {
                "provider": result.get("provider") or "",
                "provider_id": result.get("provider_id") or "",
                "row_class_name": result.get("row_class_name") or "",
                "row_status_provider": result.get("row_status_provider") or "",
                "row_status_provider_id": result.get("row_status_provider_id") or "",
                "row_status_in_library": result.get("row_status_in_library") or "0",
                "row_has_cover": result.get("row_has_cover") or "0",
                "library_book_url": result.get("library_book_url"),
                "library_book_title": result.get("library_book_title"),
                "row_enrichment_url": result.get("row_enrichment_url") or "",
                "preferred_release": preferred_release,
                "result": result,
            }
        )
    return rows
