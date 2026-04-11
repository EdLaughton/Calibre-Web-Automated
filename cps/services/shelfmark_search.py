from __future__ import annotations
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, replace
import ipaddress
import math
import re
import socket
from time import monotonic
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from requests import RequestException
from flask import url_for
from flask_babel import gettext as _
from markupsafe import Markup
from sqlalchemy.sql.expression import func

from cps import calibre_db, config, db, logger
from cps.clean_html import clean_string
from cps.cw_advocate import AddrValidator
from cps.cw_advocate import Session as SafeSession
from cps.cw_advocate.exceptions import UnacceptableAddressException

log = logger.create()

DEFAULT_SHELFMARK_TIMEOUT_SECONDS = 15
DEFAULT_SHELFMARK_LIMIT = 12
DEFAULT_SHELFMARK_SORT = "popularity"
DEFAULT_SHELFMARK_PAGE = 1
DEFAULT_SHELFMARK_FILTER_REQUESTABLE = True
DEFAULT_SHELFMARK_FILTER_HAS_COVER = True
DEFAULT_SHELFMARK_FILTER_HIGH_CONFIDENCE = False
DEFAULT_SHELFMARK_SERIES_FILTER = "all"
DEFAULT_SHELFMARK_TRIAGE_FILTER = "all"
SHELFMARK_PAGE_SIZE_OPTIONS = (12, 24, 50, 100)
SHELFMARK_SORT_OPTIONS = (
    ("popularity", "Most popular"),
    ("relevance", "Most relevant"),
    ("rating", "Highest rated"),
    ("newest", "Newest"),
    ("oldest", "Oldest"),
)
SHELFMARK_SERIES_FILTER_OPTIONS = (
    ("all", "All matches"),
    ("owned", "Owned series"),
    ("next_missing", "Next missing"),
)
SHELFMARK_TRIAGE_FILTER_OPTIONS = (
    ("all", "All shown"),
    ("strong", "Strong candidates"),
)
SHELFMARK_METADATA_PROVIDER = "hardcover"
SHELFMARK_CONTENT_TYPE = "ebook"
SHELFMARK_REQUEST_MODE = "request_book"
SHELFMARK_REQUEST_KIND = "book"
SHELFMARK_DETAIL_CACHE_TTL_SECONDS = 300
SHELFMARK_DETAIL_CACHE_MAX_ENTRIES = 256
SHELFMARK_COVER_CACHE_TTL_SECONDS = 300
SHELFMARK_COVER_CACHE_MAX_ENTRIES = 512
SHELFMARK_SCAN_CACHE_TTL_SECONDS = 120
SHELFMARK_SCAN_CACHE_MAX_ENTRIES = 16
SHELFMARK_SCAN_PAGE_SIZE = 100
SHELFMARK_QUALITY_MIN_METADATA_SIGNALS = 5
SHELFMARK_TRIAGE_MIN_RATINGS = 200
SHELFMARK_TRIAGE_MIN_READERS = 1000
SHELFMARK_TRIAGE_MIN_RATING = 4.0
SHELFMARK_TRIAGE_MIN_RATING_COUNT = 50
SHELFMARK_AUDIOBOOK_HINTS = (
    "audiobook",
    "audio book",
    "audible audio",
    "audio cd",
    "audio-cd",
    "m4b",
    "cassette",
)
SHELFMARK_EBOOK_HINTS = (
    "ebook",
    "e-book",
    "epub",
    "digital",
    "kindle",
)
SHELFMARK_PHYSICAL_HINTS = (
    "physical",
    "physical book",
    "hardcover",
    "paperback",
    "softcover",
    "mass market paperback",
    "board book",
    "print",
)
SHELFMARK_GENRE_CATEGORY_HINTS = ("genre", "genres")
SHELFMARK_MOOD_CATEGORY_HINTS = ("mood", "moods")
SHELFMARK_CONTENT_WARNING_CATEGORY_HINTS = (
    "content warning",
    "content warnings",
    "warning",
    "warnings",
    "trigger warning",
    "trigger warnings",
)

_SHELFMARK_DETAIL_CACHE: OrderedDict[tuple[str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
_SHELFMARK_COVER_CACHE: OrderedDict[tuple[str, str], tuple[float, str]] = OrderedDict()
_SHELFMARK_SCAN_CACHE: OrderedDict[
    tuple[str, str, str, int, int],
    tuple[float, tuple[dict[str, Any], ...], int, int, bool],
] = OrderedDict()


class ShelfmarkIntegrationError(RuntimeError):
    """Raised when the Shelfmark search integration cannot complete safely."""


@dataclass(frozen=True)
class ShelfmarkLibraryMatch:
    hardcover_id: str
    book_id: int
    title: str


@dataclass(frozen=True)
class ShelfmarkProbeState:
    authenticated: bool = False
    auth_required: bool = True
    requests_enabled: bool = False
    ebook_mode: str | None = None
    probe_available: bool = False


@dataclass(frozen=True)
class ShelfmarkActionState:
    mode: str
    label: str
    hint: str
    button_class: str
    icon_class: str


@dataclass(frozen=True)
class ShelfmarkLibraryState:
    key: str
    label: str | None
    hint: str | None
    row_class: str
    badge_class: str | None
    panel_class: str
    icon_class: str


@dataclass(frozen=True)
class ShelfmarkOwnedSeries:
    key: str
    series_name: str
    book_count: int
    owned_positions: tuple[float, ...]
    max_position: float | None
    contiguous_position: int | None


@dataclass(frozen=True)
class ShelfmarkSeriesContext:
    matched: bool = False
    owned_series_name: str | None = None
    owned_book_count: int = 0
    owned_max_position: float | None = None
    owned_contiguous_position: int | None = None
    is_continuation: bool = False
    is_next_missing: bool = False
    badges: tuple[dict[str, str], ...] = field(default_factory=tuple)
    facts: tuple[str, ...] = field(default_factory=tuple)
    detail_value: str | None = None


@dataclass(frozen=True)
class ShelfmarkWorkflowState:
    key: str
    label: str
    chip_class: str


@dataclass(frozen=True)
class ShelfmarkTriageState:
    strong_candidate: bool = False
    metadata_rich: bool = False
    popularity_signal: bool = False
    facts: tuple[str, ...] = field(default_factory=tuple)
    detail_value: str | None = None


@dataclass(frozen=True)
class ShelfmarkQualityState:
    high_confidence: bool = False
    metadata_complete: bool = False
    popularity_signal: bool = False
    rating_signal: bool = False
    bibliographic_signal: bool = False
    facts: tuple[str, ...] = field(default_factory=tuple)
    detail_value: str | None = None


@dataclass(frozen=True)
class ShelfmarkResultView:
    provider: str
    provider_id: str
    title: str
    subtitle: str | None
    authors: tuple[str, ...]
    cover_url: str | None
    description: str | None
    publish_year: int | None
    source_url: str | None
    display_fields: tuple[dict[str, Any], ...]
    rating: float | None
    ratings_count: int | None
    reviews_count: int | None
    readers_count: int | None
    hardcover_id: str | None
    already_in_library: bool
    library_book_id: int | None
    library_book_title: str | None
    library_book_url: str | None
    detail_url: str | None
    shelfmark_base_url: str
    shelfmark_open_url: str
    request_payload: dict[str, Any] | None
    library_state: ShelfmarkLibraryState
    action: ShelfmarkActionState
    pages: int | None = None
    editions_count: int | None = None
    lists_count: int | None = None
    description_html: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    series_count: int | None = None
    series_display: str | None = None
    series_url: str | None = None
    facts: tuple[str, ...] = field(default_factory=tuple)
    detail_stats: tuple[dict[str, str], ...] = field(default_factory=tuple)
    genres: tuple[str, ...] = field(default_factory=tuple)
    moods: tuple[str, ...] = field(default_factory=tuple)
    content_warnings: tuple[str, ...] = field(default_factory=tuple)
    series_context: ShelfmarkSeriesContext | None = None
    workflow_state: ShelfmarkWorkflowState | None = None
    quality_state: ShelfmarkQualityState | None = None
    triage_state: ShelfmarkTriageState | None = None
    needs_progressive_enrichment: bool = False
    progressive_filter_pending: bool = False

    def to_template_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authors"] = list(self.authors)
        payload["display_fields"] = list(self.display_fields)
        payload["facts"] = list(self.facts)
        payload["detail_stats"] = list(self.detail_stats)
        payload["genres"] = list(self.genres)
        payload["moods"] = list(self.moods)
        payload["content_warnings"] = list(self.content_warnings)
        if self.series_context:
            payload["series_context"]["badges"] = list(self.series_context.badges)
            payload["series_context"]["facts"] = list(self.series_context.facts)
        if self.quality_state:
            payload["quality_state"]["facts"] = list(self.quality_state.facts)
        if self.triage_state:
            payload["triage_state"]["facts"] = list(self.triage_state.facts)
        payload["library_state"] = asdict(self.library_state)
        payload["action"] = asdict(self.action)
        return payload


@dataclass(frozen=True)
class ShelfmarkResultSummary:
    total_results: int = 0
    total_available: int = 0
    raw_total_available: int = 0
    has_more: bool = False
    already_in_library: int = 0
    external_candidates: int = 0
    library_match_unavailable: int = 0

    def to_template_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShelfmarkResultGroup:
    key: str
    title: str
    hint: str | None = None
    panel_class: str = "panel-default"
    badge_class: str = "label-default"
    icon_class: str = "glyphicon glyphicon-book"
    results: tuple[ShelfmarkResultView, ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        return len(self.results)

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "hint": self.hint,
            "panel_class": self.panel_class,
            "badge_class": self.badge_class,
            "icon_class": self.icon_class,
            "count": self.count,
            "results": [result.to_template_dict() for result in self.results],
        }


@dataclass(frozen=True)
class ShelfmarkSearchSection:
    enabled: bool
    available: bool
    query: str
    page: int = DEFAULT_SHELFMARK_PAGE
    page_size: int = DEFAULT_SHELFMARK_LIMIT
    selected_sort: str = DEFAULT_SHELFMARK_SORT
    sort_options: tuple[dict[str, str], ...] = field(default_factory=tuple)
    selected_series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER
    series_filter_options: tuple[dict[str, str], ...] = field(default_factory=tuple)
    selected_triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER
    triage_filter_options: tuple[dict[str, str], ...] = field(default_factory=tuple)
    page_size_options: tuple[int, ...] = SHELFMARK_PAGE_SIZE_OPTIONS
    total_pages: int = 0
    visible_start: int = 0
    visible_end: int = 0
    has_previous: bool = False
    previous_page: int | None = None
    next_page: int | None = None
    has_more: bool = False
    total_available: int = 0
    raw_total_available: int = 0
    page_result_count: int = 0
    filter_requestable: bool = DEFAULT_SHELFMARK_FILTER_REQUESTABLE
    filter_has_cover: bool = DEFAULT_SHELFMARK_FILTER_HAS_COVER
    filter_high_confidence: bool = DEFAULT_SHELFMARK_FILTER_HIGH_CONFIDENCE
    filters_active: bool = False
    open_search_url: str | None = None
    query_label: str | None = None
    context_hint: str | None = None
    message: str | None = None
    message_level: str = "info"
    pagination_mode: str = "shelfmark"
    progressive_refinement: bool = False
    progressive_refinement_note: str | None = None
    results: tuple[ShelfmarkResultView, ...] = field(default_factory=tuple)
    groups: tuple[ShelfmarkResultGroup, ...] = field(default_factory=tuple)
    summary: ShelfmarkResultSummary = field(default_factory=ShelfmarkResultSummary)

    def to_template_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "query": self.query,
            "page": self.page,
            "page_size": self.page_size,
            "selected_sort": self.selected_sort,
            "sort_options": [dict(option) for option in self.sort_options],
            "selected_series_filter": self.selected_series_filter,
            "series_filter_options": [dict(option) for option in self.series_filter_options],
            "selected_triage_filter": self.selected_triage_filter,
            "triage_filter_options": [dict(option) for option in self.triage_filter_options],
            "page_size_options": list(self.page_size_options),
            "total_pages": self.total_pages,
            "visible_start": self.visible_start,
            "visible_end": self.visible_end,
            "has_previous": self.has_previous,
            "previous_page": self.previous_page,
            "next_page": self.next_page,
            "has_more": self.has_more,
            "total_available": self.total_available,
            "raw_total_available": self.raw_total_available,
            "page_result_count": self.page_result_count,
            "filter_requestable": self.filter_requestable,
            "filter_has_cover": self.filter_has_cover,
            "filter_high_confidence": self.filter_high_confidence,
            "filters_active": self.filters_active,
            "open_search_url": self.open_search_url,
            "query_label": self.query_label,
            "context_hint": self.context_hint,
            "message": self.message,
            "message_level": self.message_level,
            "pagination_mode": self.pagination_mode,
            "progressive_refinement": self.progressive_refinement,
            "progressive_refinement_note": self.progressive_refinement_note,
            "results": [result.to_template_dict() for result in self.results],
            "groups": [group.to_template_dict() for group in self.groups],
            "summary": self.summary.to_template_dict(),
        }


@dataclass(frozen=True)
class ShelfmarkClientConfig:
    enabled: bool
    base_url: str
    browser_base_url: str
    username: str | None
    password: str | None
    timeout_seconds: int = DEFAULT_SHELFMARK_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ShelfmarkSearchResponse:
    books: tuple[dict[str, Any], ...]
    page: int = DEFAULT_SHELFMARK_PAGE
    total_found: int = 0
    has_more: bool = False


def clear_shelfmark_detail_cache() -> None:
    _SHELFMARK_DETAIL_CACHE.clear()


def clear_shelfmark_cover_cache() -> None:
    _SHELFMARK_COVER_CACHE.clear()


def clear_shelfmark_scan_cache() -> None:
    _SHELFMARK_SCAN_CACHE.clear()


def get_shelfmark_client_config() -> ShelfmarkClientConfig:
    base_url = str(getattr(config, "config_shelfmark_url", "") or "").strip()
    browser_base_url = str(getattr(config, "config_shelfmark_browser_url", "") or "").strip() or base_url
    username = str(getattr(config, "config_shelfmark_username", "") or "").strip() or None
    password = str(getattr(config, "config_shelfmark_password_e", "") or "").strip() or None
    enabled = bool(getattr(config, "config_shelfmark_search", False) and base_url)
    return ShelfmarkClientConfig(
        enabled=enabled,
        base_url=base_url,
        browser_base_url=browser_base_url,
        username=username,
        password=password,
    )


def _base_url_host_port(base_url: str) -> tuple[str, int]:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if not parsed.scheme or not host:
        raise ShelfmarkIntegrationError(
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
    *,
    resolver: Callable[..., Sequence[Any]] | None = None,
) -> set[ipaddress._BaseNetwork]:
    try:
        return {_ip_network_for_address(host)}
    except ValueError:
        pass

    lookup = resolver or socket.getaddrinfo
    try:
        records = lookup(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ShelfmarkIntegrationError(
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
        raise ShelfmarkIntegrationError(
            _("Shelfmark Base URL could not be resolved for trusted server-side access.")
        )
    return trusted_networks


def build_shelfmark_validator(
    config_data: ShelfmarkClientConfig,
    *,
    resolver: Callable[..., Sequence[Any]] | None = None,
) -> AddrValidator:
    host, port = _base_url_host_port(config_data.base_url)
    trusted_networks = _resolve_trusted_ip_networks(host, port, resolver=resolver)
    return AddrValidator(
        ip_whitelist=trusted_networks,
        port_whitelist={port},
    )


def create_shelfmark_session(
    config_data: ShelfmarkClientConfig,
    *,
    session_factory: Callable[..., SafeSession] = SafeSession,
    resolver: Callable[..., Sequence[Any]] | None = None,
):
    validator = build_shelfmark_validator(config_data, resolver=resolver)
    return session_factory(validator=validator)


def build_shelfmark_open_url(
    base_url: str,
    *,
    title: str,
    authors: Sequence[str],
    hardcover_id: str | None,
    content_type: str = SHELFMARK_CONTENT_TYPE,
) -> str:
    # Shelfmark does not currently expose a stable URL-addressable metadata-book
    # detail route. Use the most specific browser search URL it supports today.
    primary_author = _normalize_text(authors[0]) if authors else None
    query_terms = [value for value in (title, primary_author, hardcover_id) if value]
    search_query = " ".join(query_terms[:2]) or (hardcover_id or "")
    params: dict[str, str] = {
        "content_type": content_type,
        "sort": DEFAULT_SHELFMARK_SORT,
    }
    if search_query:
        params["query"] = search_query
    if title:
        params["title"] = title
    if primary_author:
        params["author"] = primary_author
    return _with_query(_join_base_url(base_url, "/"), params)


def build_shelfmark_search_url(
    base_url: str,
    *,
    query: str,
    content_type: str = SHELFMARK_CONTENT_TYPE,
    page: int = DEFAULT_SHELFMARK_PAGE,
    page_size: int = DEFAULT_SHELFMARK_LIMIT,
    sort: str = DEFAULT_SHELFMARK_SORT,
) -> str:
    params = {
        "content_type": content_type,
        "sort": sort or DEFAULT_SHELFMARK_SORT,
        "limit": str(_normalize_page_size(page_size)),
        "page": str(page),
        "query": query,
    }
    return _with_query(_join_base_url(base_url, "/"), params)


def build_shelfmark_request_payload(book: Mapping[str, Any]) -> dict[str, Any] | None:
    hardcover_id = _extract_hardcover_id(book)
    title = _resolve_shelfmark_title(book)
    authors = _resolve_shelfmark_authors(book)
    if not hardcover_id or not title or not authors:
        return None

    payload: dict[str, Any] = {
        "book_data": {
            "title": title,
            "author": authors[0],
            "provider": SHELFMARK_METADATA_PROVIDER,
            "provider_id": hardcover_id,
        },
        "content_type": SHELFMARK_CONTENT_TYPE,
        "context": {
            "source": "*",
            "content_type": SHELFMARK_CONTENT_TYPE,
            "request_level": SHELFMARK_REQUEST_KIND,
        },
    }

    subtitle = _normalize_text(book.get("subtitle"))
    if subtitle:
        payload["book_data"]["subtitle"] = subtitle
    source_url = _normalize_text(book.get("source_url"))
    if source_url:
        payload["book_data"]["source_url"] = source_url

    return payload


def build_shelfmark_advanced_query(term: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    title = _normalize_text(term.get("title"))
    author = _normalize_text(term.get("authors"))
    publisher = _normalize_text(term.get("publisher"))
    fragments: list[str] = []
    labels: list[str] = []
    seen: set[str] = set()

    candidates = (
        (_("title"), title),
        (_("author"), author.replace("|", ",") if author else None),
        (_("publisher"), publisher),
    )
    for label, raw_value in candidates:
        normalized = _normalize_text(raw_value)
        if not normalized:
            continue
        dedupe_key = normalized.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        fragments.append(normalized)
        labels.append(label)

    if not fragments:
        return None, tuple()

    return " ".join(fragments), tuple(labels)


def get_shelfmark_sort_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "value": value,
            "label": _(label),
        }
        for value, label in SHELFMARK_SORT_OPTIONS
    )


def get_shelfmark_series_filter_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "value": value,
            "label": _(label),
        }
        for value, label in SHELFMARK_SERIES_FILTER_OPTIONS
    )


