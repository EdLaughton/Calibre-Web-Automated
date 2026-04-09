from __future__ import annotations
from dataclasses import asdict, dataclass, field
import ipaddress
import math
import socket
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from requests import RequestException
from flask import url_for
from flask_babel import gettext as _
from sqlalchemy.sql.expression import func

from cps import calibre_db, config, db, logger
from cps.cw_advocate import AddrValidator
from cps.cw_advocate import Session as SafeSession
from cps.cw_advocate.exceptions import UnacceptableAddressException

log = logger.create()

DEFAULT_SHELFMARK_TIMEOUT_SECONDS = 15
DEFAULT_SHELFMARK_LIMIT = 12
DEFAULT_SHELFMARK_SORT = "relevance"
DEFAULT_SHELFMARK_PAGE = 1
SHELFMARK_METADATA_PROVIDER = "hardcover"
SHELFMARK_CONTENT_TYPE = "ebook"
SHELFMARK_REQUEST_MODE = "request_book"
SHELFMARK_REQUEST_KIND = "book"


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

    def to_template_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authors"] = list(self.authors)
        payload["display_fields"] = list(self.display_fields)
        payload["library_state"] = asdict(self.library_state)
        payload["action"] = asdict(self.action)
        return payload


@dataclass(frozen=True)
class ShelfmarkResultSummary:
    total_results: int = 0
    total_available: int = 0
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
    total_pages: int = 0
    visible_start: int = 0
    visible_end: int = 0
    has_previous: bool = False
    previous_page: int | None = None
    next_page: int | None = None
    has_more: bool = False
    total_available: int = 0
    open_search_url: str | None = None
    query_label: str | None = None
    context_hint: str | None = None
    message: str | None = None
    message_level: str = "info"
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
            "total_pages": self.total_pages,
            "visible_start": self.visible_start,
            "visible_end": self.visible_end,
            "has_previous": self.has_previous,
            "previous_page": self.previous_page,
            "next_page": self.next_page,
            "has_more": self.has_more,
            "total_available": self.total_available,
            "open_search_url": self.open_search_url,
            "query_label": self.query_label,
            "context_hint": self.context_hint,
            "message": self.message,
            "message_level": self.message_level,
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
) -> str:
    params = {
        "content_type": content_type,
        "sort": DEFAULT_SHELFMARK_SORT,
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
            hint=_("Exact Hardcover ID already exists in your library."),
            button_class="btn-success",
            icon_class="glyphicon glyphicon-book",
        )

    if not hardcover_id:
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=_("This result has no exact Hardcover ID, so CWA cannot prepare a direct Shelfmark request."),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if request_payload is None:
        requirement_hint = _describe_missing_request_requirements(missing_request_requirements)
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=requirement_hint
            or _("Shelfmark did not return enough exact metadata to prepare a direct request."),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if probe_state is None or not probe_state.probe_available:
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=_("Request availability is checked in your browser. Until Shelfmark confirms a live session and compatible policy, opening Shelfmark remains the safe fallback."),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if not probe_state.authenticated:
        suffix = _("Login required") if probe_state.auth_required else _("Open in Shelfmark")
        return ShelfmarkActionState(
            mode="open",
            label=_("Open in Shelfmark"),
            hint=_("Shelfmark session was not found for this browser. %(suffix)s.", suffix=suffix),
            button_class="btn-default",
            icon_class="glyphicon glyphicon-new-window",
        )

    if probe_state.requests_enabled and probe_state.ebook_mode == SHELFMARK_REQUEST_MODE:
        return ShelfmarkActionState(
            mode="request",
            label=_("Request in Shelfmark"),
            hint=_("This browser already has a Shelfmark session and the current policy allows book-level requests."),
            button_class="btn-primary",
            icon_class="glyphicon glyphicon-send",
        )

    return ShelfmarkActionState(
        mode="open",
        label=_("Open in Shelfmark"),
        hint=_("Shelfmark is signed in, but the current Shelfmark policy does not allow direct book-level requests for this result."),
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


def build_shelfmark_result_view(
    book: Mapping[str, Any],
    *,
    library_match: ShelfmarkLibraryMatch | None,
    detail_url: str | None,
    shelfmark_browser_base_url: str,
    probe_state: ShelfmarkProbeState | None = None,
) -> ShelfmarkResultView:
    title = _resolve_shelfmark_title(book) or _("Unknown title")
    authors = tuple(_resolve_shelfmark_authors(book))
    hardcover_id = _extract_hardcover_id(book)
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
        subtitle=_normalize_text(book.get("subtitle")),
        authors=authors,
        cover_url=_normalize_shelfmark_cover_url(shelfmark_browser_base_url, book.get("cover_url")),
        description=_normalize_text(book.get("description")),
        publish_year=_normalize_int(book.get("publish_year")),
        source_url=_normalize_text(book.get("source_url")),
        display_fields=_normalize_display_fields(book.get("display_fields")),
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
    )


