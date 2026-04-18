# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urljoin, urlsplit

from flask_babel import gettext as _
from requests import RequestException

from cps import config, logger
from cps.cw_advocate import AddrValidator
from cps.cw_advocate import Session as SafeSession
from cps.cw_advocate.exceptions import UnacceptableAddressException

log = logger.create()

DEFAULT_SHELFMARK_TIMEOUT_SECONDS = 15
DEFAULT_SHELFMARK_SEARCH_LIMIT = 20
DEFAULT_SHELFMARK_SEARCH_PAGE = 1
DEFAULT_SHELFMARK_SEARCH_SORT = "relevance"
DEFAULT_SHELFMARK_CONTENT_TYPE = "ebook"


class ShelfmarkClientError(RuntimeError):
    """Raised when Shelfmark search or request operations fail."""


@dataclass(frozen=True)
class ShelfmarkClientConfig:
    enabled: bool
    base_url: str
    username: str
    password: str
    timeout_seconds: int = DEFAULT_SHELFMARK_TIMEOUT_SECONDS


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_base_url(value: Any) -> str:
    base_url = _normalize_text(value).rstrip("/")
    if not base_url:
        return ""

    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ShelfmarkClientError(
            _("Configure Shelfmark Base URL as a full http:// or https:// URL.")
        )

    return base_url


def get_shelfmark_client_config() -> ShelfmarkClientConfig:
    base_url = _normalize_text(getattr(config, "config_shelfmark_url", ""))
    enabled = bool(getattr(config, "config_shelfmark_search", False) and base_url)
    return ShelfmarkClientConfig(
        enabled=enabled,
        base_url=_normalize_base_url(base_url) if base_url else "",
        username=_normalize_text(getattr(config, "config_shelfmark_username", "")),
        password=_normalize_text(getattr(config, "config_shelfmark_password_e", "")),
    )


def _base_url_host_port(base_url: str) -> tuple[str, int]:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if not parsed.scheme or not host:
        raise ShelfmarkClientError(
            _("Configure Shelfmark Base URL as a full http:// or https:// URL.")
        )
    if parsed.port is not None:
        return host, parsed.port
    return host, 443 if parsed.scheme.lower() == "https" else 80


def _ip_network_for_address(value: str) -> ipaddress._BaseNetwork:
    address = ipaddress.ip_address(value)
    suffix = 32 if address.version == 4 else 128
    return ipaddress.ip_network(f"{address.exploded}/{suffix}", strict=False)


def _resolve_trusted_ip_networks(
    host: str,
    port: int,
) -> set[ipaddress._BaseNetwork]:
    try:
        return {_ip_network_for_address(host)}
    except ValueError:
        pass

    try:
        records = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ShelfmarkClientError(
            _("Shelfmark Base URL could not be resolved for trusted server-side access.")
        ) from exc

    trusted_networks: set[ipaddress._BaseNetwork] = set()
    for record in records:
        try:
            socket_address = record[4]
            raw_ip = str(socket_address[0]).split("%", 1)[0]
            trusted_networks.add(_ip_network_for_address(raw_ip))
        except (IndexError, TypeError, ValueError):
            continue

    if not trusted_networks:
        raise ShelfmarkClientError(
            _("Shelfmark Base URL could not be resolved for trusted server-side access.")
        )
    return trusted_networks


def build_shelfmark_validator(config_data: ShelfmarkClientConfig) -> AddrValidator:
    host, port = _base_url_host_port(config_data.base_url)
    trusted_networks = _resolve_trusted_ip_networks(host, port)
    return AddrValidator(
        ip_whitelist=trusted_networks,
        port_whitelist={port},
    )


def create_shelfmark_session(config_data: ShelfmarkClientConfig) -> SafeSession:
    return SafeSession(validator=build_shelfmark_validator(config_data))


def _join_base_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