def get_shelfmark_triage_filter_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "value": value,
            "label": _(label),
        }
        for value, label in SHELFMARK_TRIAGE_FILTER_OPTIONS
    )


def _normalize_page_size(value: Any) -> int:
    normalized = _normalize_int(value) or DEFAULT_SHELFMARK_LIMIT
    if normalized in SHELFMARK_PAGE_SIZE_OPTIONS:
        return normalized
    return DEFAULT_SHELFMARK_LIMIT


def _normalize_sort(value: Any) -> str:
    normalized = (_normalize_text(value) or DEFAULT_SHELFMARK_SORT).lower()
    if normalized in {item[0] for item in SHELFMARK_SORT_OPTIONS}:
        return normalized
    return DEFAULT_SHELFMARK_SORT


def _normalize_series_filter(value: Any) -> str:
    normalized = (_normalize_text(value) or DEFAULT_SHELFMARK_SERIES_FILTER).lower()
    if normalized in {item[0] for item in SHELFMARK_SERIES_FILTER_OPTIONS}:
        return normalized
    return DEFAULT_SHELFMARK_SERIES_FILTER


def _normalize_triage_filter(value: Any) -> str:
    normalized = (_normalize_text(value) or DEFAULT_SHELFMARK_TRIAGE_FILTER).lower()
    if normalized in {item[0] for item in SHELFMARK_TRIAGE_FILTER_OPTIONS}:
        return normalized
    return DEFAULT_SHELFMARK_TRIAGE_FILTER


def _normalize_flag(value: Any) -> bool:
    normalized = (_normalize_text(value) or "").lower()
    return normalized in {"1", "true", "yes", "on"}


def parse_shelfmark_probe_state(
    auth_payload: Mapping[str, Any] | None,
    policy_payload: Mapping[str, Any] | None,
) -> ShelfmarkProbeState:
    authenticated = bool(auth_payload and auth_payload.get("authenticated"))
    auth_required = True if auth_payload is None else bool(auth_payload.get("auth_required", True))
    requests_enabled = bool(policy_payload and policy_payload.get("requests_enabled"))
    ebook_mode = None
    if policy_payload and isinstance(policy_payload.get("defaults"), Mapping):
        raw_mode = policy_payload["defaults"].get("ebook")
        ebook_mode = str(raw_mode).strip().lower() if raw_mode else None
    return ShelfmarkProbeState(
        authenticated=authenticated,
        auth_required=auth_required,
        requests_enabled=requests_enabled,
        ebook_mode=ebook_mode,
        probe_available=auth_payload is not None,
    )


def select_shelfmark_action(
    *,
    already_in_library: bool,
    library_book_url: str | None,
    hardcover_id: str | None,
    request_payload: Mapping[str, Any] | None,
    missing_request_requirements: Sequence[str] = (),
    probe_state: ShelfmarkProbeState | None,
) -> ShelfmarkActionState:
    if already_in_library and library_book_url:
        return ShelfmarkActionState(
            mode="view_library",
            label=_("Open existing CWA book"),
            hint=None,
            button_class="btn-success",
            icon_class="glyphicon glyphicon-book",
        )

    if not hardcover_id:
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=_("Direct request needs an exact Hardcover ID."),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if request_payload is None:
        requirement_hint = _describe_missing_request_requirements(missing_request_requirements)
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=requirement_hint
            or _("Direct request needs more exact metadata from Shelfmark."),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if probe_state is None or not probe_state.probe_available:
        return ShelfmarkActionState(
            mode="request",
            label=_("Request in Shelfmark"),
            hint=None,
            button_class="btn-primary",
            icon_class="glyphicon glyphicon-send",
        )

    if not probe_state.authenticated:
        suffix = _("Login required") if probe_state.auth_required else _("Open in Shelfmark")
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=_("Shelfmark needs a live browser login here. %(suffix)s.", suffix=suffix),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if probe_state.requests_enabled and probe_state.ebook_mode == SHELFMARK_REQUEST_MODE:
        return ShelfmarkActionState(
            mode="request",
            label=_("Request in Shelfmark"),
            hint=None,
            button_class="btn-primary",
            icon_class="glyphicon glyphicon-send",
        )

    return ShelfmarkActionState(
        mode="open",
        label=_("Open in Shelfmark"),
        hint=_("Open this in Shelfmark to continue under the current request policy."),
        button_class="btn-default",
        icon_class="glyphicon glyphicon-new-window",
    )


def build_shelfmark_library_state(
    *,
    library_match: ShelfmarkLibraryMatch | None,
    hardcover_id: str | None,
) -> ShelfmarkLibraryState:
    if library_match is not None:
        return ShelfmarkLibraryState(
            key="already_in_library",
            label=_("In library"),
            hint=None,
            row_class="success",
            badge_class="label-success",
            panel_class="panel-success",
            icon_class="glyphicon glyphicon-ok-circle",
        )

    if hardcover_id:
        return ShelfmarkLibraryState(
            key="external_candidate",
            label=None,
            hint=None,
            row_class="info",
            badge_class=None,
            panel_class="panel-info",
            icon_class="glyphicon glyphicon-cloud-download",
        )

    return ShelfmarkLibraryState(
        key="library_match_unavailable",
        label=_("No Hardcover ID"),
        hint=_("Duplicate check is unavailable because Shelfmark did not return an exact Hardcover ID."),
        row_class="warning",
        badge_class="label-warning",
        panel_class="panel-warning",
        icon_class="glyphicon glyphicon-question-sign",
    )


def build_shelfmark_workflow_state(
    *,
    already_in_library: bool,
    hardcover_id: str | None,
    request_payload: Mapping[str, Any] | None,
) -> ShelfmarkWorkflowState | None:
    if already_in_library:
        return ShelfmarkWorkflowState(
            key="imported",
            label=_("In library"),
            chip_class="shelfmark-status-chip--imported",
        )

    if hardcover_id and request_payload is not None:
        return ShelfmarkWorkflowState(
            key="available",
            label=_("Available to request"),
            chip_class="shelfmark-status-chip--available",
        )

    return None


