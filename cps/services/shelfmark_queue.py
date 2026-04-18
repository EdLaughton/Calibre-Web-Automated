# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask_babel import gettext as _

from cps import logger

from .shelfmark_client import (
    ShelfmarkClient,
    ShelfmarkClientError,
    ShelfmarkClientConfig,
    build_shelfmark_item_key,
)

_scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from cwa_db import CWA_DB  # noqa: E402

log = logger.create()

ACTIVE_QUEUE_STATUSES = {
    "submitting",
    "requested",
    "queued",
    "resolving",
    "locating",
    "downloading",
    "complete",
    "importing",
}
RETRYABLE_QUEUE_STATUSES = {"failed", "cancelled", "rejected"}


@dataclass(frozen=True)
class ShelfmarkQueueSummary:
    key: str
    provider: str
    provider_id: str
    status: str
    label: str
    detail: str
    imported_book_id: int | None
    row: Mapping[str, Any]

    @property
    def is_terminal(self) -> bool:
        return self.status in {"imported", "failed", "cancelled", "rejected"}


def _utcnow() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value or {}, sort_keys=True)
    except TypeError:
        return "{}"


def _parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = _normalize_text(value)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _response_is_download(payload: Mapping[str, Any]) -> bool:
    return _normalize_text(payload.get("kind")).lower() == "download"


def _request_level(payload: Mapping[str, Any]) -> str:
    context = payload.get("context")
    if isinstance(context, Mapping):
        value = _normalize_text(context.get("request_level"))
        if value:
            return value
    return "book"


def _primary_title(payload: Mapping[str, Any]) -> str:
    for container_key in ("book_data", "release_data"):
        container = payload.get(container_key)
        if isinstance(container, Mapping):
            title = _normalize_text(container.get("title"))
            if title:
                return title
    return ""


def _primary_author(payload: Mapping[str, Any]) -> str:
    for container_key in ("book_data", "release_data"):
        container = payload.get(container_key)
        if isinstance(container, Mapping):
            author = _normalize_text(container.get("author"))
            if author:
                return author
    return ""


def _extract_identifiers(payload: Mapping[str, Any]) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for container_key in ("book_data", "release_data"):
        container = payload.get(container_key)
        if not isinstance(container, Mapping):
            continue
        provider = _normalize_text(container.get("provider")).lower()
        provider_id = _normalize_text(container.get("provider_id"))
        if provider == "hardcover" and provider_id:
            identifiers.setdefault("hardcover-id", provider_id)
        for identifier_key in ("isbn_13", "isbn13", "isbn_10", "isbn10", "isbn"):
            raw_value = _normalize_text(container.get(identifier_key))
            if raw_value:
                identifiers.setdefault("isbn", raw_value.replace("-", "").replace(" ", ""))
    return identifiers


def _status_label(status: str, row: Mapping[str, Any]) -> tuple[str, str]:
    detail = _normalize_text(row.get("status_detail")) or _normalize_text(row.get("last_error"))
    labels = {
        "submitting": _("Queued"),
        "requested": _("Queued"),
        "queued": _("Queued"),
        "resolving": _("Queued"),
        "locating": _("Queued"),
        "downloading": _("Downloading"),
        "complete": _("Importing"),
        "importing": _("Importing"),
        "imported": _("Imported"),
        "failed": _("Request in Shelfmark"),
        "cancelled": _("Request in Shelfmark"),
        "rejected": _("Request in Shelfmark"),
    }
    return labels.get(status, _("Request in Shelfmark")), detail


def queue_row_to_summary(row: Mapping[str, Any]) -> ShelfmarkQueueSummary:
    provider = _normalize_text(row.get("provider")).lower()
    provider_id = _normalize_text(row.get("provider_id"))
    status = _normalize_text(row.get("status")).lower() or "requested"
    label, detail = _status_label(status, row)
    imported_book_id = row.get("imported_book_id")
    try:
        imported_book_id = int(imported_book_id) if imported_book_id is not None else None
    except (TypeError, ValueError):
        imported_book_id = None
    return ShelfmarkQueueSummary(
        key=build_shelfmark_item_key(provider, provider_id),
        provider=provider,
        provider_id=provider_id,
        status=status,
        label=label,
        detail=detail,
        imported_book_id=imported_book_id,
        row=row,
    )


def load_queue_rows_for_items(items: Sequence[tuple[str, str]]) -> dict[str, ShelfmarkQueueSummary]:
    if not items:
        return {}
    db = CWA_DB()
    rows = db.shelfmark_queue_get_latest_for_items(items)
    return {
        summary.key: summary
        for summary in (queue_row_to_summary(row) for row in rows)
        if summary.key
    }


