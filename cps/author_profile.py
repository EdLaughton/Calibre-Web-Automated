# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass

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


def _from_hardcover(author_name: str) -> AuthorProfileView | None:
    hardcover_service = getattr(services, "hardcover", None)
    if not hardcover_service:
        return None

    try:
        profile = hardcover_service.get_author_profile(author_name)
    except Exception as exc:  # pragma: no cover - defensive app-path guard
        log.warning("Hardcover author profile lookup failed for %s: %s", author_name, exc)
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

    try:
        profile = goodreads_service.get_author_info(author_name)
    except Exception as exc:  # pragma: no cover - defensive app-path guard
        log.warning("Goodreads author profile lookup failed for %s: %s", author_name, exc)
        return None

    if not profile:
        return None

    return AuthorProfileView(
        name=getattr(profile, "name", None) or author_name,
        image_url=getattr(profile, "image_url", None),
        safe_about=getattr(profile, "safe_about", None),
        link=getattr(profile, "link", None),
        source_label=_("Goodreads"),
    )


def build_author_profile(author_name: str) -> AuthorProfileView | None:
    if not author_name:
        return None

    hardcover_profile = _from_hardcover(author_name)
    if hardcover_profile and (hardcover_profile.image_url or hardcover_profile.safe_about):
        return hardcover_profile

    goodreads_profile = _from_goodreads(author_name)
    if goodreads_profile and (goodreads_profile.image_url or goodreads_profile.safe_about):
        return goodreads_profile

    return hardcover_profile or goodreads_profile