def build_library_match_map(rows: Iterable[Mapping[str, Any]]) -> dict[str, ShelfmarkLibraryMatch]:
    matches: dict[str, ShelfmarkLibraryMatch] = {}
    for row in rows:
        hardcover_id = _normalize_text(row.get("hardcover_id"))
        if not hardcover_id or hardcover_id in matches:
            continue
        try:
            book_id = int(row.get("book_id"))
        except (TypeError, ValueError):
            continue
        matches[hardcover_id] = ShelfmarkLibraryMatch(
            hardcover_id=hardcover_id,
            book_id=book_id,
            title=_normalize_text(row.get("title")) or "",
        )
    return matches


def lookup_visible_library_matches(hardcover_ids: Sequence[str]) -> dict[str, ShelfmarkLibraryMatch]:
    normalized_ids = [value for value in (_normalize_text(identifier) for identifier in hardcover_ids) if value]
    if not normalized_ids:
        return {}

    rows = (
        calibre_db.session.query(
            db.Identifiers.val.label("hardcover_id"),
            db.Books.id.label("book_id"),
            db.Books.title.label("title"),
        )
        .join(db.Books, db.Identifiers.book == db.Books.id)
        .filter(func.lower(db.Identifiers.type) == "hardcover-id")
        .filter(db.Identifiers.val.in_(normalized_ids))
        .filter(calibre_db.common_filters())
        .order_by(db.Books.id.asc())
        .all()
    )

    return build_library_match_map(
        {
            "hardcover_id": row.hardcover_id,
            "book_id": row.book_id,
            "title": row.title,
        }
        for row in rows
    )