def submit_shelfmark_request(
    config_data: ShelfmarkClientConfig,
    payload: Mapping[str, Any],
    *,
    initiated_by_user_id: int | None,
    initiated_by_username: str,
) -> Mapping[str, Any]:
    book_data = payload.get("book_data")
    if not isinstance(book_data, Mapping):
        raise ShelfmarkClientError(_("Shelfmark request payload is missing book data."))

    provider = _normalize_text(book_data.get("provider")).lower()
    provider_id = _normalize_text(book_data.get("provider_id"))
    title = _primary_title(payload)
    author = _primary_author(payload)
    if not provider or not provider_id:
        raise ShelfmarkClientError(_("Shelfmark request payload is missing provider identity."))

    db = CWA_DB()
    existing = db.shelfmark_queue_find_active(provider, provider_id)
    if existing:
        return {
            "row": existing,
            "created": False,
            "reused": True,
            "response": _parse_json(existing.get("response_json")),
        }

    row_id = db.shelfmark_queue_add(
        provider=provider,
        provider_id=provider_id,
        title=title,
        author=author,
        content_type=_normalize_text(book_data.get("content_type")) or "ebook",
        request_kind=_request_level(payload),
        status="submitting",
        status_detail="",
        request_payload_json=_json_dumps(payload),
        release_data_json=_json_dumps(payload.get("release_data")),
        response_json="{}",
        external_request_id=None,
        external_task_id="",
        external_source=_normalize_text((payload.get("release_data") or {}).get("source") if isinstance(payload.get("release_data"), Mapping) else ""),
        external_source_id=_normalize_text((payload.get("release_data") or {}).get("source_id") if isinstance(payload.get("release_data"), Mapping) else ""),
        initiated_by_user_id=initiated_by_user_id,
        initiated_by_username=initiated_by_username,
        last_error="",
    )
    if row_id is None:
        raise ShelfmarkClientError(_("Could not persist the Shelfmark queue row in CWA."))

    client = ShelfmarkClient(config_data)
    try:
        response_payload = dict(client.create_request(payload))
    except ShelfmarkClientError as exc:
        db.shelfmark_queue_update_status(
            row_id,
            status="failed",
            status_detail=_normalize_text(exc),
            last_error=_normalize_text(exc),
            response_json="{}",
        )
        raise

    identifiers = _extract_identifiers(payload)
    if _response_is_download(response_payload):
        db.shelfmark_queue_update_submission(
            row_id,
            status="queued",
            status_detail="",
            response_json=_json_dumps(response_payload),
            external_request_id=None,
            external_task_id="",
            external_source=_normalize_text(response_payload.get("source")) or _normalize_text((payload.get("release_data") or {}).get("source") if isinstance(payload.get("release_data"), Mapping) else ""),
            external_source_id=_normalize_text(response_payload.get("source_id")) or _normalize_text((payload.get("release_data") or {}).get("source_id") if isinstance(payload.get("release_data"), Mapping) else ""),
            release_data_json=_json_dumps(payload.get("release_data")),
            last_error="",
            identifiers_json=_json_dumps(identifiers),
        )
    else:
        delivery_state = _normalize_text(response_payload.get("delivery_state")).lower()
        queue_status = {
            "queued": "queued",
            "resolving": "resolving",
            "locating": "locating",
            "downloading": "downloading",
            "complete": "complete",
            "error": "failed",
            "cancelled": "cancelled",
        }.get(delivery_state, "requested")
        db.shelfmark_queue_update_submission(
            row_id,
            status=queue_status,
            status_detail=_normalize_text(response_payload.get("last_failure_reason")),
            response_json=_json_dumps(response_payload),
            external_request_id=response_payload.get("id"),
            external_task_id="",
            external_source=_normalize_text((payload.get("release_data") or {}).get("source") if isinstance(payload.get("release_data"), Mapping) else ""),
            external_source_id=_normalize_text((payload.get("release_data") or {}).get("source_id") if isinstance(payload.get("release_data"), Mapping) else ""),
            release_data_json=_json_dumps(response_payload.get("release_data") or payload.get("release_data")),
            last_error="",
            identifiers_json=_json_dumps(identifiers),
        )

    row = db.shelfmark_queue_get_by_id(row_id)
    return {
        "row": row or {},
        "created": True,
        "reused": False,
        "response": response_payload,
    }