def summarize_shelfmark_results(
    results: Sequence[ShelfmarkResultView],
    *,
    total_available: int | None = None,
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


def search_shelfmark_results(
    query: str | None,
    *,
    detail_url_builder: Callable[[Mapping[str, Any]], str | None],
    page: int = DEFAULT_SHELFMARK_PAGE,
    query_label: str | None = None,
    context_hint: str | None = None,
    empty_message: str | None = None,
) -> ShelfmarkSearchSection:
    normalized_query = _normalize_text(query)
    requested_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(page) or DEFAULT_SHELFMARK_PAGE)
    config_data = get_shelfmark_client_config()
    if not config_data.enabled:
        return ShelfmarkSearchSection(enabled=False, available=False, query=normalized_query or "")

    if not normalized_query:
        return ShelfmarkSearchSection(
            enabled=True,
            available=True,
            query="",
            page=requested_page,
            page_size=DEFAULT_SHELFMARK_LIMIT,
            total_pages=0,
            visible_start=0,
            visible_end=0,
            has_previous=False,
            previous_page=None,
            next_page=None,
            has_more=False,
            total_available=0,
            open_search_url=(
                build_shelfmark_search_url(
                    config_data.browser_base_url,
                    query="",
                    page=requested_page,
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
        search_response = client.search_books(normalized_query, page=requested_page)
        books = search_response.books
        hardcover_ids = [value for value in (_extract_hardcover_id(book) for book in books) if value]
        library_matches = lookup_visible_library_matches(hardcover_ids)
        results = tuple(
            build_shelfmark_result_view(
                book,
                library_match=library_matches.get(_extract_hardcover_id(book) or ""),
                detail_url=detail_url_builder(book),
                shelfmark_browser_base_url=config_data.browser_base_url,
            )
            for book in books
        )
        summary = summarize_shelfmark_results(
            results,
            total_available=search_response.total_found,
            has_more=search_response.has_more,
        )
        current_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(search_response.page) or requested_page)
        total_pages = (
            max(1, math.ceil(summary.total_available / DEFAULT_SHELFMARK_LIMIT))
            if summary.total_available
            else 0
        )
        visible_start = ((current_page - 1) * DEFAULT_SHELFMARK_LIMIT) + 1 if results else 0
        visible_end = visible_start + len(results) - 1 if results else 0
        return ShelfmarkSearchSection(
            enabled=True,
            available=True,
            query=normalized_query,
            page=current_page,
            page_size=DEFAULT_SHELFMARK_LIMIT,
            total_pages=total_pages,
            visible_start=visible_start,
            visible_end=visible_end,
            has_previous=current_page > DEFAULT_SHELFMARK_PAGE,
            previous_page=current_page - 1 if current_page > DEFAULT_SHELFMARK_PAGE else None,
            next_page=current_page + 1 if search_response.has_more else None,
            has_more=search_response.has_more,
            total_available=summary.total_available,
            open_search_url=build_shelfmark_search_url(
                config_data.browser_base_url,
                query=normalized_query,
                page=current_page,
            ),
            query_label=query_label,
            context_hint=context_hint,
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
    return build_shelfmark_result_view(
        book,
        library_match=library_match,
        detail_url=detail_url,
        shelfmark_browser_base_url=config_data.browser_base_url,
        probe_state=probe_state,
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
        provider: str = SHELFMARK_METADATA_PROVIDER,
        content_type: str = SHELFMARK_CONTENT_TYPE,
    ) -> ShelfmarkSearchResponse:
        self._ensure_authenticated()
        current_page = max(DEFAULT_SHELFMARK_PAGE, _normalize_int(page) or DEFAULT_SHELFMARK_PAGE)
        response = self._perform_request(
            "get",
            _join_base_url(self.config.base_url, "/api/metadata/search"),
            _("Shelfmark search failed."),
            params={
                "query": query,
                "limit": limit,
                "sort": DEFAULT_SHELFMARK_SORT,
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
        return payload

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


def _resolve_shelfmark_title(book: Mapping[str, Any]) -> str | None:
    return _normalize_text(book.get("title")) or _normalize_text(book.get("search_title"))


def _resolve_shelfmark_authors(book: Mapping[str, Any]) -> list[str]:
    authors = _normalize_authors(book.get("authors"))
    if authors:
        return authors

    for key in ("author", "search_author"):
        authors = _normalize_authors(book.get(key))
        if authors:
            return authors

    return []


def _normalize_shelfmark_cover_url(base_url: str, value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None

    parsed = urlsplit(normalized)
    if parsed.scheme or parsed.netloc:
        return normalized

    if normalized.startswith("/"):
        base_parts = urlsplit(base_url)
        if not base_parts.scheme or not base_parts.netloc:
            return normalized
        return urlunsplit((base_parts.scheme, base_parts.netloc, normalized, "", ""))

    return _join_base_url(base_url, normalized)


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
