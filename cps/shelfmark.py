# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, abort, flash, jsonify, redirect, request, url_for
from flask_babel import gettext as _

from .cw_login import current_user
from .render_template import render_title_template
from .services.shelfmark_client import (
    ShelfmarkClientError,
    build_shelfmark_item_key,
    get_shelfmark_client_config,
)
from .services.shelfmark_details import get_shelfmark_detail_view
from .services.shelfmark_queue import load_visible_queue_status, submit_shelfmark_request
from .services.shelfmark_search import search_shelfmark
from .usermanagement import login_required_if_no_ano

shelfmark_search = Blueprint("shelfmark_search", __name__)


def _safe_local_return_to(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return url_for("shelfmark_search.search_page")
    return candidate


def _feature_enabled() -> bool:
    config_data = get_shelfmark_client_config()
    return config_data.enabled and bool(config_data.base_url)


def _current_username() -> str:
    return getattr(current_user, "name", None) or getattr(current_user, "nickname", None) or "Unknown"


def _current_user_id() -> int | None:
    try:
        user_id = getattr(current_user, "id", None)
        return int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


def _is_xhr_request() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _redirect_query_args() -> dict[str, str]:
    return {
        key: value
        for key, value in request.args.items()
        if isinstance(key, str) and isinstance(value, str)
    }


@shelfmark_search.route("/request", methods=["GET"])
@login_required_if_no_ano
def search_page():
    if not _feature_enabled():
        abort(404)

    query = (request.args.get("query") or "").strip()
    error_message = ""
    results_payload = {
        "query": query,
        "results": [],
        "error": "",
        "total_found": 0,
        "searched": False,
    }
    if query:
        try:
            results_payload = search_shelfmark(get_shelfmark_client_config(), query)
        except ShelfmarkClientError as exc:
            error_message = str(exc)
            results_payload["searched"] = True

    return render_title_template(
        "shelfmark_search.html",
        title=_("Request Book"),
        page="request",
        query=query,
        shelfmark_results=results_payload["results"],
        shelfmark_error=error_message,
        shelfmark_total_found=results_payload["total_found"],
        shelfmark_searched=results_payload["searched"],
        is_xhr=_is_xhr_request(),
    )


@shelfmark_search.route("/request/queue", methods=["POST"])
@login_required_if_no_ano
def submit_request():
    if not _feature_enabled():
        abort(404)

    request_payload = request.form.get("request_payload", "")
    return_to = _safe_local_return_to(request.form.get("return_to"))
    try:
        payload = json.loads(request_payload)
    except (TypeError, ValueError):
        flash(_("Shelfmark request payload was invalid."), category="error")
        return redirect(return_to)

    try:
        result = submit_shelfmark_request(
            get_shelfmark_client_config(),
            payload,
            initiated_by_user_id=_current_user_id(),
            initiated_by_username=_current_username(),
        )
    except ShelfmarkClientError as exc:
        flash(str(exc), category="error")
        return redirect(return_to)

    row = result.get("row") or {}
    queue_key = build_shelfmark_item_key(row.get("provider"), row.get("provider_id"))
    if result.get("reused"):
        flash(_("Shelfmark request already exists for this book."), category="info")
    else:
        flash(_("Shelfmark request queued for %(title)s.", title=row.get("title") or _("Unknown title")), category="success")
    if queue_key:
        return redirect(return_to + ("&" if "?" in return_to else "?") + f"queued={queue_key}")
    return redirect(return_to)


@shelfmark_search.route("/request/detail/<provider>/<path:provider_id>", methods=["GET"])
@login_required_if_no_ano
def book_detail(provider: str, provider_id: str):
    if not _feature_enabled():
        abort(404)

    try:
        detail = get_shelfmark_detail_view(
            get_shelfmark_client_config(),
            provider.strip().lower(),
            provider_id.strip(),
        )
    except ShelfmarkClientError as exc:
        return render_title_template(
            "shelfmark_search_detail.html",
            title=_("Book Details"),
            detail_error=str(exc),
            detail_view=None,
            query=(request.args.get("query") or "").strip(),
            is_xhr=_is_xhr_request(),
        )

    return render_title_template(
        "shelfmark_search_detail.html",
        title=_("Book Details"),
        detail_error="",
        detail_view=detail,
        query=(request.args.get("query") or "").strip(),
        is_xhr=_is_xhr_request(),
    )


@shelfmark_search.route("/request/status", methods=["POST"])
@login_required_if_no_ano
def queue_status():
    if not _feature_enabled():
        abort(404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload"}), 400

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return jsonify({"items": {}})

    items: list[tuple[str, str]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        provider = str(raw_item.get("provider") or "").strip().lower()
        provider_id = str(raw_item.get("provider_id") or "").strip()
        if provider and provider_id:
            items.append((provider, provider_id))

    statuses = load_visible_queue_status(items)
    for summary in statuses.values():
        imported_book_id = summary.get("imported_book_id")
        summary["href"] = (
            url_for("web.show_book", book_id=int(imported_book_id))
            if imported_book_id is not None
            else ""
        )

    return jsonify({"items": statuses})


@shelfmark_search.route("/shelfmark", methods=["GET"])
@login_required_if_no_ano
def legacy_search_page_redirect():
    if not _feature_enabled():
        abort(404)
    return redirect(url_for("shelfmark_search.search_page", **_redirect_query_args()), code=302)


@shelfmark_search.route("/shelfmark/detail/<provider>/<path:provider_id>", methods=["GET"])
@login_required_if_no_ano
def legacy_book_detail_redirect(provider: str, provider_id: str):
    if not _feature_enabled():
        abort(404)
    return redirect(
        url_for(
            "shelfmark_search.book_detail",
            provider=provider,
            provider_id=provider_id,
            **_redirect_query_args(),
        ),
        code=302,
    )


@shelfmark_search.route("/shelfmark/request", methods=["POST"])
@login_required_if_no_ano
def legacy_submit_request_redirect():
    if not _feature_enabled():
        abort(404)
    return redirect(url_for("shelfmark_search.submit_request"), code=307)


@shelfmark_search.route("/shelfmark/status", methods=["POST"])
@login_required_if_no_ano
def legacy_queue_status_redirect():
    if not _feature_enabled():
        abort(404)
    return redirect(url_for("shelfmark_search.queue_status"), code=307)