def _flatten_snapshot_downloads(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    status_payload = snapshot.get("status")
    if not isinstance(status_payload, Mapping):
        return {}

    flattened: dict[str, dict[str, Any]] = {}
    for status_name, bucket in status_payload.items():
        if not isinstance(bucket, Mapping):
            continue
        normalized_status = _normalize_text(status_name).lower()
        for task_id, download_item in bucket.items():
            if not isinstance(download_item, Mapping):
                continue
            item = dict(download_item)
            item.setdefault("id", _normalize_text(task_id))
            item["_bucket_status"] = normalized_status
            flattened[_normalize_text(item.get("id"))] = item
    return flattened


def _flatten_snapshot_requests(snapshot: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    raw_requests = snapshot.get("requests")
    if not isinstance(raw_requests, Sequence):
        return {}

    flattened: dict[int, dict[str, Any]] = {}
    for request_item in raw_requests:
        if not isinstance(request_item, Mapping):
            continue
        try:
            request_id = int(request_item.get("id"))
        except (TypeError, ValueError):
            continue
        flattened[request_id] = dict(request_item)
    return flattened


def _match_download_for_row(
    row: Mapping[str, Any],
    downloads_by_id: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    external_task_id = _normalize_text(row.get("external_task_id"))
    if external_task_id and external_task_id in downloads_by_id:
        return downloads_by_id[external_task_id]

    provider_source = _normalize_text(row.get("external_source")).lower()
    provider_source_id = _normalize_text(row.get("external_source_id"))
    title = _normalize_text(row.get("title")).lower()
    for download_item in downloads_by_id.values():
        source = _normalize_text(download_item.get("source")).lower()
        source_id = _normalize_text(download_item.get("source_id"))
        if provider_source and provider_source_id and source == provider_source and source_id == provider_source_id:
            return download_item
        if title and _normalize_text(download_item.get("title")).lower() == title:
            return download_item
    return None


def _map_request_row_status(request_item: Mapping[str, Any]) -> tuple[str, str]:
    request_status = _normalize_text(request_item.get("status")).lower()
    delivery_state = _normalize_text(request_item.get("delivery_state")).lower()
    last_failure_reason = _normalize_text(request_item.get("last_failure_reason"))

    if request_status == "rejected":
        return "rejected", last_failure_reason
    if request_status == "cancelled":
        return "cancelled", last_failure_reason
    if delivery_state == "error":
        return "failed", last_failure_reason
    if delivery_state == "cancelled":
        return "cancelled", last_failure_reason
    if delivery_state in {"queued", "resolving", "locating", "downloading", "complete"}:
        return delivery_state, last_failure_reason
    return "requested", last_failure_reason


def sync_shelfmark_queue(
    config_data: ShelfmarkClientConfig,
    *,
    imported_matcher: Any = None,
) -> dict[str, int]:
    db = CWA_DB()
    active_rows = db.shelfmark_queue_list_active()
    summary = {
        "updated": 0,
        "imported": 0,
        "active": len(active_rows),
    }
    if not active_rows:
        return summary

    client = ShelfmarkClient(config_data)
    snapshot = client.fetch_activity_snapshot()
    downloads_by_id = _flatten_snapshot_downloads(snapshot)
    requests_by_id = _flatten_snapshot_requests(snapshot)

    if imported_matcher is None:
        from .shelfmark_search import reconcile_queue_rows_with_library

        imported_matcher = reconcile_queue_rows_with_library

    row_updates: list[tuple[int, dict[str, Any]]] = []
    for row in active_rows:
        row_id = int(row["id"])
        next_fields: dict[str, Any] = {
            "last_polled_at_utc": _utcnow(),
        }

        external_request_id = row.get("external_request_id")
        matched_request = None
        try:
            if external_request_id is not None:
                matched_request = requests_by_id.get(int(external_request_id))
        except (TypeError, ValueError):
            matched_request = None

        if matched_request is not None:
            mapped_status, detail = _map_request_row_status(matched_request)
            next_fields.update(
                {
                    "status": mapped_status,
                    "status_detail": detail,
                    "release_data_json": _json_dumps(matched_request.get("release_data")),
                    "response_json": _json_dumps(matched_request),
                    "last_error": detail if mapped_status in {"failed", "rejected", "cancelled"} else "",
                }
            )

        matched_download = _match_download_for_row(row, downloads_by_id)
        if matched_download is not None:
            bucket_status = _normalize_text(matched_download.get("_bucket_status")).lower()
            mapped_status = {
                "queued": "queued",
                "resolving": "resolving",
                "locating": "locating",
                "downloading": "downloading",
                "complete": "complete",
                "error": "failed",
                "cancelled": "cancelled",
            }.get(bucket_status, bucket_status or _normalize_text(row.get("status")).lower() or "queued")
            next_fields.update(
                {
                    "status": mapped_status,
                    "status_detail": _normalize_text(matched_download.get("status_message")),
                    "external_task_id": _normalize_text(matched_download.get("id")),
                    "external_source": _normalize_text(matched_download.get("source")) or _normalize_text(row.get("external_source")),
                    "external_source_id": _normalize_text(matched_download.get("source_id")) or _normalize_text(row.get("external_source_id")),
                    "response_json": _json_dumps(matched_download),
                    "last_error": _normalize_text(matched_download.get("status_message")) if mapped_status == "failed" else "",
                }
            )

        row_updates.append((row_id, next_fields))

    for row_id, next_fields in row_updates:
        db.shelfmark_queue_patch(row_id, next_fields)
        summary["updated"] += 1

    refreshed_rows = db.shelfmark_queue_list_active()
    imported = imported_matcher(refreshed_rows)
    for row_id, imported_book_id in imported:
        db.shelfmark_queue_mark_imported(row_id, imported_book_id)
        summary["imported"] += 1

    for row in db.shelfmark_queue_list_active():
        status = _normalize_text(row.get("status")).lower()
        if status == "complete":
            db.shelfmark_queue_patch(
                int(row["id"]),
                {
                    "status": "importing",
                    "status_detail": _normalize_text(row.get("status_detail")),
                },
            )

    return summary


def load_visible_queue_status(items: Iterable[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    rows = load_queue_rows_for_items(list(items))
    return {
        key: {
            "status": summary.status,
            "label": summary.label,
            "detail": summary.detail,
            "imported_book_id": summary.imported_book_id,
        }
        for key, summary in rows.items()
    }