def _normalize_series_name_key(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return re.sub(r"\s+", " ", normalized.casefold()).strip() or None


def _largest_contiguous_series_prefix(positions: Sequence[float]) -> int | None:
    normalized_positions = sorted(
        {int(position) for position in positions if position > 0 and float(position).is_integer()}
    )
    if not normalized_positions:
        return None

    expected = 1
    for position in normalized_positions:
        if position != expected:
            return expected - 1
        expected += 1
    return expected - 1


def build_owned_series_map(rows: Iterable[Mapping[str, Any]]) -> dict[str, ShelfmarkOwnedSeries]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        series_name = _normalize_text(row.get("series_name"))
        key = _normalize_series_name_key(series_name)
        if not key:
            continue

        item = grouped.setdefault(
            key,
            {
                "series_name": series_name or "",
                "book_ids": set(),
                "positions": [],
            },
        )
        book_id = _normalize_int(row.get("book_id"))
        if book_id is not None:
            item["book_ids"].add(book_id)
        series_position = _normalize_series_position(row.get("series_position"))
        if series_position is not None:
            item["positions"].append(series_position)

    owned_series: dict[str, ShelfmarkOwnedSeries] = {}
    for key, item in grouped.items():
        owned_positions = tuple(sorted(set(item["positions"])))
        max_position = owned_positions[-1] if owned_positions else None
        owned_series[key] = ShelfmarkOwnedSeries(
            key=key,
            series_name=item["series_name"],
            book_count=len(item["book_ids"]),
            owned_positions=owned_positions,
            max_position=max_position,
            contiguous_position=_largest_contiguous_series_prefix(owned_positions),
        )
    return owned_series


def lookup_visible_owned_series(series_names: Sequence[str]) -> dict[str, ShelfmarkOwnedSeries]:
    normalized_names = {
        value
        for value in (_normalize_series_name_key(series_name) for series_name in series_names)
        if value
    }
    if not normalized_names:
        return {}

    rows = (
        calibre_db.session.query(
            db.Series.name.label("series_name"),
            db.Books.id.label("book_id"),
            db.Books.series_index.label("series_position"),
        )
        .join(db.books_series_link, db.books_series_link.c.series == db.Series.id)
        .join(db.Books, db.books_series_link.c.book == db.Books.id)
        .filter(func.lower(db.Series.name).in_(tuple(normalized_names)))
        .filter(calibre_db.common_filters())
        .order_by(db.Series.name.asc(), db.Books.id.asc())
        .all()
    )

    return build_owned_series_map(
        {
            "series_name": row.series_name,
            "book_id": row.book_id,
            "series_position": row.series_position,
        }
        for row in rows
    )


def _build_series_context_badges(
    *,
    matched: bool,
    is_continuation: bool,
    is_next_missing: bool,
) -> tuple[dict[str, str], ...]:
    if is_next_missing:
        return ({"label": _("Next missing"), "badge_class": "label-primary"},)
    if is_continuation:
        return ({"label": _("Continue series"), "badge_class": "label-info"},)
    if matched:
        return ({"label": _("Owned series"), "badge_class": "label-default"},)
    return tuple()


def _build_series_context_facts(
    *,
    matched: bool,
    owned_book_count: int,
    owned_contiguous_position: int | None,
    owned_max_position: float | None,
    is_continuation: bool,
    is_next_missing: bool,
) -> tuple[str, ...]:
    if not matched:
        return tuple()

    facts: list[str] = []
    if owned_book_count:
        label = _("book") if owned_book_count == 1 else _("books")
        facts.append(
            _("%(count)s %(label)s owned in this series", count=owned_book_count, label=label)
        )

    if owned_contiguous_position and owned_contiguous_position > 0:
        facts.append(_("Owned through %(position)s", position=owned_contiguous_position))

    return tuple(facts)


def _build_series_context_detail_value(context: ShelfmarkSeriesContext) -> str | None:
    if not context.matched:
        return None
    parts: list[str] = []
    if context.is_next_missing:
        parts.append(_("Next missing"))
    elif context.is_continuation:
        parts.append(_("Continue series"))
    else:
        parts.append(_("Owned series"))
    parts.extend(context.facts)
    return " \u00b7 ".join(part for part in parts if part)


def build_shelfmark_series_contexts(
    results: Sequence[ShelfmarkResultView],
    owned_series: Mapping[str, ShelfmarkOwnedSeries],
) -> tuple[ShelfmarkSeriesContext | None, ...]:
    expected_next_positions: dict[str, int | None] = {}
    for key, owned in owned_series.items():
        if owned.contiguous_position is None:
            expected_next_positions[key] = None
        else:
            expected_next_positions[key] = owned.contiguous_position + 1

    contexts: list[ShelfmarkSeriesContext | None] = []
    for result in results:
        series_key = _normalize_series_name_key(result.series_name)
        owned = owned_series.get(series_key or "")
        if owned is None:
            contexts.append(None)
            continue

        numeric_position = result.series_position
        expected_next = expected_next_positions.get(owned.key)
        is_next_missing = bool(
            not result.already_in_library
            and numeric_position is not None
            and float(numeric_position).is_integer()
            and expected_next is not None
            and int(numeric_position) == expected_next
        )
        is_continuation = bool(
            not result.already_in_library
            and numeric_position is not None
            and owned.max_position is not None
            and numeric_position > owned.max_position
        )
        context = ShelfmarkSeriesContext(
            matched=True,
            owned_series_name=owned.series_name,
            owned_book_count=owned.book_count,
            owned_max_position=owned.max_position,
            owned_contiguous_position=owned.contiguous_position,
            is_continuation=is_continuation,
            is_next_missing=is_next_missing,
        )
        context = replace(
            context,
            badges=_build_series_context_badges(
                matched=context.matched,
                is_continuation=context.is_continuation and not context.is_next_missing,
                is_next_missing=context.is_next_missing,
            ),
        )
        context = replace(
            context,
            facts=_build_series_context_facts(
                matched=context.matched,
                owned_book_count=context.owned_book_count,
                owned_contiguous_position=context.owned_contiguous_position,
                owned_max_position=context.owned_max_position,
                is_continuation=context.is_continuation and not context.is_next_missing,
                is_next_missing=context.is_next_missing,
            ),
        )
        contexts.append(replace(context, detail_value=_build_series_context_detail_value(context)))

    return tuple(contexts)


def _series_rank_key(result: ShelfmarkResultView) -> tuple[int, int, int, float]:
    context = result.series_context
    if context and context.is_next_missing:
        bucket = 0
    elif context and context.is_continuation:
        bucket = 1
    elif context and context.matched:
        bucket = 2
    else:
        bucket = 3

    duplicate_rank = 1 if result.already_in_library else 0
    request_rank = 0 if (result.hardcover_id and result.request_payload) else 1
    series_position = result.series_position if result.series_position is not None else float("inf")
    return bucket, duplicate_rank, request_rank, series_position


def _triage_rank_key(result: ShelfmarkResultView) -> tuple[int, int, int]:
    triage = result.triage_state
    strong_rank = 0 if triage and triage.strong_candidate else 1
    metadata_rank = 0 if triage and triage.metadata_rich else 1
    popularity_rank = 0 if triage and triage.popularity_signal else 1
    return strong_rank, metadata_rank, popularity_rank


def _quality_rank_key(result: ShelfmarkResultView) -> tuple[int, int, int, int]:
    quality = result.quality_state
    confidence_rank = 0 if quality and quality.high_confidence else 1
    rating_rank = 0 if quality and quality.rating_signal else 1
    popularity_rank = 0 if quality and quality.popularity_signal else 1
    metadata_rank = 0 if quality and quality.metadata_complete else 1
    return confidence_rank, rating_rank, popularity_rank, metadata_rank


def _rank_visible_results(results: Sequence[ShelfmarkResultView]) -> tuple[ShelfmarkResultView, ...]:
    indexed_results = list(enumerate(results))
    indexed_results.sort(
        key=lambda item: (
            *_series_rank_key(item[1]),
            *_triage_rank_key(item[1]),
            *_quality_rank_key(item[1]),
            item[0],
        )
    )
    return tuple(result for _, result in indexed_results)


def build_shelfmark_result_view(
    book: Mapping[str, Any],
    *,
    library_match: ShelfmarkLibraryMatch | None,
    detail_url: str | None,
    shelfmark_browser_base_url: str,
    probe_state: ShelfmarkProbeState | None = None,
    series_context: ShelfmarkSeriesContext | None = None,
) -> ShelfmarkResultView:
    title = _resolve_shelfmark_title(book) or _("Unknown title")
    authors = tuple(_resolve_shelfmark_authors(book))
    hardcover_id = _extract_hardcover_id(book)
    publish_year = _resolve_publish_year(book)
    description_html = _sanitize_description_html(book.get("description"))
    series_name = _resolve_series_name(book)
    series_position = _resolve_series_position(book)
    series_count = _resolve_series_count(book)
    rating = _resolve_rating_value(book)
    ratings_count = _resolve_ratings_count(book)
    reviews_count = _resolve_reviews_count(book)
    readers_count = _resolve_readers_count(book)
    pages = _resolve_pages(book)
    editions_count = _resolve_editions_count(book)
    lists_count = _resolve_lists_count(book)
    library_book_url = (
        url_for("web.show_book", book_id=library_match.book_id)
        if library_match is not None
        else None
    )
    request_payload = build_shelfmark_request_payload(book)
    missing_request_requirements = _missing_request_requirements(book)
    library_state = build_shelfmark_library_state(
        library_match=library_match,
        hardcover_id=hardcover_id,
    )
    action = select_shelfmark_action(
        already_in_library=library_match is not None,
        library_book_url=library_book_url,
        hardcover_id=hardcover_id,
        request_payload=request_payload,
        missing_request_requirements=missing_request_requirements,
        probe_state=probe_state,
    )
    return ShelfmarkResultView(
        provider=_normalize_text(book.get("provider")) or SHELFMARK_METADATA_PROVIDER,
        provider_id=_normalize_text(book.get("provider_id")) or "",
        title=title,
        subtitle=_resolve_shelfmark_subtitle(book),
        authors=authors,
        cover_url=_normalize_shelfmark_cover_url(
            shelfmark_browser_base_url,
            _resolve_shelfmark_cover_value(book),
        ),
        description=_plain_text_from_html(description_html),
        publish_year=publish_year,
        source_url=_resolve_source_url(book),
        display_fields=_normalize_display_fields(book.get("display_fields")),
        rating=rating,
        ratings_count=ratings_count,
        reviews_count=reviews_count,
        readers_count=readers_count,
        hardcover_id=hardcover_id,
        already_in_library=library_match is not None,
        library_book_id=library_match.book_id if library_match is not None else None,
        library_book_title=library_match.title if library_match is not None else None,
        library_book_url=library_book_url,
        detail_url=detail_url,
        shelfmark_base_url=shelfmark_browser_base_url,
        shelfmark_open_url=build_shelfmark_open_url(
            shelfmark_browser_base_url,
            title=title,
            authors=authors,
            hardcover_id=hardcover_id,
        ),
        request_payload=request_payload,
        library_state=library_state,
        action=action,
        pages=pages,
        editions_count=editions_count,
        lists_count=lists_count,
        description_html=description_html,
        series_name=series_name,
        series_position=series_position,
        series_count=series_count,
        series_display=_format_series_display(series_name, series_position),
        series_url=_resolve_series_url(book),
        facts=_build_result_facts(book, publish_year=publish_year),
        detail_stats=_build_detail_stats(book, publish_year=publish_year),
        genres=_resolve_genres(book),
        moods=_resolve_moods(book),
        content_warnings=_resolve_content_warnings(book),
        series_context=series_context,
        workflow_state=build_shelfmark_workflow_state(
            already_in_library=library_match is not None,
            hardcover_id=hardcover_id,
            request_payload=request_payload,
        ),
    )


def summarize_shelfmark_results(
    results: Sequence[ShelfmarkResultView],
    *,
    total_available: int | None = None,
    raw_total_available: int | None = None,
    has_more: bool = False,
) -> ShelfmarkResultSummary:
    total_results = len(results)
    already_in_library = sum(1 for result in results if result.library_state.key == "already_in_library")
    library_match_unavailable = sum(
        1 for result in results if result.library_state.key == "library_match_unavailable"
    )
    external_candidates = total_results - already_in_library - library_match_unavailable
    return ShelfmarkResultSummary(
        total_results=total_results,
        total_available=max(total_results, int(total_available or 0)),
        raw_total_available=max(int(raw_total_available or 0), int(total_available or 0), total_results),
        has_more=bool(has_more),
        already_in_library=already_in_library,
        external_candidates=external_candidates,
        library_match_unavailable=library_match_unavailable,
    )


def group_shelfmark_results(results: Sequence[ShelfmarkResultView]) -> tuple[ShelfmarkResultGroup, ...]:
    grouped: list[ShelfmarkResultGroup] = []
    definitions = (
        (
            "already_in_library",
            _("Already in Your Library"),
            None,
        ),
        (
            "external_candidate",
            _("External Candidates"),
            None,
        ),
        (
            "library_match_unavailable",
            _("External Results Without Exact Hardcover ID"),
            _("Duplicate checking is unavailable for these results because Shelfmark did not return an exact Hardcover ID."),
        ),
    )

    for key, title, hint in definitions:
        members = tuple(result for result in results if result.library_state.key == key)
        if not members:
            continue
        grouped.append(
            ShelfmarkResultGroup(
                key=key,
                title=title,
                hint=hint,
                panel_class=members[0].library_state.panel_class,
                badge_class=members[0].library_state.badge_class,
                icon_class=members[0].library_state.icon_class,
                results=members,
            )
        )

    return tuple(grouped)


def _book_has_detail_identity(book: Mapping[str, Any]) -> bool:
    return bool(
        _normalize_text(book.get("provider"))
        and _normalize_text(book.get("provider_id"))
    )


def _needs_detail_enrichment(book: Mapping[str, Any]) -> bool:
    if not _book_has_detail_identity(book):
        return False

    series_name = _resolve_series_name(book)
    series_position = _resolve_series_position(book)
    incomplete_series_metadata = bool(series_name) != bool(series_position is not None)

    return bool(
        not _resolve_shelfmark_cover_value(book)
        or not _normalize_text(book.get("description"))
        or _resolve_rating_value(book) is None
        or _resolve_ratings_count(book) is None
        or _resolve_readers_count(book) is None
        or _resolve_pages(book) is None
        or incomplete_series_metadata
    )


def _has_usable_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return True


def _merge_book_details(
    search_book: Mapping[str, Any],
    detail_book: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(search_book)
    if not detail_book:
        return merged

    preferred_keys = (
        "title",
        "subtitle",
        "authors",
        "author",
        "search_title",
        "search_author",
        "description",
        "publish_year",
        "release_year",
        "release_date",
        "source_url",
        "slug",
        "canonical",
        "canonical_id",
        "display_fields",
        "genres",
        "series_id",
        "series_url",
        "series_slug",
        "series_name",
        "series_position",
        "series_count",
        "featured_book_series",
        "featured_book_series_id",
        "book_series",
        "rating",
        "ratings_count",
        "reviews_count",
        "users_count",
        "users_read_count",
        "pages",
        "editions_count",
        "editions",
        "editions_aggregate",
        "lists_count",
        "moods",
        "content_warnings",
        "warnings",
        "taggings",
        "cached_tags",
        "cached_featured_series",
        "default_audio_edition",
        "default_audio_edition_id",
        "default_cover_edition",
        "default_cover_edition_id",
        "default_ebook_edition",
        "default_ebook_edition_id",
        "default_physical_edition",
        "default_physical_edition_id",
        "edition",
        "edition_id",
        "content_type",
        "format",
        "edition_format",
        "media_type",
        "physical_format",
        "object_type",
        "reading_format",
        "provider_display_name",
        "cover_url",
        "preview",
        "cached_image",
        "image",
    )

    for key in preferred_keys:
        value = detail_book.get(key)
        if _has_usable_value(value):
            merged[key] = value
    return merged


def _prune_ttl_cache(
    cache: OrderedDict[Any, tuple[float, Any]],
    *,
    ttl_seconds: int,
    max_entries: int,
    now: float | None = None,
) -> None:
    current_time = monotonic() if now is None else now
    expired_keys = [
        cache_key
        for cache_key, (cached_at, _) in cache.items()
        if current_time - cached_at >= ttl_seconds
    ]
    for cache_key in expired_keys:
        cache.pop(cache_key, None)

    while len(cache) > max_entries:
        cache.popitem(last=False)


def _prune_shelfmark_detail_cache(now: float | None = None) -> None:
    _prune_ttl_cache(
        _SHELFMARK_DETAIL_CACHE,
        ttl_seconds=SHELFMARK_DETAIL_CACHE_TTL_SECONDS,
        max_entries=SHELFMARK_DETAIL_CACHE_MAX_ENTRIES,
        now=now,
    )


def _get_cached_shelfmark_detail_book(
    base_url: str,
    provider: str,
    provider_id: str,
) -> dict[str, Any] | None:
    now = monotonic()
    _prune_shelfmark_detail_cache(now)
    cache_key = (base_url, provider, provider_id)
    cached_entry = _SHELFMARK_DETAIL_CACHE.get(cache_key)
    if not cached_entry:
        return None

    cached_at, cached_payload = cached_entry
    if now - cached_at >= SHELFMARK_DETAIL_CACHE_TTL_SECONDS:
        _SHELFMARK_DETAIL_CACHE.pop(cache_key, None)
        return None
    _SHELFMARK_DETAIL_CACHE.move_to_end(cache_key)
    return dict(cached_payload)


def _remember_shelfmark_detail_book(
    base_url: str,
    provider: str,
    provider_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _prune_shelfmark_detail_cache()
    cache_key = (base_url, provider, provider_id)
    cached_payload = dict(payload)
    _SHELFMARK_DETAIL_CACHE[cache_key] = (monotonic(), cached_payload)
    _SHELFMARK_DETAIL_CACHE.move_to_end(cache_key)
    _prune_shelfmark_detail_cache()
    return dict(cached_payload)


def _prune_shelfmark_cover_cache(now: float | None = None) -> None:
    _prune_ttl_cache(
        _SHELFMARK_COVER_CACHE,
        ttl_seconds=SHELFMARK_COVER_CACHE_TTL_SECONDS,
        max_entries=SHELFMARK_COVER_CACHE_MAX_ENTRIES,
        now=now,
    )


def _prune_shelfmark_scan_cache(now: float | None = None) -> None:
    current_time = monotonic() if now is None else now
    expired_keys = [
        cache_key
        for cache_key, (cached_at, _, _, _, _) in _SHELFMARK_SCAN_CACHE.items()
        if current_time - cached_at >= SHELFMARK_SCAN_CACHE_TTL_SECONDS
    ]
    for cache_key in expired_keys:
        _SHELFMARK_SCAN_CACHE.pop(cache_key, None)

    while len(_SHELFMARK_SCAN_CACHE) > SHELFMARK_SCAN_CACHE_MAX_ENTRIES:
        _SHELFMARK_SCAN_CACHE.popitem(last=False)


def _get_cached_shelfmark_cover_url(base_url: str, cover_value: str) -> str | None:
    now = monotonic()
    _prune_shelfmark_cover_cache(now)
    cache_key = (base_url, cover_value)
    cached_entry = _SHELFMARK_COVER_CACHE.get(cache_key)
    if not cached_entry:
        return None

    cached_at, cached_value = cached_entry
    if now - cached_at >= SHELFMARK_COVER_CACHE_TTL_SECONDS:
        _SHELFMARK_COVER_CACHE.pop(cache_key, None)
        return None
    _SHELFMARK_COVER_CACHE.move_to_end(cache_key)
    return cached_value


def _remember_shelfmark_cover_url(base_url: str, cover_value: str, resolved_url: str) -> str:
    _prune_shelfmark_cover_cache()
    cache_key = (base_url, cover_value)
    _SHELFMARK_COVER_CACHE[cache_key] = (monotonic(), resolved_url)
    _SHELFMARK_COVER_CACHE.move_to_end(cache_key)
    _prune_shelfmark_cover_cache()
    return resolved_url


def _get_cached_shelfmark_scan(
    base_url: str,
    query: str,
    sort: str,
    *,
    page: int,
    page_size: int,
) -> ShelfmarkSearchResponse | None:
    now = monotonic()
    _prune_shelfmark_scan_cache(now)
    cache_key = (base_url, query, sort, page, page_size)
    cached_entry = _SHELFMARK_SCAN_CACHE.get(cache_key)
    if not cached_entry:
        return None

    cached_at, cached_books, cached_page, total_found, has_more = cached_entry
    if now - cached_at >= SHELFMARK_SCAN_CACHE_TTL_SECONDS:
        _SHELFMARK_SCAN_CACHE.pop(cache_key, None)
        return None

    _SHELFMARK_SCAN_CACHE.move_to_end(cache_key)
    return ShelfmarkSearchResponse(
        books=tuple(dict(book) for book in cached_books),
        page=cached_page,
        total_found=total_found,
        has_more=has_more,
    )


def _remember_shelfmark_scan(
    base_url: str,
    query: str,
    sort: str,
    *,
    page: int,
    page_size: int,
    response: ShelfmarkSearchResponse,
) -> ShelfmarkSearchResponse:
    _prune_shelfmark_scan_cache()
    cache_key = (base_url, query, sort, page, page_size)
    cached_books = tuple(dict(book) for book in response.books)
    _SHELFMARK_SCAN_CACHE[cache_key] = (
        monotonic(),
        cached_books,
        max(DEFAULT_SHELFMARK_PAGE, _normalize_int(response.page) or page),
        int(response.total_found or len(cached_books)),
        bool(response.has_more),
    )
    _SHELFMARK_SCAN_CACHE.move_to_end(cache_key)
    _prune_shelfmark_scan_cache()
    return ShelfmarkSearchResponse(
        books=tuple(dict(book) for book in cached_books),
        page=max(DEFAULT_SHELFMARK_PAGE, _normalize_int(response.page) or page),
        total_found=int(response.total_found or len(cached_books)),
        has_more=bool(response.has_more),
    )


def _fetch_shelfmark_search_page(
    client: "ShelfmarkClient",
    query: str,
    *,
    page: int,
    page_size: int,
    sort: str,
) -> ShelfmarkSearchResponse:
    cached_page = _get_cached_shelfmark_scan(
        client.config.base_url,
        query,
        sort,
        page=page,
        page_size=page_size,
    )
    if cached_page is not None:
        return cached_page

    response = client.search_books(
        query,
        limit=page_size,
        page=page,
        sort=sort,
    )
    return _remember_shelfmark_scan(
        client.config.base_url,
        query,
        sort,
        page=page,
        page_size=page_size,
        response=response,
    )


def _get_search_enrichment_detail_book(
    client: "ShelfmarkClient",
    book: Mapping[str, Any],
    local_detail_cache: dict[tuple[str, str], Mapping[str, Any] | None],
) -> Mapping[str, Any] | None:
    provider = _normalize_text(book.get("provider")) or SHELFMARK_METADATA_PROVIDER
    provider_id = _normalize_text(book.get("provider_id")) or ""
    if not provider_id:
        return None

    cache_key = (provider, provider_id)
    if cache_key in local_detail_cache:
        return local_detail_cache[cache_key]

    cached_detail = _get_cached_shelfmark_detail_book(
        client.config.base_url,
        provider,
        provider_id,
    )
    if cached_detail is not None:
        local_detail_cache[cache_key] = cached_detail
        return cached_detail

    if not _needs_detail_enrichment(book):
        local_detail_cache[cache_key] = None
        return None

    try:
        detail_book = client.fetch_book(provider, provider_id)
    except ShelfmarkIntegrationError as exc:
        log.debug(
            "Shelfmark detail enrichment skipped for %s/%s: %s",
            provider,
            provider_id,
            exc,
        )
        local_detail_cache[cache_key] = None
        return None

    local_detail_cache[cache_key] = detail_book
    return detail_book


def _enrich_books_with_detail_covers(
    client: "ShelfmarkClient",
    books: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    detail_cache: dict[tuple[str, str], Mapping[str, Any] | None] = {}
    enriched: list[dict[str, Any]] = []

    for book in books:
        normalized_book = dict(book)
        if not _book_has_detail_identity(normalized_book):
            enriched.append(normalized_book)
            continue

        detail_book = _get_search_enrichment_detail_book(client, normalized_book, detail_cache)
        merged_book = _merge_book_details(normalized_book, detail_book)
        provider = _normalize_text(merged_book.get("provider")) or SHELFMARK_METADATA_PROVIDER
        provider_id = _normalize_text(merged_book.get("provider_id")) or ""
        if provider_id:
            _remember_shelfmark_detail_book(
                client.config.base_url,
                provider,
                provider_id,
                merged_book,
            )
        enriched.append(merged_book)

    return tuple(enriched)


def _iter_request_media_signals(book: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for record in (book, _resolve_display_edition(book), _select_edition_by_kind(book, "audio")):
        if isinstance(record, Mapping):
            values.extend(_iter_media_signals(record))
    for label in ("Format", "Edition format", "Media", "Medium"):
        display_value = _lookup_display_field_value(book, label)
        if display_value:
            values.append(display_value.casefold())
    return tuple(values)


def _is_audiobook_result(book: Mapping[str, Any]) -> bool:
    primary_content_type = _resolve_primary_content_type(book)
    if primary_content_type == "audio":
        return True
    if primary_content_type in {"ebook", "physical"}:
        return False

    for value in _iter_request_media_signals(book):
        if value == "audiobook":
            return True
        if any(hint in value for hint in SHELFMARK_AUDIOBOOK_HINTS):
            return True
    return False


def _build_search_result_views(
    books: Sequence[Mapping[str, Any]],
    *,
    detail_url_builder: Callable[[Mapping[str, Any]], str | None],
    shelfmark_browser_base_url: str,
    enrich_with_details: bool = False,
    detail_client: "ShelfmarkClient" | None = None,
) -> tuple[tuple[ShelfmarkResultView, ...], tuple[Mapping[str, Any], ...]]:
    page_books = tuple(book for book in books if not _is_audiobook_result(book))
    if enrich_with_details and detail_client is not None:
        page_books = _enrich_books_with_detail_covers(detail_client, page_books)

    hardcover_ids = [value for value in (_extract_hardcover_id(book) for book in page_books) if value]
    library_matches = lookup_visible_library_matches(hardcover_ids)
    results = tuple(
        build_shelfmark_result_view(
            book,
            library_match=library_matches.get(_extract_hardcover_id(book) or ""),
            detail_url=detail_url_builder(book),
            shelfmark_browser_base_url=shelfmark_browser_base_url,
        )
        for book in page_books
    )
    owned_series = lookup_visible_owned_series(
        [result.series_name for result in results if result.series_name]
    )
    results = tuple(
        replace(result, series_context=context)
        for result, context in zip(
            results,
            build_shelfmark_series_contexts(results, owned_series),
        )
    )
    results = tuple(
        replace(result, quality_state=build_shelfmark_quality_state(result))
        for result in results
    )
    results = tuple(
        replace(
            result,
            triage_state=build_shelfmark_triage_state(
                result,
                quality_state=result.quality_state,
            ),
        )
        for result in results
    )
    return results, page_books


def _result_matches_filters(
    result: ShelfmarkResultView,
    *,
    requestable_only: bool = False,
    has_cover_only: bool = False,
    high_confidence_only: bool = False,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
) -> bool:
    if requestable_only and (
        result.already_in_library
        or not result.hardcover_id
        or not result.request_payload
    ):
        return False
    if has_cover_only and not result.cover_url:
        return False
    if high_confidence_only and not (
        result.quality_state and result.quality_state.high_confidence
    ):
        return False
    if series_filter == "owned" and not (
        result.series_context and result.series_context.matched
    ):
        return False
    if series_filter == "next_missing" and not (
        result.series_context and result.series_context.is_next_missing
    ):
        return False
    if triage_filter == "strong" and not (
        result.triage_state and result.triage_state.strong_candidate
    ):
        return False
    return True


def _result_may_match_filters_after_enrichment(
    result: ShelfmarkResultView,
    raw_book: Mapping[str, Any],
    *,
    requestable_only: bool = False,
    has_cover_only: bool = False,
    high_confidence_only: bool = False,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
) -> bool:
    detail_possible = _book_has_detail_identity(raw_book) and _needs_detail_enrichment(raw_book)
    if not detail_possible:
        return False

    if requestable_only and (
        not result.already_in_library
        and (not result.hardcover_id or not result.request_payload)
    ):
        return True

    if has_cover_only and not result.cover_url:
        return True

    if high_confidence_only and not result.already_in_library and not (
        result.quality_state and result.quality_state.high_confidence
    ):
        return True

    if series_filter == "owned" and not (
        result.series_context and result.series_context.matched
    ):
        return True

    if series_filter == "next_missing" and not (
        result.series_context and result.series_context.is_next_missing
    ):
        return True

    if triage_filter == "strong" and not result.already_in_library and not (
        result.triage_state and result.triage_state.strong_candidate
    ):
        return True

    return False


def _prepare_progressive_page_results(
    results: Sequence[ShelfmarkResultView],
    raw_books: Sequence[Mapping[str, Any]],
    *,
    requestable_only: bool = False,
    has_cover_only: bool = False,
    high_confidence_only: bool = False,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
) -> tuple[ShelfmarkResultView, ...]:
    visible_results: list[ShelfmarkResultView] = []

    for result, raw_book in zip(results, raw_books):
        matches_filters = _result_matches_filters(
            result,
            requestable_only=requestable_only,
            has_cover_only=has_cover_only,
            high_confidence_only=high_confidence_only,
            series_filter=series_filter,
            triage_filter=triage_filter,
        )
        filter_pending = (
            not matches_filters
            and _result_may_match_filters_after_enrichment(
                result,
                raw_book,
                requestable_only=requestable_only,
                has_cover_only=has_cover_only,
                high_confidence_only=high_confidence_only,
                series_filter=series_filter,
                triage_filter=triage_filter,
            )
        )
        if not matches_filters and not filter_pending:
            continue

        visible_results.append(
            replace(
                result,
                needs_progressive_enrichment=bool(
                    _book_has_detail_identity(raw_book)
                    and _needs_detail_enrichment(raw_book)
                ),
                progressive_filter_pending=filter_pending,
            )
        )

    return _rank_visible_results(visible_results)


def _filter_visible_results(
    results: Sequence[ShelfmarkResultView],
    *,
    requestable_only: bool = False,
    has_cover_only: bool = False,
    high_confidence_only: bool = False,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
) -> tuple[ShelfmarkResultView, ...]:
    return tuple(
        result
        for result in results
        if _result_matches_filters(
            result,
            requestable_only=requestable_only,
            has_cover_only=has_cover_only,
            high_confidence_only=high_confidence_only,
            series_filter=series_filter,
            triage_filter=triage_filter,
        )
    )


def result_matches_shelfmark_filters(
    result: ShelfmarkResultView,
    *,
    requestable_only: bool = False,
    has_cover_only: bool = False,
    high_confidence_only: bool = False,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
) -> bool:
    return _result_matches_filters(
        result,
        requestable_only=requestable_only,
        has_cover_only=has_cover_only,
        high_confidence_only=high_confidence_only,
        series_filter=series_filter,
        triage_filter=triage_filter,
    )


def search_shelfmark_results(
    query: str | None,
    *,
    detail_url_builder: Callable[[Mapping[str, Any]], str | None],
    page: int = DEFAULT_SHELFMARK_PAGE,
    page_size: int = DEFAULT_SHELFMARK_LIMIT,
    sort: str = DEFAULT_SHELFMARK_SORT,
    filter_requestable: bool = DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
    filter_has_cover: bool = DEFAULT_SHELFMARK_FILTER_HAS_COVER,
    filter_high_confidence: bool = DEFAULT_SHELFMARK_FILTER_HIGH_CONFIDENCE,
    series_filter: str = DEFAULT_SHELFMARK_SERIES_FILTER,
    triage_filter: str = DEFAULT_SHELFMARK_TRIAGE_FILTER,
    query_label: str | None = None,
    context_hint: str | None = None,
    empty_message: str | None = None,
) -> ShelfmarkSearchSection:
    normalized_query = _normalize_text(query)
    requested_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(page) or DEFAULT_SHELFMARK_PAGE)
    requested_page_size = _normalize_page_size(page_size)
    selected_sort = _normalize_sort(sort)
    selected_series_filter = _normalize_series_filter(series_filter)
    selected_triage_filter = _normalize_triage_filter(triage_filter)
    requestable_only = bool(filter_requestable)
    has_cover_only = bool(filter_has_cover)
    high_confidence_only = bool(filter_high_confidence)
    filters_active = (
        requestable_only != DEFAULT_SHELFMARK_FILTER_REQUESTABLE
        or has_cover_only != DEFAULT_SHELFMARK_FILTER_HAS_COVER
        or high_confidence_only != DEFAULT_SHELFMARK_FILTER_HIGH_CONFIDENCE
        or selected_series_filter != DEFAULT_SHELFMARK_SERIES_FILTER
        or selected_triage_filter != DEFAULT_SHELFMARK_TRIAGE_FILTER
    )
    sort_options = get_shelfmark_sort_options()
    series_filter_options = get_shelfmark_series_filter_options()
    triage_filter_options = get_shelfmark_triage_filter_options()
    config_data = get_shelfmark_client_config()
    if not config_data.enabled:
        return ShelfmarkSearchSection(enabled=False, available=False, query=normalized_query or "")

    if not normalized_query:
        return ShelfmarkSearchSection(
            enabled=True,
            available=True,
            query="",
            page=requested_page,
            page_size=requested_page_size,
            selected_sort=selected_sort,
            sort_options=sort_options,
            selected_series_filter=selected_series_filter,
            series_filter_options=series_filter_options,
            selected_triage_filter=selected_triage_filter,
            triage_filter_options=triage_filter_options,
            page_size_options=SHELFMARK_PAGE_SIZE_OPTIONS,
            total_pages=0,
            visible_start=0,
            visible_end=0,
            has_previous=False,
            previous_page=None,
            next_page=None,
            has_more=False,
            total_available=0,
            raw_total_available=0,
            page_result_count=0,
            filter_requestable=requestable_only,
            filter_has_cover=has_cover_only,
            filter_high_confidence=high_confidence_only,
            filters_active=filters_active,
            open_search_url=(
                build_shelfmark_search_url(
                    config_data.browser_base_url,
                    query="",
                    page=requested_page,
                    page_size=requested_page_size,
                    sort=selected_sort,
                )
                if config_data.browser_base_url
                else None
            ),
            query_label=query_label,
            context_hint=context_hint,
            message=empty_message,
            message_level="info",
            results=tuple(),
            groups=tuple(),
            summary=ShelfmarkResultSummary(),
        )

    client = ShelfmarkClient(config_data)
    try:
        search_response = _fetch_shelfmark_search_page(
            client,
            normalized_query,
            page=requested_page,
            page_size=requested_page_size,
            sort=selected_sort,
        )
        page_results, raw_page_books = _build_search_result_views(
            search_response.books,
            detail_url_builder=detail_url_builder,
            shelfmark_browser_base_url=config_data.browser_base_url,
        )
        results = _prepare_progressive_page_results(
            page_results,
            raw_page_books,
            requestable_only=requestable_only,
            has_cover_only=has_cover_only,
            high_confidence_only=high_confidence_only,
            series_filter=selected_series_filter,
            triage_filter=selected_triage_filter,
        )
        total_available = search_response.total_found
        raw_total_available = search_response.total_found
        current_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(search_response.page) or requested_page)
        total_pages = (
            max(1, math.ceil(total_available / requested_page_size))
            if total_available
            else 0
        )
        visible_start = ((current_page - 1) * requested_page_size) + 1 if results else 0
        visible_end = visible_start + len(results) - 1 if results else 0
        has_more = bool(
            search_response.has_more
            or (
                total_pages
                and current_page < total_pages
            )
        )
        summary = summarize_shelfmark_results(
            results,
            total_available=total_available,
            raw_total_available=raw_total_available,
            has_more=has_more,
        )
        progressive_refinement = bool(
            any(result.needs_progressive_enrichment for result in results)
            or filters_active
        )
        return ShelfmarkSearchSection(
            enabled=True,
            available=True,
            query=normalized_query,
            page=current_page,
            page_size=requested_page_size,
            selected_sort=selected_sort,
            sort_options=sort_options,
            selected_series_filter=selected_series_filter,
            series_filter_options=series_filter_options,
            selected_triage_filter=selected_triage_filter,
            triage_filter_options=triage_filter_options,
            page_size_options=SHELFMARK_PAGE_SIZE_OPTIONS,
            total_pages=total_pages,
            visible_start=visible_start,
            visible_end=visible_end,
            has_previous=current_page > DEFAULT_SHELFMARK_PAGE,
            previous_page=current_page - 1 if current_page > DEFAULT_SHELFMARK_PAGE else None,
            next_page=current_page + 1 if has_more else None,
            has_more=has_more,
            total_available=summary.total_available,
            raw_total_available=summary.raw_total_available,
            page_result_count=len(results),
            filter_requestable=requestable_only,
            filter_has_cover=has_cover_only,
            filter_high_confidence=high_confidence_only,
            filters_active=filters_active,
            open_search_url=build_shelfmark_search_url(
                config_data.browser_base_url,
                query=normalized_query,
                page=current_page,
                page_size=requested_page_size,
                sort=selected_sort,
            ),
            query_label=query_label,
            context_hint=context_hint,
            pagination_mode="shelfmark",
            progressive_refinement=progressive_refinement,
            progressive_refinement_note=(
                _(
                    "Totals and paging come directly from Shelfmark. Visible rows on this page refine as richer metadata loads, then top up from later Shelfmark pages when needed."
                )
                if progressive_refinement
                else None
            ),
            results=results,
            groups=group_shelfmark_results(results),
            summary=summary,
        )
    except ShelfmarkIntegrationError as exc:
        log.warning("Shelfmark search unavailable for query '%s': %s", normalized_query, exc)
        return ShelfmarkSearchSection(
            enabled=True,
            available=False,
            query=normalized_query,
            query_label=query_label,
            context_hint=context_hint,
            message=str(exc),
            message_level="warning",
        )


def fetch_shelfmark_detail(
    provider: str,
    provider_id: str,
    *,
    detail_url: str | None = None,
    probe_state: ShelfmarkProbeState | None = None,
) -> ShelfmarkResultView:
    config_data = get_shelfmark_client_config()
    if not config_data.enabled:
        raise ShelfmarkIntegrationError(_("Shelfmark integration is not enabled."))

    client = ShelfmarkClient(config_data)
    book = client.fetch_book(provider, provider_id)
    hardcover_id = _extract_hardcover_id(book)
    library_match = None
    if hardcover_id:
        library_match = lookup_visible_library_matches([hardcover_id]).get(hardcover_id)
    result = build_shelfmark_result_view(
        book,
        library_match=library_match,
        detail_url=detail_url,
        shelfmark_browser_base_url=config_data.browser_base_url,
        probe_state=probe_state,
    )
    owned_series = lookup_visible_owned_series([result.series_name] if result.series_name else [])
    series_context = build_shelfmark_series_contexts((result,), owned_series)[0]
    result = replace(result, series_context=series_context)
    result = replace(result, quality_state=build_shelfmark_quality_state(result))
    return replace(
        result,
        triage_state=build_shelfmark_triage_state(
            result,
            quality_state=result.quality_state,
        ),
    )


class ShelfmarkClient:
    def __init__(self, config_data: ShelfmarkClientConfig, session: SafeSession | None = None):
        self.config = config_data
        self.session = session or create_shelfmark_session(config_data)
        self._authenticated = False

    def search_books(
        self,
        query: str,
        *,
        limit: int = DEFAULT_SHELFMARK_LIMIT,
        page: int = DEFAULT_SHELFMARK_PAGE,
        sort: str = DEFAULT_SHELFMARK_SORT,
        provider: str = SHELFMARK_METADATA_PROVIDER,
        content_type: str = SHELFMARK_CONTENT_TYPE,
    ) -> ShelfmarkSearchResponse:
        self._ensure_authenticated()
        normalized_limit = _normalize_page_size(limit)
        current_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(page) or DEFAULT_SHELFMARK_PAGE)
        selected_sort = _normalize_sort(sort)
        response = self._perform_request(
            "get",
            _join_base_url(self.config.base_url, "/api/metadata/search"),
            _("Shelfmark search failed."),
            params={
                "query": query,
                "limit": normalized_limit,
                "sort": selected_sort,
                "page": current_page,
                "provider": provider,
                "content_type": content_type,
            },
        )
        payload = self._parse_json_response(
            response,
            _("Shelfmark search failed."),
            unauthorized_message=self._search_auth_failure_message(),
            forbidden_message=self._search_forbidden_message(),
            invalid_payload_message=_("Shelfmark returned an unexpected metadata search response."),
        )
        books = payload.get("books")
        if not isinstance(books, list):
            raise ShelfmarkIntegrationError(
                _("Shelfmark returned an unexpected metadata search response. Expected a 'books' list.")
            )
        normalized_books = tuple(book for book in books if isinstance(book, dict))
        return ShelfmarkSearchResponse(
            books=normalized_books,
            page=_normalize_int(payload.get("page")) or DEFAULT_SHELFMARK_PAGE,
            total_found=_normalize_int(payload.get("total_found")) or len(normalized_books),
            has_more=bool(payload.get("has_more")),
        )

    def fetch_book(self, provider: str, provider_id: str) -> dict[str, Any]:
        cached_payload = _get_cached_shelfmark_detail_book(
            self.config.base_url,
            provider,
            provider_id,
        )
        if cached_payload is not None:
            return cached_payload

        self._ensure_authenticated()
        response = self._perform_request(
            "get",
            _join_base_url(
                self.config.base_url,
                f"/api/metadata/book/{provider}/{provider_id}",
            ),
            _("Shelfmark book details are unavailable."),
        )
        payload = self._parse_json_response(response, _("Shelfmark book details are unavailable."))
        if not isinstance(payload, dict):
            raise ShelfmarkIntegrationError(_("Shelfmark returned an invalid book detail payload."))
        return _remember_shelfmark_detail_book(
            self.config.base_url,
            provider,
            provider_id,
            payload,
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
            raise ShelfmarkIntegrationError(
                _("Configure both a Shelfmark search username and password before enabling integrated external search.")
            )

        response = self._perform_request(
            "post",
            _join_base_url(self.config.base_url, "/api/auth/login"),
            _("Shelfmark login failed for the configured search account."),
            json={
                "username": username,
                "password": password,
                "remember_me": False,
            },
        )
        payload = self._parse_json_response(response, _("Shelfmark login failed for the configured search account."))
        if not isinstance(payload, dict) or not payload.get("success"):
            raise ShelfmarkIntegrationError(
                _("Shelfmark login failed for the configured search account.")
            )
        self._authenticated = True

    def _perform_request(self, method: str, url: str, default_message: str, **kwargs: Any):
        try:
            return getattr(self.session, method)(
                url,
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
        except UnacceptableAddressException as exc:
            raise ShelfmarkIntegrationError(
                _(
                    "Shelfmark server-side request validation blocked this address. "
                    "Check that Shelfmark Base URL points directly to your Shelfmark instance "
                    "and is not redirecting to a different host or port."
                )
            ) from exc
        except RequestException as exc:
            raise ShelfmarkIntegrationError(default_message) from exc

    def _search_auth_failure_message(self) -> str:
        if not self.config.username and not self.config.password:
            return _(
                "Shelfmark metadata search requires authentication. Configure Shelfmark Search Username and Password in CWA admin. "
                "Your browser's Shelfmark login is only used for browser-side request actions, not for server-side external search."
            )
        return _(
            "Shelfmark rejected the configured search account. Verify Shelfmark Search Username and Password and confirm that account can use metadata search."
        )

    @staticmethod
    def _search_forbidden_message() -> str:
        return _(
            "Shelfmark denied the configured search account access to metadata search. Verify the account and any reverse-proxy or auth restrictions on Shelfmark."
        )

    @staticmethod
    def _parse_json_response(
        response: Any,
        default_message: str,
        *,
        unauthorized_message: str | None = None,
        forbidden_message: str | None = None,
        invalid_payload_message: str | None = None,
    ) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShelfmarkIntegrationError(invalid_payload_message or default_message) from exc

        status_code = getattr(response, "status_code", getattr(response, "status", None))

        if response.ok:
            if isinstance(payload, Mapping):
                return payload
            raise ShelfmarkIntegrationError(invalid_payload_message or default_message)

        if status_code == 401 and unauthorized_message:
            raise ShelfmarkIntegrationError(unauthorized_message)

        if status_code == 403 and forbidden_message:
            raise ShelfmarkIntegrationError(forbidden_message)

        message = default_message
        if isinstance(payload, Mapping):
            raw_error = payload.get("error") or payload.get("message")
            normalized = _normalize_text(raw_error)
            if normalized:
                message = normalized
        raise ShelfmarkIntegrationError(message)


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _normalize_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_authors(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)):
        normalized = _normalize_text(value)
        return [normalized] if normalized else []
    if not isinstance(value, Sequence):
        return []
    authors: list[str] = []
    for author in value:
        normalized = _normalize_text(author)
        if normalized:
            authors.append(normalized)
    return authors


def _iter_mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return tuple()
    return tuple(item for item in value if isinstance(item, Mapping))


def _resolve_shelfmark_title(book: Mapping[str, Any]) -> str | None:
    direct_title = _normalize_text(book.get("title")) or _normalize_text(book.get("search_title"))
    if direct_title:
        return direct_title

    canonical = book.get("canonical")
    if isinstance(canonical, Mapping):
        return _normalize_text(canonical.get("title"))
    return None


def _resolve_shelfmark_authors(book: Mapping[str, Any]) -> list[str]:
    authors = _normalize_authors(book.get("authors"))
    if authors:
        return authors

    for key in ("author", "search_author"):
        authors = _normalize_authors(book.get(key))
        if authors:
            return authors

    return []


def _normalize_cover_candidate(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("url", "href", "src"):
            normalized = _normalize_text(value.get(key))
            if normalized:
                return normalized
        return None
    return _normalize_text(value)


def _normalize_year_from_value(value: Any) -> int | None:
    direct_year = _normalize_int(value)
    if direct_year is not None:
        return direct_year

    normalized = _normalize_text(value)
    if not normalized:
        return None

    match = re.search(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b", normalized)
    if not match:
        return None
    return _normalize_int(match.group(1))


def _normalize_tag_category(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    normalized = normalized.casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", normalized).strip() or None


def _tag_category_matches(category: Any, allowed_labels: Sequence[str]) -> bool:
    normalized_category = _normalize_tag_category(category)
    if not normalized_category:
        return False
    allowed = {_normalize_tag_category(label) for label in allowed_labels}
    return normalized_category in allowed


def _extract_schema_tag_label(tagging: Mapping[str, Any]) -> str | None:
    tag = tagging.get("tag")
    if isinstance(tag, Mapping):
        return (
            _normalize_text(tag.get("tag"))
            or _normalize_text(tag.get("name"))
            or _normalize_text(tag.get("title"))
            or _normalize_text(tag.get("label"))
        )
    return None


def _resolve_schema_tag_values(
    book: Mapping[str, Any],
    *,
    categories: Sequence[str],
    limit: int,
    prefer_non_spoilers: bool = False,
) -> tuple[str, ...]:
    matches: list[tuple[int, int, str]] = []
    seen: set[str] = set()

    for index, tagging in enumerate(_iter_mapping_items(book.get("taggings"))):
        tag = tagging.get("tag")
        if not isinstance(tag, Mapping):
            continue

        tag_category = tag.get("tag_category")
        category_value = None
        if isinstance(tag_category, Mapping):
            category_value = tag_category.get("category") or tag_category.get("slug")
        if not _tag_category_matches(category_value, categories):
            continue

        label = _extract_schema_tag_label(tagging)
        if not label:
            continue

        label_key = label.casefold()
        if label_key in seen:
            continue
        seen.add(label_key)

        spoiler_rank = 1 if bool(tagging.get("spoiler")) else 0
        if not prefer_non_spoilers:
            spoiler_rank = 0
        matches.append((spoiler_rank, index, label))

    if prefer_non_spoilers:
        matches.sort(key=lambda item: (item[0], item[1]))

    return tuple(label for _, _, label in matches[:limit])


def _resolve_hardcover_slug(book: Mapping[str, Any]) -> str | None:
    slug = _normalize_text(book.get("slug"))
    if slug:
        return slug

    canonical = book.get("canonical")
    if isinstance(canonical, Mapping):
        return _normalize_text(canonical.get("slug"))
    return None


def _resolve_source_url(book: Mapping[str, Any]) -> str | None:
    explicit_source_url = _normalize_text(book.get("source_url"))
    if explicit_source_url:
        return explicit_source_url

    if (_normalize_text(book.get("provider")) or SHELFMARK_METADATA_PROVIDER) != SHELFMARK_METADATA_PROVIDER:
        return None

    slug = _resolve_hardcover_slug(book)
    if not slug:
        return None
    return f"https://hardcover.app/books/{slug}"


def _edition_identity(edition: Mapping[str, Any]) -> tuple[str | None, ...]:
    return (
        _normalize_text(edition.get("id")),
        _normalize_text(edition.get("title")),
        _normalize_text(edition.get("isbn_13")),
        _normalize_text(edition.get("isbn_10")),
    )


def _iter_schema_editions(book: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    editions: list[Mapping[str, Any]] = []
    seen: set[tuple[str | None, ...]] = set()

    def add_candidate(candidate: Any) -> None:
        if not isinstance(candidate, Mapping):
            return
        edition_key = _edition_identity(candidate)
        if edition_key in seen:
            return
        seen.add(edition_key)
        editions.append(candidate)

    for key in (
        "default_ebook_edition",
        "edition",
        "default_physical_edition",
        "default_audio_edition",
        "default_cover_edition",
    ):
        add_candidate(book.get(key))

    for candidate in _iter_mapping_items(book.get("editions")):
        add_candidate(candidate)

    return tuple(editions)


def _iter_media_signals(record: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in (
        "content_type",
        "format",
        "edition_format",
        "media_type",
        "physical_format",
        "object_type",
    ):
        normalized = _normalize_text(record.get(key))
        if normalized:
            values.append(normalized.casefold())

    reading_format = record.get("reading_format")
    if isinstance(reading_format, Mapping):
        normalized = _normalize_text(reading_format.get("format"))
        if normalized:
            values.append(normalized.casefold())

    return tuple(values)


def _classify_schema_content_type(record: Mapping[str, Any]) -> str | None:
    media_signals = _iter_media_signals(record)
    if not media_signals:
        return None

    has_ebook_signal = any(
        any(hint in signal for hint in SHELFMARK_EBOOK_HINTS)
        for signal in media_signals
    )
    has_physical_signal = any(
        any(hint in signal for hint in SHELFMARK_PHYSICAL_HINTS)
        for signal in media_signals
    )
    has_audio_signal = any(
        signal == "audiobook"
        or any(hint in signal for hint in SHELFMARK_AUDIOBOOK_HINTS)
        for signal in media_signals
    )

    if has_ebook_signal:
        return "ebook"
    if has_physical_signal:
        return "physical"
    if has_audio_signal:
        return "audio"
    return None


def _select_edition_by_kind(book: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    default_key_by_kind = {
        "ebook": "default_ebook_edition",
        "physical": "default_physical_edition",
        "audio": "default_audio_edition",
    }
    default_candidate = book.get(default_key_by_kind[kind])
    if isinstance(default_candidate, Mapping):
        return default_candidate

    inline_edition = book.get("edition")
    if isinstance(inline_edition, Mapping):
        inline_kind = _classify_schema_content_type(inline_edition)
        if inline_kind == kind or (kind == "ebook" and inline_kind is None):
            return inline_edition

    for candidate in _iter_mapping_items(book.get("editions")):
        if _classify_schema_content_type(candidate) == kind:
            return candidate

    return None


def _resolve_display_edition(book: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for kind in ("ebook", "physical", "audio"):
        candidate = _select_edition_by_kind(book, kind)
        if candidate is not None:
            return candidate

    default_cover_edition = book.get("default_cover_edition")
    if isinstance(default_cover_edition, Mapping):
        return default_cover_edition

    all_editions = _iter_schema_editions(book)
    return all_editions[0] if all_editions else None


def _resolve_primary_content_type(book: Mapping[str, Any]) -> str | None:
    explicit_type = _classify_schema_content_type(book)
    if _select_edition_by_kind(book, "ebook") is not None:
        return "ebook"
    if explicit_type == "ebook":
        return "ebook"

    if _select_edition_by_kind(book, "physical") is not None:
        return "physical"
    if explicit_type == "physical":
        return "physical"

    if _select_edition_by_kind(book, "audio") is not None:
        return "audio"
    if explicit_type == "audio":
        return "audio"

    return None


def _resolve_featured_series_row(book: Mapping[str, Any]) -> Mapping[str, Any] | None:
    featured = book.get("featured_book_series")
    if isinstance(featured, Mapping):
        return featured

    for row in _iter_mapping_items(book.get("book_series")):
        if bool(row.get("featured")) and isinstance(row.get("series"), Mapping):
            return row

    for row in _iter_mapping_items(book.get("book_series")):
        if isinstance(row.get("series"), Mapping):
            return row

    return None


def _resolve_featured_series(book: Mapping[str, Any]) -> Mapping[str, Any] | None:
    row = _resolve_featured_series_row(book)
    if not row:
        return None
    series = row.get("series")
    return series if isinstance(series, Mapping) else None


def _resolve_shelfmark_cover_value(book: Mapping[str, Any]) -> Any:
    for key in ("cover_url", "preview", "cached_image", "image"):
        value = _normalize_cover_candidate(book.get(key))
        if value:
            return value

    default_cover_edition = book.get("default_cover_edition")
    if isinstance(default_cover_edition, Mapping):
        for key in ("cached_image", "image"):
            value = _normalize_cover_candidate(default_cover_edition.get(key))
            if value:
                return value

    display_edition = _resolve_display_edition(book)
    if isinstance(display_edition, Mapping):
        for key in ("cached_image", "image"):
            value = _normalize_cover_candidate(display_edition.get(key))
            if value:
                return value
    return None


def _sanitize_description_html(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    cleaned = clean_string(normalized)
    cleaned = _normalize_text(cleaned)
    return cleaned


def _plain_text_from_html(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    plain = _normalize_text(Markup(normalized).striptags())
    return plain


def _normalize_series_position(value: Any) -> float | None:
    return _normalize_float(value)


def _format_series_position(value: float | None) -> str | None:
    if value is None:
        return None
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _resolve_series_name(book: Mapping[str, Any]) -> str | None:
    featured_series = _resolve_featured_series(book)
    if isinstance(featured_series, Mapping):
        name = _normalize_text(featured_series.get("name"))
        if name:
            return name
    return _normalize_text(book.get("series_name"))


def _resolve_series_position(book: Mapping[str, Any]) -> float | None:
    featured_series_row = _resolve_featured_series_row(book)
    if isinstance(featured_series_row, Mapping):
        position = _normalize_series_position(featured_series_row.get("position"))
        if position is not None:
            return position
    return _normalize_series_position(book.get("series_position"))


def _resolve_series_count(book: Mapping[str, Any]) -> int | None:
    featured_series = _resolve_featured_series(book)
    if isinstance(featured_series, Mapping):
        for key in ("primary_books_count", "books_count"):
            count = _normalize_int(featured_series.get(key))
            if count is not None:
                return count
    return _normalize_int(book.get("series_count"))


def _resolve_publish_year(book: Mapping[str, Any]) -> int | None:
    for candidate in (
        book.get("publish_year"),
        book.get("release_year"),
        book.get("release_date"),
    ):
        resolved_year = _normalize_year_from_value(candidate)
        if resolved_year is not None:
            return resolved_year

    display_edition = _resolve_display_edition(book)
    if isinstance(display_edition, Mapping):
        for candidate in (
            display_edition.get("release_year"),
            display_edition.get("release_date"),
        ):
            resolved_year = _normalize_year_from_value(candidate)
            if resolved_year is not None:
                return resolved_year

    return None


def _lookup_display_field_value(book: Mapping[str, Any], *labels: str) -> str | None:
    target_labels = {label.casefold() for label in labels if label}
    if not target_labels:
        return None

    for field in _normalize_display_fields(book.get("display_fields")):
        label = _normalize_text(field.get("label"))
        if label and label.casefold() in target_labels:
            return _normalize_text(field.get("value"))
    return None


def _resolve_pages(book: Mapping[str, Any]) -> int | None:
    display_edition = _resolve_display_edition(book)
    if isinstance(display_edition, Mapping):
        edition_pages = _normalize_int(display_edition.get("pages"))
        if edition_pages is not None:
            return edition_pages

    pages = _normalize_int(book.get("pages"))
    if pages is not None:
        return pages

    display_value = _lookup_display_field_value(book, "Pages")
    if not display_value:
        return None
    return _normalize_int(re.sub(r"[^\d]", "", display_value))


def _resolve_editions_count(book: Mapping[str, Any]) -> int | None:
    editions_count = _normalize_int(book.get("editions_count"))
    if editions_count is not None:
        return editions_count

    editions_aggregate = book.get("editions_aggregate")
    if isinstance(editions_aggregate, Mapping):
        aggregate = editions_aggregate.get("aggregate")
        if isinstance(aggregate, Mapping):
            editions_count = _normalize_int(aggregate.get("count"))
            if editions_count is not None:
                return editions_count

    display_value = _lookup_display_field_value(book, "Editions")
    if not display_value:
        return None
    return _normalize_int(re.sub(r"[^\d]", "", display_value))


def _resolve_lists_count(book: Mapping[str, Any]) -> int | None:
    lists_count = _normalize_int(book.get("lists_count"))
    if lists_count is not None:
        return lists_count

    list_count = _normalize_int(book.get("list_count"))
    if list_count is not None:
        return list_count

    display_value = _lookup_display_field_value(book, "Lists", "List count", "Lists count")
    if not display_value:
        return None
    return _normalize_int(re.sub(r"[^\d]", "", display_value))


def _resolve_reviews_count(book: Mapping[str, Any]) -> int | None:
    reviews_count = _normalize_int(book.get("reviews_count"))
    if reviews_count is not None:
        return reviews_count

    review_count = _normalize_int(book.get("review_count"))
    if review_count is not None:
        return review_count

    display_value = _lookup_display_field_value(book, "Reviews", "Review count", "Reviews count")
    if not display_value:
        return None
    return _normalize_int(re.sub(r"[^\d]", "", display_value))


def _resolve_rating_value(book: Mapping[str, Any]) -> float | None:
    rating_value = _normalize_float(book.get("rating"))
    if rating_value is not None:
        return rating_value

    display_value = _lookup_display_field_value(book, "Rating")
    if not display_value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", display_value)
    if not match:
        return None
    return _normalize_float(match.group(0))


def _resolve_ratings_count(book: Mapping[str, Any]) -> int | None:
    ratings_count = _normalize_int(book.get("ratings_count"))
    if ratings_count is not None:
        return ratings_count

    display_value = _lookup_display_field_value(book, "Ratings")
    if display_value:
        return _normalize_int(re.sub(r"[^\d]", "", display_value))

    rating_display = _lookup_display_field_value(book, "Rating")
    if not rating_display:
        return None
    match = re.search(r"\(([\d,]+)\)", rating_display)
    if not match:
        return None
    return _normalize_int(match.group(1).replace(",", ""))


def _resolve_readers_count(book: Mapping[str, Any]) -> int | None:
    readers_count = _normalize_int(book.get("users_count"))
    if readers_count is not None:
        return readers_count

    readers_count = _normalize_int(book.get("users_read_count"))
    if readers_count is not None:
        return readers_count

    display_value = _lookup_display_field_value(book, "Readers", "Reader count")
    if not display_value:
        return None
    return _normalize_int(re.sub(r"[^\d]", "", display_value))


def _resolve_shelfmark_subtitle(book: Mapping[str, Any]) -> str | None:
    subtitle = _normalize_text(book.get("subtitle"))

    if (_normalize_text(book.get("provider")) or SHELFMARK_METADATA_PROVIDER) != SHELFMARK_METADATA_PROVIDER:
        return subtitle

    display_edition = _resolve_display_edition(book)
    edition_subtitle = None
    if isinstance(display_edition, Mapping):
        edition_subtitle = _normalize_text(display_edition.get("subtitle"))

    if subtitle and edition_subtitle:
        return subtitle if subtitle.casefold() == edition_subtitle.casefold() else None
    if edition_subtitle and not subtitle:
        return edition_subtitle

    # Hardcover subtitles are often noisy unless we can confirm them against a
    # schema-backed edition relationship.
    return None


def _format_series_display(series_name: str | None, series_position: float | None) -> str | None:
    if not series_name:
        return None
    position = _format_series_position(series_position)
    if position:
        return f"{series_name} ({position})"
    return series_name


def _slugify_hardcover_path_segment(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    normalized = (
        unicodedata.normalize("NFKD", normalized)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or None


def _resolve_series_url(book: Mapping[str, Any]) -> str | None:
    explicit_url = _normalize_text(book.get("series_url"))
    if explicit_url:
        return explicit_url

    if (_normalize_text(book.get("provider")) or SHELFMARK_METADATA_PROVIDER) != SHELFMARK_METADATA_PROVIDER:
        return None

    series_slug = _normalize_text(book.get("series_slug"))
    if not series_slug:
        featured_series = _resolve_featured_series(book)
        if isinstance(featured_series, Mapping):
            series_slug = _normalize_text(featured_series.get("slug"))
    if not series_slug:
        featured_series = book.get("featured_book_series")
        if isinstance(featured_series, Mapping):
            series_data = featured_series.get("series")
            if isinstance(series_data, Mapping):
                series_slug = _normalize_text(series_data.get("slug"))
    if not series_slug:
        series_slug = _slugify_hardcover_path_segment(_resolve_series_name(book))
    if not series_slug:
        return None
    return f"https://hardcover.app/series/{series_slug}"


def _normalize_tag_list(value: Any, *, limit: int | None = None) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        normalized = _normalize_text(value)
        return (normalized,) if normalized else tuple()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return tuple()

    tags: list[str] = []
    seen: set[str] = set()
    generic_labels = {
        "genre",
        "mood",
        "tag",
        "content warning",
        "content warnings",
        "warning",
        "warnings",
    }
    for item in value:
        if isinstance(item, Mapping):
            normalized = (
                _normalize_text(item.get("value"))
                or _normalize_text(item.get("tag"))
                or _normalize_text(item.get("name"))
                or _normalize_text(item.get("title"))
                or _normalize_text(item.get("label"))
            )
        else:
            normalized = _normalize_text(item)
        if not normalized:
            continue
        if normalized.casefold() in generic_labels:
            continue
        tag_key = normalized.casefold()
        if tag_key in seen:
            continue
        seen.add(tag_key)
        tags.append(normalized)
        if limit and len(tags) >= limit:
            break
    return tuple(tags)


def _resolve_genres(book: Mapping[str, Any]) -> tuple[str, ...]:
    schema_values = _resolve_schema_tag_values(
        book,
        categories=SHELFMARK_GENRE_CATEGORY_HINTS,
        limit=5,
    )
    if schema_values:
        return schema_values

    direct = _normalize_tag_list(book.get("genres"), limit=5)
    if direct:
        return direct

    cached_tags = _normalize_tag_list(book.get("cached_tags"), limit=5)
    if cached_tags:
        return cached_tags

    tag_fallback = _normalize_tag_list(book.get("tags"), limit=5)
    if tag_fallback:
        return tag_fallback

    return _normalize_compact_values(
        _lookup_display_field_value(book, "Genres", "Genre", "Tags", "Tag"),
        limit=5,
    )


def _normalize_compact_values(value: Any, *, limit: int | None = None) -> tuple[str, ...]:
    generic_labels = {
        "genre",
        "mood",
        "tag",
        "content warning",
        "content warnings",
        "warning",
        "warnings",
    }
    if isinstance(value, Mapping):
        normalized = (
            _normalize_text(value.get("value"))
            or _normalize_text(value.get("tag"))
            or _normalize_text(value.get("label"))
            or _normalize_text(value.get("name"))
        )
        if not normalized or normalized.casefold() in generic_labels:
            return tuple()
        return (normalized,) 

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return _normalize_tag_list(value, limit=limit)

    normalized = _normalize_text(value)
    if not normalized:
        return tuple()

    parts = re.split(r"\s*(?:,|;|\n|\u2022|\u00b7|\|)\s*", normalized)
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = _normalize_text(part)
        if not item:
            continue
        if item.casefold() in generic_labels:
            continue
        item_key = item.casefold()
        if item_key in seen:
            continue
        seen.add(item_key)
        values.append(item)
        if limit and len(values) >= limit:
            break
    return tuple(values)


def _resolve_moods(book: Mapping[str, Any]) -> tuple[str, ...]:
    schema_values = _resolve_schema_tag_values(
        book,
        categories=SHELFMARK_MOOD_CATEGORY_HINTS,
        limit=5,
    )
    if schema_values:
        return schema_values

    direct = _normalize_compact_values(book.get("moods"), limit=5)
    if direct:
        return direct
    return _normalize_compact_values(
        _lookup_display_field_value(book, "Moods", "Mood"),
        limit=5,
    )


def _resolve_content_warnings(book: Mapping[str, Any]) -> tuple[str, ...]:
    schema_values = _resolve_schema_tag_values(
        book,
        categories=SHELFMARK_CONTENT_WARNING_CATEGORY_HINTS,
        limit=6,
        prefer_non_spoilers=True,
    )
    if schema_values:
        return schema_values

    direct = _normalize_compact_values(book.get("content_warnings"), limit=6)
    if direct:
        return direct

    fallback = _normalize_compact_values(book.get("warnings"), limit=6)
    if fallback:
        return fallback

    return _normalize_compact_values(
        _lookup_display_field_value(book, "Content warnings", "Content warning", "Warnings"),
        limit=6,
    )


def build_shelfmark_quality_state(result: ShelfmarkResultView) -> ShelfmarkQualityState | None:
    requestable_now = bool(
        not result.already_in_library
        and result.hardcover_id
        and result.request_payload
    )
    if not requestable_now:
        return None

    has_cover = bool(result.cover_url)
    has_description = bool(result.description)
    has_authors = bool(result.authors)
    bibliographic_signal = bool(
        _normalize_text(result.title)
        and has_authors
        and (not result.series_name or result.series_display)
    )
    series_signal = bool(
        result.series_context
        and (result.series_context.is_next_missing or result.series_context.is_continuation)
    )
    metadata_signal_count = sum(
        1
        for value in (
            result.cover_url,
            result.description,
            result.publish_year,
            result.pages,
            result.rating,
            result.ratings_count,
            result.readers_count,
            result.series_display,
        )
        if value not in (None, "")
    )
    metadata_complete = bool(
        has_cover
        and has_description
        and bibliographic_signal
        and metadata_signal_count >= SHELFMARK_QUALITY_MIN_METADATA_SIGNALS
    )
    popularity_signal = bool(
        (result.readers_count or 0) >= SHELFMARK_TRIAGE_MIN_READERS
        or (result.ratings_count or 0) >= SHELFMARK_TRIAGE_MIN_RATINGS
    )
    rating_signal = bool(
        result.rating is not None
        and result.rating >= SHELFMARK_TRIAGE_MIN_RATING
        and (result.ratings_count or 0) >= SHELFMARK_TRIAGE_MIN_RATING_COUNT
    )
    high_confidence = bool(
        requestable_now
        and has_cover
        and has_description
        and bibliographic_signal
        and (series_signal or rating_signal or (metadata_complete and popularity_signal))
    )

    facts: list[str] = []
    if rating_signal:
        facts.append(_("Well rated"))
    if popularity_signal:
        facts.append(_("Popular"))
    if metadata_complete:
        facts.append(_("Complete metadata"))

    detail_parts: list[str] = []
    if high_confidence:
        detail_parts.append(_("High confidence"))
    detail_parts.extend(facts)

    return ShelfmarkQualityState(
        high_confidence=high_confidence,
        metadata_complete=metadata_complete,
        popularity_signal=popularity_signal,
        rating_signal=rating_signal,
        bibliographic_signal=bibliographic_signal,
        facts=tuple(facts),
        detail_value=" \u00b7 ".join(detail_parts) if detail_parts else None,
    )


def build_shelfmark_triage_state(
    result: ShelfmarkResultView,
    *,
    quality_state: ShelfmarkQualityState | None = None,
) -> ShelfmarkTriageState | None:
    requestable_now = bool(
        not result.already_in_library
        and result.hardcover_id
        and result.request_payload
    )
    if not requestable_now:
        return None

    quality = quality_state or build_shelfmark_quality_state(result)
    has_cover = bool(result.cover_url)
    series_signal = bool(
        result.series_context
        and (result.series_context.is_next_missing or result.series_context.is_continuation)
    )
    metadata_rich = bool(quality and quality.metadata_complete)
    popularity_signal = bool(quality and (quality.popularity_signal or quality.rating_signal))
    strong_candidate = bool(
        requestable_now
        and has_cover
        and (
            series_signal
            or (quality and quality.high_confidence)
        )
    )

    facts: list[str] = []
    if popularity_signal:
        facts.append(_("Popular"))
    if metadata_rich:
        facts.append(_("Rich metadata"))

    detail_parts: list[str] = []
    if strong_candidate:
        detail_parts.append(_("Strong candidate"))
    detail_parts.extend(facts)

    return ShelfmarkTriageState(
        strong_candidate=strong_candidate,
        metadata_rich=metadata_rich,
        popularity_signal=popularity_signal,
        facts=tuple(facts),
        detail_value=" \u00b7 ".join(detail_parts) if detail_parts else None,
    )


def _build_result_facts(book: Mapping[str, Any], *, publish_year: int | None) -> tuple[str, ...]:
    facts: list[str] = []

    rating_value = _resolve_rating_value(book)
    ratings_count = _resolve_ratings_count(book)
    readers_count = _resolve_readers_count(book)
    pages = _resolve_pages(book)
    series_display = _format_series_display(
        _resolve_series_name(book),
        _resolve_series_position(book),
    )

    if rating_value is not None:
        facts.append(f"{rating_value:.1f} \u2605")
    if ratings_count:
        label = _("rating") if ratings_count == 1 else _("ratings")
        facts.append(f"{ratings_count:,} {label}")
    if readers_count:
        label = _("reader") if readers_count == 1 else _("readers")
        facts.append(f"{readers_count:,} {label}")
    if publish_year:
        facts.append(str(publish_year))
    if pages:
        label = _("page") if pages == 1 else _("pages")
        facts.append(f"{pages:,} {label}")
    if series_display:
        facts.append(series_display)

    return tuple(facts)


def _build_detail_stats(book: Mapping[str, Any], *, publish_year: int | None) -> tuple[dict[str, str], ...]:
    stats: list[dict[str, str]] = []
    reviews_count = _resolve_reviews_count(book)
    editions_count = _resolve_editions_count(book)
    lists_count = _resolve_lists_count(book)

    if reviews_count:
        stats.append({"label": _("Reviews"), "value": f"{reviews_count:,}"})
    if editions_count:
        stats.append({"label": _("Editions"), "value": f"{editions_count:,}"})
    if lists_count:
        stats.append({"label": _("Lists"), "value": f"{lists_count:,}"})

    return tuple(stats)


def _normalize_shelfmark_cover_url(base_url: str, value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    normalized_base_url = _normalize_text(base_url) or ""
    cached_value = _get_cached_shelfmark_cover_url(normalized_base_url, normalized)
    if cached_value is not None:
        return cached_value

    parsed = urlsplit(normalized)
    if parsed.scheme or parsed.netloc:
        return _remember_shelfmark_cover_url(normalized_base_url, normalized, normalized)

    if normalized.startswith("/"):
        base_parts = urlsplit(normalized_base_url)
        if not base_parts.scheme or not base_parts.netloc:
            return _remember_shelfmark_cover_url(normalized_base_url, normalized, normalized)
        normalized_path = parsed.path
        base_prefix = (base_parts.path or "").rstrip("/")
        if base_prefix and normalized_path.startswith("/api/covers/"):
            normalized_path = f"{base_prefix}{normalized_path}"
        return _remember_shelfmark_cover_url(
            normalized_base_url,
            normalized,
            urlunsplit(
                (
                    base_parts.scheme,
                    base_parts.netloc,
                    normalized_path,
                    parsed.query,
                    parsed.fragment,
                )
            ),
        )

    return _remember_shelfmark_cover_url(
        normalized_base_url,
        normalized,
        _join_base_url(normalized_base_url, normalized),
    )


def _normalize_display_fields(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return tuple()
    normalized_fields: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = _normalize_text(item.get("label"))
        field_value = _normalize_text(item.get("value"))
        if not label or not field_value:
            continue
        normalized_fields.append(
            {
                "label": label,
                "value": field_value,
                "icon": _normalize_text(item.get("icon")),
            }
        )
    return tuple(normalized_fields)


def _extract_hardcover_id(book: Mapping[str, Any]) -> str | None:
    identifiers = book.get("identifiers")
    if isinstance(identifiers, Mapping):
        for key in ("hardcover-id", "hardcover_id"):
            normalized_identifier = _normalize_text(identifiers.get(key))
            if normalized_identifier:
                return normalized_identifier

    provider = _normalize_text(book.get("provider"))
    if provider != SHELFMARK_METADATA_PROVIDER:
        return None
    return _normalize_text(book.get("provider_id"))


def _missing_request_requirements(book: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    if not _extract_hardcover_id(book):
        missing.append("hardcover_id")
    if not _resolve_shelfmark_title(book):
        missing.append("title")
    if not _resolve_shelfmark_authors(book):
        missing.append("author")
    return tuple(missing)


def _describe_missing_request_requirements(requirements: Sequence[str]) -> str | None:
    labels = {
        "hardcover_id": _("exact Hardcover ID"),
        "title": _("book title"),
        "author": _("at least one author"),
    }
    normalized = [labels[item] for item in requirements if item in labels]
    if not normalized:
        return None
    if len(normalized) == 1:
        requirements_text = normalized[0]
    elif len(normalized) == 2:
        requirements_text = _("%(first)s and %(second)s", first=normalized[0], second=normalized[1])
    else:
        requirements_text = _(
            "%(first)s, %(second)s, and %(third)s",
            first=normalized[0],
            second=normalized[1],
            third=normalized[2],
        )
    return _(
        "CWA needs the %(requirements)s from Shelfmark before it can prepare a direct request here.",
        requirements=requirements_text,
    )


def _join_base_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    return urljoin(f"{normalized_base}/", path.lstrip("/"))


def _with_query(base_url: str, params: Mapping[str, str]) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(params, doseq=True),
            "",
        )
    )