class ShelfmarkClient:
    def __init__(self, config_data: ShelfmarkClientConfig, session: SafeSession | None = None):
        self.config = config_data
        self.session = session or create_shelfmark_session(config_data)
        self._authenticated = False

    def search_books(
        self,
        query: str,
        *,
        limit: int = DEFAULT_SHELFMARK_SEARCH_LIMIT,
        page: int = DEFAULT_SHELFMARK_SEARCH_PAGE,
        sort: str = DEFAULT_SHELFMARK_SEARCH_SORT,
        content_type: str = DEFAULT_SHELFMARK_CONTENT_TYPE,
    ) -> Mapping[str, Any]:
        self._ensure_authenticated()
        response = self._request(
            "get",
            "/api/metadata/search",
            params={
                "query": query,
                "limit": max(1, min(int(limit), 100)),
                "page": max(1, int(page)),
                "sort": _normalize_text(sort) or DEFAULT_SHELFMARK_SEARCH_SORT,
                "content_type": _normalize_text(content_type) or DEFAULT_SHELFMARK_CONTENT_TYPE,
            },
            default_message=_("Shelfmark search failed."),
        )
        return self._json_response(
            response,
            default_message=_("Shelfmark search failed."),
            unauthorized_message=_(
                "Shelfmark metadata search requires a configured service account. "
                "Set Shelfmark Service Username and Password in CWA admin."
            ),
        )

    def fetch_book(self, provider: str, provider_id: str) -> Mapping[str, Any]:
        self._ensure_authenticated()
        response = self._request(
            "get",
            f"/api/metadata/book/{provider}/{provider_id}",
            default_message=_("Shelfmark book details are unavailable."),
        )
        return self._json_response(
            response,
            default_message=_("Shelfmark book details are unavailable."),
        )

    def create_request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_authenticated()
        response = self._request(
            "post",
            "/api/requests",
            json=dict(payload),
            default_message=_("Shelfmark request submission failed."),
        )
        return self._json_response(
            response,
            default_message=_("Shelfmark request submission failed."),
        )

    def fetch_activity_snapshot(self) -> Mapping[str, Any]:
        self._ensure_authenticated()
        response = self._request(
            "get",
            "/api/activity/snapshot",
            default_message=_("Shelfmark activity sync failed."),
        )
        return self._json_response(
            response,
            default_message=_("Shelfmark activity sync failed."),
        )

    def _ensure_authenticated(self) -> None:
        if self._authenticated:
            return

        username = self.config.username
        password = self.config.password
        if not username and not password:
            self._authenticated = True
            return

        if not username or not password:
            raise ShelfmarkClientError(
                _(
                    "Configure both Shelfmark Service Username and Shelfmark Service Password "
                    "before enabling Shelfmark search."
                )
            )

        response = self._request(
            "post",
            "/api/auth/login",
            json={
                "username": username,
                "password": password,
                "remember_me": False,
            },
            default_message=_("Shelfmark login failed for the configured service account."),
        )
        payload = self._json_response(
            response,
            default_message=_("Shelfmark login failed for the configured service account."),
        )
        if not payload.get("success"):
            raise ShelfmarkClientError(
                _("Shelfmark login failed for the configured service account.")
            )
        self._authenticated = True

    def _request(self, method: str, path: str, default_message: str, **kwargs: Any):
        url = _join_base_url(self.config.base_url, path)
        try:
            return getattr(self.session, method)(
                url,
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
        except UnacceptableAddressException as exc:
            raise ShelfmarkClientError(
                _(
                    "Shelfmark server-side request validation blocked this address. "
                    "Check that Shelfmark Base URL points directly to your Shelfmark instance."
                )
            ) from exc
        except RequestException as exc:
            raise ShelfmarkClientError(default_message) from exc

    @staticmethod
    def _json_response(
        response: Any,
        *,
        default_message: str,
        unauthorized_message: str | None = None,
    ) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShelfmarkClientError(default_message) from exc

        status_code = getattr(response, "status_code", None)
        if getattr(response, "ok", False):
            if isinstance(payload, Mapping):
                return payload
            raise ShelfmarkClientError(default_message)

        if status_code == 401 and unauthorized_message:
            raise ShelfmarkClientError(unauthorized_message)

        if isinstance(payload, Mapping):
            message = _normalize_text(payload.get("message")) or _normalize_text(payload.get("error"))
            if message:
                raise ShelfmarkClientError(message)

        raise ShelfmarkClientError(default_message)


def build_shelfmark_item_key(provider: Any, provider_id: Any) -> str:
    normalized_provider = _normalize_text(provider).lower()
    normalized_provider_id = _normalize_text(provider_id)
    if not normalized_provider or not normalized_provider_id:
        return ""
    return f"{normalized_provider}:{normalized_provider_id}"

