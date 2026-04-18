# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
import re

from flask_babel import gettext as _

from . import logger, services

log = logger.create()


@dataclass(frozen=True)
class AuthorProfileView:
    name: str
    image_url: str | None = None
    safe_about: str | None = None
    link: str | None = None
    source_label: str | None = None


def _normalize_author_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = str(value).replace("|", ",").lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _candidate_author_names(author_name: str) -> tuple[str, ...]:
    normalized = " ".join((author_name or "").replace("|", ",").split())
    if not normalized:
        return tuple()

    candidates = [normalized]
    if "," in normalized:
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
        if len(parts) == 2:
            display_name = " ".join(reversed(parts)).strip()
            if display_name and display_name not in candidates:
                candidates.append(display_name)
    return tuple(candidates)


def _from_hardcover(author_name: str) -> AuthorProfileView | None:
    hardcover_service = getattr(services, "hardcover", None)
    if not hardcover_service:
        return None

    for candidate_name in _candidate_author_names(author_name):
        try:
            profile = hardcover_service.get_author_profile(candidate_name)
        except Exception as exc:  # pragma: no cover - defensive app-path guard
            log.warning("Hardcover author profile lookup failed for %s: %s", candidate_name, exc)
            continue

        if not profile:
            continue

        return AuthorProfileView(
            name=profile.name or candidate_name,
            image_url=profile.image_url,
            safe_about=profile.safe_about,
            link=profile.link,
            source_label=_("Hardcover"),
        )
    return None


def _extract_hardcover_book_ids(library_books) -> tuple[int, ...]:
    seen: set[int] = set()
    normalized_ids: list[int] = []
    for book in library_books or ():
        for identifier in getattr(book, "identifiers", None) or ():
            identifier_type = str(getattr(identifier, "type", "") or "").strip().lower()
            if identifier_type != "hardcover-id":
                continue
            raw_value = getattr(identifier, "val", None)
            try:
                hardcover_id = int(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
            if hardcover_id in seen:
                continue
            seen.add(hardcover_id)
            normalized_ids.append(hardcover_id)
    return tuple(normalized_ids)


def _select_hardcover_author_id(author_name: str, library_books) -> int | None:
    hardcover_service = getattr(services, "hardcover", None)
    if not hardcover_service or not hasattr(hardcover_service, "get_hardcover_client"):
        return None

    book_ids = _extract_hardcover_book_ids(library_books)
    if not book_ids:
        return None

    try:
        client = hardcover_service.get_hardcover_client(load_privacy=False)
    except Exception as exc:  # pragma: no cover - defensive app-path guard
        log.warning("Hardcover client lookup failed while resolving author profile for %s: %s", author_name, exc)
        return None
    if client is None:
        return None

    try:
        books = client.list_books_by_ids(list(book_ids))
    except Exception as exc:  # pragma: no cover - defensive app-path guard
        log.warning("Hardcover book lookup failed while resolving author profile for %s: %s", author_name, exc)
        return None

    candidate_keys = {_normalize_author_key(candidate) for candidate in _candidate_author_names(author_name)}
    candidate_keys.discard("")
    if not candidate_keys:
        return None

    scores: dict[int, int] = {}
    for book in books or ():
        for contribution in book.get("contributions") or ():
            author = contribution.get("author") if isinstance(contribution, dict) else None
            if not isinstance(author, dict):
                continue
            try:
                hardcover_author_id = int(author.get("id"))
            except (TypeError, ValueError):
                continue
            if _normalize_author_key(author.get("name")) not in candidate_keys:
                continue
            scores[hardcover_author_id] = scores.get(hardcover_author_id, 0) + 1

    if not scores:
        return None

    return max(scores.items(), key=lambda item: (item[1], -item[0]))[0]


def _from_hardcover_library_books(author_name: str, library_books) -> AuthorProfileView | None:
    hardcover_service = getattr(services, "hardcover", None)
    if not hardcover_service or not hasattr(hardcover_service, "get_author_profile_by_id"):
        return None

    hardcover_author_id = _select_hardcover_author_id(author_name, library_books)
    if hardcover_author_id is None:
        return None

    try:
        profile = hardcover_service.get_author_profile_by_id(hardcover_author_id)
    except Exception as exc:  # pragma: no cover - defensive app-path guard
        log.warning(
            "Hardcover author profile by id failed for %s (author_id=%s): %s",
            author_name,
            hardcover_author_id,
            exc,
        )
        return None
    if not profile:
        return None

    return AuthorProfileView(
        name=profile.name or author_name,
        image_url=profile.image_url,
        safe_about=profile.safe_about,
        link=profile.link,
        source_label=_("Hardcover"),
    )


def _from_goodreads(author_name: str) -> AuthorProfileView | None:
    goodreads_service = getattr(services, "goodreads_support", None)
    if not goodreads_service:
        return None

    for candidate_name in _candidate_author_names(author_name):
        try:
            profile = goodreads_service.get_author_info(candidate_name)
        except Exception as exc:  # pragma: no cover - defensive app-path guard
            log.warning("Goodreads author profile lookup failed for %s: %s", candidate_name, exc)
            continue

        if not profile:
            continue

        return AuthorProfileView(
            name=getattr(profile, "name", None) or candidate_name,
            image_url=getattr(profile, "image_url", None),
            safe_about=getattr(profile, "safe_about", None),
            link=getattr(profile, "link", None),
            source_label=_("Goodreads"),
        )
    return None


def build_author_profile(author_name: str, *, library_books=None) -> AuthorProfileView | None:
    if not author_name:
        return None

    hardcover_profile = _from_hardcover_library_books(author_name, library_books)
    if hardcover_profile and (hardcover_profile.image_url or hardcover_profile.safe_about):
        return hardcover_profile

    hardcover_profile = _from_hardcover(author_name)
    if hardcover_profile and (hardcover_profile.image_url or hardcover_profile.safe_about):
        return hardcover_profile

    goodreads_profile = _from_goodreads(author_name)
    if goodreads_profile and (goodreads_profile.image_url or goodreads_profile.safe_about):
        return goodreads_profile

    return hardcover_profile or goodreads_profile
