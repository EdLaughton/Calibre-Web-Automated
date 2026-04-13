# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json

from cps import logger, db
from cps.search_metadata import cl as metadata_providers
from cps.utils.shelfmark_import_provenance import select_exact_hardcover_result
import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()
ENGLISH_LANGUAGE_CODES = {"en", "eng"}
EBOOK_IMPORT_FORMATS = {"EPUB", "EPUB3", "KEPUB", "AZW", "AZW3", "MOBI"}


@dataclass
class ExactHardcoverLookupOutcome:
    attempted: bool = False
    metadata: object | None = None
    existing_identifiers: dict[str, str] = field(default_factory=dict)
    match_basis: str | None = None
    reason: str | None = None
    error: str | None = None
    preferred_edition_id: str | None = None
    preferred_edition_reason: str | None = None


def _normalize_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get_book_identifier_map(book) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for identifier in getattr(book, 'identifiers', []) or []:
        identifier_type = getattr(identifier, 'type', None)
        identifier_value = getattr(identifier, 'val', None)
        if identifier_type and identifier_value:
            identifiers[str(identifier_type)] = str(identifier_value)
    return identifiers


def _find_metadata_provider(provider_id: str):
    for provider in metadata_providers:
        if getattr(provider, '__id__', None) == provider_id:
            return provider
    return None


def _metadata_source_id(metadata) -> str | None:
    source = getattr(metadata, 'source', None)
    return _normalize_text(getattr(source, 'id', None))


def _is_english_language(language_code: str | None) -> bool:
    normalized = _normalize_text(language_code)
    if normalized is None:
        return False
    return normalized.lower() in ENGLISH_LANGUAGE_CODES


def _get_book_formats(book) -> set[str]:
    formats: set[str] = set()
    for entry in getattr(book, 'data', []) or []:
        book_format = _normalize_text(getattr(entry, 'format', None))
        if book_format is not None:
            formats.add(book_format.upper())
    return formats


def _get_book_language_codes(book) -> set[str]:
    language_codes: set[str] = set()
    for language in getattr(book, 'languages', []) or []:
        code = _normalize_text(getattr(language, 'lang_code', None))
        if code is not None:
            language_codes.add(code.lower())
    return language_codes


def _format_language_codes(language_codes: set[str]) -> str:
    if not language_codes:
        return ""
    return ",".join(sorted(language_codes))


def _get_metadata_identifier(metadata, identifier_type: str) -> str | None:
    identifiers = getattr(metadata, 'identifiers', None)
    if not isinstance(identifiers, dict):
        return None
    return _normalize_text(identifiers.get(identifier_type))


def _metadata_language_code(metadata) -> str | None:
    return _normalize_text(getattr(metadata, 'hardcover_matched_edition_language', None))


def _metadata_is_ebook(metadata) -> bool:
    metadata_format = _normalize_text(getattr(metadata, 'format', None))
    if metadata_format is None:
        return False
    return metadata_format.lower() == 'e-book'


def _metadata_matches_language(metadata, language_codes: set[str]) -> bool:
    if not language_codes:
        return False
    metadata_language = _metadata_language_code(metadata)
    if metadata_language is None:
        return False
    return metadata_language.lower() in language_codes


def _annotate_exact_hardcover_preferred_edition(metadata, selection_reason: str) -> None:
    metadata.hardcover_preferred_edition_id = _get_metadata_identifier(metadata, 'hardcover-edition')
    metadata.hardcover_preferred_edition_reason = selection_reason
    metadata.hardcover_preferred_edition_language_code = _metadata_language_code(metadata)


def _apply_exact_hardcover_book_level_fallback(metadata) -> None:
    identifiers = getattr(metadata, 'identifiers', None)
    if not isinstance(identifiers, dict):
        identifiers = {}
    else:
        identifiers = dict(identifiers)

    identifiers.pop('hardcover-edition', None)
    identifiers.pop('isbn', None)
    metadata.identifiers = identifiers
    metadata.publisher = ""
    metadata.publishedDate = _normalize_text(getattr(metadata, 'hardcover_book_release_date', None)) or ""
    metadata.languages = []
    metadata.format = None
    metadata.cover = ""


def _resolve_preferred_exact_hardcover_metadata(book, results, existing_identifiers):
    explicit_result = select_exact_hardcover_result(results, existing_identifiers)
    if explicit_result is None:
        return None, None

    explicit_edition = existing_identifiers.get('hardcover-edition')
    if explicit_edition:
        _annotate_exact_hardcover_preferred_edition(explicit_result, 'explicit hardcover-edition')
        return explicit_result, 'explicit hardcover-edition'

    preferred_language_codes = _get_book_language_codes(book)
    prefers_ebook = bool(_get_book_formats(book) & EBOOK_IMPORT_FORMATS)
    book_id = getattr(book, 'id', 'unknown')
    imported_language_label = _format_language_codes(preferred_language_codes)

    if prefers_ebook:
        default_ebook_edition_id = _normalize_text(
            getattr(explicit_result, 'hardcover_default_ebook_edition_id', None)
        )
        if default_ebook_edition_id:
            for result in results:
                if _get_metadata_identifier(result, 'hardcover-edition') == default_ebook_edition_id:
                    default_ebook_language = _metadata_language_code(result)
                    if preferred_language_codes:
                        if _metadata_matches_language(result, preferred_language_codes):
                            log.info(
                                "Imported ebook language=%s; accepting default_ebook_edition %s for book_id=%s because it matches imported language",
                                imported_language_label,
                                default_ebook_edition_id,
                                book_id,
                            )
                            _annotate_exact_hardcover_preferred_edition(result, 'default_ebook_edition')
                            return result, 'default_ebook_edition'

                        log.info(
                            "Imported ebook language=%s; rejecting default_ebook_edition %s for book_id=%s because language=%s does not match imported language",
                            imported_language_label,
                            default_ebook_edition_id,
                            book_id,
                            default_ebook_language or "",
                        )
                    elif (
                        default_ebook_language is None
                        or _is_english_language(default_ebook_language)
                    ):
                        _annotate_exact_hardcover_preferred_edition(result, 'default_ebook_edition')
                        return result, 'default_ebook_edition'

        ebook_candidates = [result for result in results if _metadata_is_ebook(result)]
        for result in ebook_candidates:
            if _metadata_matches_language(result, preferred_language_codes):
                if preferred_language_codes:
                    log.info(
                        "Imported ebook language=%s; preferring matching Hardcover ebook edition %s for book_id=%s",
                        imported_language_label,
                        _get_metadata_identifier(result, 'hardcover-edition') or "",
                        book_id,
                    )
                _annotate_exact_hardcover_preferred_edition(result, 'language-matching ebook edition')
                return result, 'language-matching ebook edition'
        if not preferred_language_codes:
            for result in ebook_candidates:
                if _is_english_language(_metadata_language_code(result)):
                    _annotate_exact_hardcover_preferred_edition(result, 'english ebook edition search')
                    return result, 'english ebook edition search'

    if preferred_language_codes and _metadata_matches_language(explicit_result, preferred_language_codes):
        _annotate_exact_hardcover_preferred_edition(explicit_result, 'language-matching fallback')
        return explicit_result, 'language-matching fallback'

    explicit_result.hardcover_preferred_edition_id = None
    explicit_result.hardcover_preferred_edition_reason = 'book-level fallback'
    explicit_result.hardcover_preferred_edition_language_code = _metadata_language_code(explicit_result)
    _apply_exact_hardcover_book_level_fallback(explicit_result)
    return explicit_result, 'book-level fallback'


def _choose_exact_hardcover_title(book, metadata, existing_identifiers: dict[str, str]) -> None:
    if _metadata_source_id(metadata) != 'hardcover':
        return

    book_id = getattr(book, 'id', 'unknown')
    provenance_id = existing_identifiers.get('hardcover-id')
    provenance_slug = existing_identifiers.get('hardcover-slug')
    matched_edition_title = (
        _normalize_text(getattr(metadata, 'hardcover_matched_edition_title', None))
        or _normalize_text(getattr(metadata, 'title', None))
    )
    matched_edition_language = _normalize_text(
        getattr(metadata, 'hardcover_matched_edition_language', None)
    )
    book_title = _normalize_text(getattr(metadata, 'hardcover_book_title', None))
    default_ebook_title = _normalize_text(
        getattr(metadata, 'hardcover_default_ebook_title', None)
    )
    default_ebook_language = _normalize_text(
        getattr(metadata, 'hardcover_default_ebook_language', None)
    )
    default_cover_title = _normalize_text(
        getattr(metadata, 'hardcover_default_cover_title', None)
    )
    imported_title = _normalize_text(getattr(book, 'title', None))
    imported_language_codes = _get_book_language_codes(book)
    preferred_edition_id = _normalize_text(
        getattr(metadata, 'hardcover_preferred_edition_id', None)
    )
    preferred_edition_reason = _normalize_text(
        getattr(metadata, 'hardcover_preferred_edition_reason', None)
    )

    log.info(
        "Exact Hardcover provenance for book %s: id=%s slug=%s",
        book_id,
        provenance_id,
        provenance_slug,
    )
    log.info(
        "Exact Hardcover metadata titles for book %s: book_title=%r default_ebook_title=%r "
        "default_ebook_language=%s default_cover_title=%r matched_edition_title=%r "
        "matched_edition_language=%s",
        book_id,
        book_title,
        default_ebook_title,
        default_ebook_language or "",
        default_cover_title,
        matched_edition_title,
        matched_edition_language or "",
    )

    chosen_title = matched_edition_title
    chosen_source = "matched edition title"

    if preferred_edition_id and preferred_edition_reason != 'book-level fallback':
        chosen_title = (
            matched_edition_title
            or default_ebook_title
            or book_title
            or imported_title
        )
        if chosen_title == default_ebook_title and preferred_edition_reason == 'default_ebook_edition':
            chosen_source = "default ebook edition title"
        elif chosen_title == matched_edition_title:
            chosen_source = "matched edition title"
        elif chosen_title == book_title:
            chosen_source = "book title"
        elif chosen_title == imported_title:
            chosen_source = "preserved imported title"
    elif existing_identifiers.get('hardcover-edition'):
        chosen_title = (
            matched_edition_title
            or default_ebook_title
            or book_title
            or imported_title
        )
        if chosen_title == default_ebook_title:
            chosen_source = "default ebook edition title"
        elif chosen_title == book_title:
            chosen_source = "book title"
        elif chosen_title == imported_title:
            chosen_source = "preserved imported title"
    else:
        if imported_language_codes:
            if default_ebook_title and (
                default_ebook_language is not None
                and default_ebook_language.lower() in imported_language_codes
            ):
                chosen_title = default_ebook_title
                chosen_source = "default ebook edition title"
            elif matched_edition_title and (
                matched_edition_language is not None
                and matched_edition_language.lower() in imported_language_codes
            ):
                chosen_title = matched_edition_title
                chosen_source = "matched edition title"
            elif imported_title:
                chosen_title = imported_title
                chosen_source = "preserved imported title"
            elif book_title:
                chosen_title = book_title
                chosen_source = "book title"
        else:
            if default_ebook_title and _is_english_language(default_ebook_language):
                chosen_title = default_ebook_title
                chosen_source = "default ebook edition title"
            elif book_title:
                chosen_title = book_title
                chosen_source = "book title"
            elif matched_edition_title and (
                matched_edition_language is None or _is_english_language(matched_edition_language)
            ):
                chosen_title = matched_edition_title
                chosen_source = "matched edition title"
            elif imported_title:
                chosen_title = imported_title
                chosen_source = "preserved imported title"

    if chosen_source == "preserved imported title":
        log.info(
            "Preserving imported title for book %s; exact Hardcover matched edition title appears language-mismatched",
            book_id,
        )
    else:
        log.info(
            "Choosing %s for exact Hardcover metadata on book %s",
            chosen_source,
            book_id,
        )

    if chosen_title is not None:
        metadata.title = chosen_title
        metadata.hardcover_title_source = chosen_source


def _choose_exact_hardcover_cover(book, metadata) -> None:
    if _metadata_source_id(metadata) != 'hardcover':
        return

    book_id = getattr(book, 'id', 'unknown')
    preferred_edition_id = _normalize_text(
        getattr(metadata, 'hardcover_preferred_edition_id', None)
    )
    preferred_edition_reason = _normalize_text(
        getattr(metadata, 'hardcover_preferred_edition_reason', None)
    )
    matched_edition_cover = (
        _normalize_text(getattr(metadata, 'hardcover_matched_edition_cover_url', None))
        or _normalize_text(getattr(metadata, 'cover', None))
    )
    default_ebook_cover = _normalize_text(
        getattr(metadata, 'hardcover_default_ebook_cover_url', None)
    )
    default_cover = _normalize_text(
        getattr(metadata, 'hardcover_default_cover_url', None)
    )

    if preferred_edition_id and preferred_edition_reason != 'book-level fallback':
        if matched_edition_cover:
            metadata.cover = matched_edition_cover
            metadata.hardcover_cover_source = 'chosen edition cover'
            log.info(
                "Using chosen edition cover for exact Hardcover provenance on book_id=%s",
                book_id,
            )
            return
        if preferred_edition_reason == 'default_ebook_edition' and default_ebook_cover:
            metadata.cover = default_ebook_cover
            metadata.hardcover_cover_source = 'chosen edition cover'
            log.info(
                "Using chosen edition cover for exact Hardcover provenance on book_id=%s",
                book_id,
            )
            return

    if default_cover:
        metadata.cover = default_cover
        metadata.hardcover_cover_source = 'parent/default cover fallback'
        log.info(
            "Falling back to parent/default cover because chosen edition cover was unavailable for book_id=%s",
            book_id,
        )
        return

    metadata.cover = ""
    metadata.hardcover_cover_source = 'no cover resolved'


def _determine_exact_hardcover_match_basis(metadata, existing_identifiers: dict[str, str]) -> str | None:
    metadata_identifiers = getattr(metadata, 'identifiers', None)
    if not isinstance(metadata_identifiers, dict):
        metadata_identifiers = {}

    hardcover_edition = existing_identifiers.get('hardcover-edition')
    if hardcover_edition and metadata_identifiers.get('hardcover-edition') == hardcover_edition:
        return 'hardcover-edition'

    hardcover_slug = existing_identifiers.get('hardcover-slug')
    if hardcover_slug and metadata_identifiers.get('hardcover-slug') == hardcover_slug:
        return 'hardcover-slug'

    hardcover_id = existing_identifiers.get('hardcover-id')
    if hardcover_id and metadata_identifiers.get('hardcover-id') == hardcover_id:
        return 'hardcover-id'

    return None


def _load_cover_update_dependencies():
    from cps import helper as helper_module
    from cps.cover_utils import apply_selected_cover_url

    return helper_module, apply_selected_cover_url


def _apply_hardcover_cover_to_book(book, metadata) -> bool:
    if _metadata_source_id(metadata) != 'hardcover':
        return False

    cover_url = _normalize_text(getattr(metadata, 'cover', None))
    book_id = getattr(book, 'id', 'unknown')
    cover_source = _normalize_text(getattr(metadata, 'hardcover_cover_source', None)) or 'provider cover'

    if not cover_url:
        log.info(
            "No safe preferred exact cover found; preserving existing/imported cover for book_id=%s",
            book_id,
        )
        return False

    try:
        helper_module, apply_selected_cover_url = _load_cover_update_dependencies()
    except Exception as exc:
        log.warning(
            "Metadata fetch: cover helpers unavailable for book_id=%s; skipping exact Hardcover cover update: %s",
            book_id,
            exc,
        )
        return False

    log.info(
        "Applying exact Hardcover cover during ingest for book_id=%s from %s",
        book_id,
        cover_source,
    )
    outcome = apply_selected_cover_url(
        book_id=book_id,
        book_path=getattr(book, 'path', ''),
        cover_url=cover_url,
        logger=log,
        save_cover_from_url=helper_module.save_cover_from_url,
        refresh_thumbnail_cache=helper_module.replace_cover_thumbnail_cache,
    )
    if not outcome.applied:
        if outcome.error:
            log.warning(
                "Metadata fetch: exact Hardcover cover update failed for book_id=%s error=%s",
                book_id,
                outcome.error,
            )
        return False

    if outcome.cleared_cover:
        book.has_cover = 0
    else:
        book.has_cover = 1

    log.info(
        "Queued cover thumbnail invalidation after exact Hardcover ingest cover update for book_id=%s",
        book_id,
    )
    return True


def _fetch_exact_hardcover_metadata(book, provider_hierarchy, enabled_map):
    """Fetch metadata through the exact Hardcover path when stable identifiers exist.

    `hardcover-id` is the lookup key. If the ingest sidecar also attached
    `hardcover-edition` or `hardcover-slug`, those identifiers are used to pick the
    exact returned Hardcover result rather than falling back to a fuzzy first match.
    """
    existing_identifiers = _get_book_identifier_map(book)
    hardcover_id = existing_identifiers.get('hardcover-id')
    if not hardcover_id:
        return ExactHardcoverLookupOutcome(
            existing_identifiers=existing_identifiers,
            reason='no_provenance',
        )

    if 'hardcover' not in provider_hierarchy:
        return ExactHardcoverLookupOutcome(
            existing_identifiers=existing_identifiers,
            reason='provider_not_configured',
        )

    if not enabled_map.get('hardcover', True):
        return ExactHardcoverLookupOutcome(
            existing_identifiers=existing_identifiers,
            reason='provider_disabled',
        )

    provider = _find_metadata_provider('hardcover')
    if not provider or not provider.active:
        return ExactHardcoverLookupOutcome(
            existing_identifiers=existing_identifiers,
            reason='provider_unavailable',
        )

    log.info(
        "Metadata fetch: using exact Hardcover lookup for book_id=%s hardcover-id=%s",
        getattr(book, 'id', 'unknown'),
        hardcover_id,
    )

    hardcover_edition = existing_identifiers.get('hardcover-edition')
    if hardcover_edition:
        log.info(
            "Metadata fetch: preferring Hardcover result matching hardcover-edition=%s for book_id=%s",
            hardcover_edition,
            getattr(book, 'id', 'unknown'),
        )
    else:
        hardcover_slug = existing_identifiers.get('hardcover-slug')
        if hardcover_slug:
            log.info(
                "Metadata fetch: preferring Hardcover result matching hardcover-slug=%s for book_id=%s",
                hardcover_slug,
                getattr(book, 'id', 'unknown'),
            )

    try:
        results = provider.search(f"hardcover-id:{hardcover_id}", "", "en") or []
    except Exception as e:
        return ExactHardcoverLookupOutcome(
            attempted=True,
            existing_identifiers=existing_identifiers,
            reason='lookup_error',
            error=str(e),
        )

    if not results:
        return ExactHardcoverLookupOutcome(
            attempted=True,
            existing_identifiers=existing_identifiers,
            reason='no_results',
        )

    metadata, preferred_edition_reason = _resolve_preferred_exact_hardcover_metadata(
        book,
        results,
        existing_identifiers,
    )
    if metadata is None:
        return ExactHardcoverLookupOutcome(
            attempted=True,
            existing_identifiers=existing_identifiers,
            reason='no_exact_match',
        )

    return ExactHardcoverLookupOutcome(
        attempted=True,
        metadata=metadata,
        existing_identifiers=existing_identifiers,
        match_basis=_determine_exact_hardcover_match_basis(metadata, existing_identifiers),
        preferred_edition_id=_normalize_text(getattr(metadata, 'hardcover_preferred_edition_id', None)),
        preferred_edition_reason=preferred_edition_reason,
    )

def fetch_and_apply_metadata(book_id: int, user_enabled: bool = False) -> bool:
    """
    Fetch metadata for a newly ingested book and apply it if settings allow.
    
    Args:
        book_id: The ID of the book to fetch metadata for
        user_enabled: Deprecated parameter - metadata fetching is now admin-controlled only
        
    Returns:
        bool: True if metadata was successfully fetched and applied, False otherwise
    """
    try:
        if not db.CalibreDB.session_factory:
            log.error("CalibreDB not initialized; skipping metadata fetch")
            return False

        # Check global settings (admin-controlled only)
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        
        if not cwa_settings.get('auto_metadata_fetch_enabled', False):
            log.debug("Auto metadata fetch disabled by administrator")
            return False
            
        # Get the book
        calibre_db_instance = db.CalibreDB(expire_on_commit=False, init=True)
        book = calibre_db_instance.get_book(book_id)
        if not book:
            log.error(f"Book with ID {book_id} not found")
            return False
            
        # Create fuzzy fallback search query from book title and author.
        search_query = book.title
        if book.authors:
            author_names = [author.name for author in book.authors]
            search_query += " " + " ".join(author_names)
            
        log.info(f"Fetching metadata for: {search_query}")
        
        # Get provider hierarchy
        try:
            provider_hierarchy = json.loads(cwa_settings.get('metadata_provider_hierarchy', '["google","douban","dnb","ibdb","comicvine"]'))
        except (json.JSONDecodeError, TypeError):
            provider_hierarchy = ["google", "douban", "dnb", "ibdb", "comicvine"]

        # Global provider enablement map
        enabled_map = _parse_metadata_providers_enabled(
            cwa_settings.get('metadata_providers_enabled', '{}')
        )

        metadata_found = False

        exact_hardcover_lookup = _fetch_exact_hardcover_metadata(
            book,
            provider_hierarchy=provider_hierarchy,
            enabled_map=enabled_map,
        )
        exact_identifiers = exact_hardcover_lookup.existing_identifiers
        if exact_hardcover_lookup.reason == 'no_provenance':
            log.info(
                "Metadata fetch: no exact Hardcover provenance present for book_id=%s; falling back to fuzzy lookup",
                book.id,
            )
        elif exact_hardcover_lookup.reason == 'provider_not_configured':
            log.info(
                "Metadata fetch: exact Hardcover provenance present for book_id=%s hardcover-id=%s, "
                "but Hardcover is not in the metadata provider hierarchy; falling back to fuzzy lookup",
                book.id,
                exact_identifiers.get('hardcover-id'),
            )
        elif exact_hardcover_lookup.reason == 'provider_disabled':
            log.info(
                "Metadata fetch: exact Hardcover provenance present for book_id=%s hardcover-id=%s, "
                "but the Hardcover provider is disabled; falling back to fuzzy lookup",
                book.id,
                exact_identifiers.get('hardcover-id'),
            )
        elif exact_hardcover_lookup.reason == 'provider_unavailable':
            log.info(
                "Metadata fetch: exact Hardcover provenance present for book_id=%s hardcover-id=%s, "
                "but the Hardcover provider is unavailable; falling back to fuzzy lookup",
                book.id,
                exact_identifiers.get('hardcover-id'),
            )
        elif exact_hardcover_lookup.reason == 'lookup_error':
            log.warning(
                "Metadata fetch: exact Hardcover lookup failed for book_id=%s hardcover-id=%s: %s",
                book.id,
                exact_identifiers.get('hardcover-id'),
                exact_hardcover_lookup.error,
            )
            log.info(
                "Metadata fetch: falling back to fuzzy lookup for book_id=%s after exact Hardcover lookup failure",
                book.id,
            )
        elif exact_hardcover_lookup.reason == 'no_results':
            log.info(
                "Metadata fetch: exact Hardcover lookup returned no results for book_id=%s hardcover-id=%s; "
                "falling back to fuzzy lookup",
                book.id,
                exact_identifiers.get('hardcover-id'),
            )
        elif exact_hardcover_lookup.reason == 'no_exact_match':
            log.info(
                "Metadata fetch: exact Hardcover lookup found no matching result for book_id=%s hardcover-id=%s; "
                "falling back to fuzzy lookup",
                book.id,
                exact_identifiers.get('hardcover-id'),
            )

        if exact_hardcover_lookup.metadata is not None:
            if exact_hardcover_lookup.match_basis == 'hardcover-edition':
                log.info(
                    "Metadata fetch: exact Hardcover result matched via hardcover-edition=%s for book_id=%s",
                    exact_identifiers.get('hardcover-edition'),
                    book.id,
                )
            elif exact_hardcover_lookup.match_basis == 'hardcover-slug':
                log.info(
                    "Metadata fetch: exact Hardcover result matched via hardcover-slug=%s for book_id=%s",
                    exact_identifiers.get('hardcover-slug'),
                    book.id,
                )
            elif exact_hardcover_lookup.match_basis == 'hardcover-id':
                log.info(
                    "Metadata fetch: exact Hardcover result matched via hardcover-id=%s for book_id=%s",
                    exact_identifiers.get('hardcover-id'),
                    book.id,
                )

            preferred_edition_reason = exact_hardcover_lookup.preferred_edition_reason
            preferred_edition_id = exact_hardcover_lookup.preferred_edition_id
            if preferred_edition_id and preferred_edition_reason:
                log.info(
                    "Resolved preferred exact Hardcover edition %s for book_id=%s from %s",
                    preferred_edition_id,
                    book.id,
                    preferred_edition_reason,
                )
                log.info(
                    "Using edition-level metadata from Hardcover edition %s for title/isbn/language/publisher/pages/release date",
                    preferred_edition_id,
                )
            else:
                log.info(
                    "No safe preferred exact Hardcover edition was resolved for book_id=%s; falling back to book-level title safety",
                    book.id,
                )
            log.info(
                "Using parent book metadata for slug/series/description on book_id=%s",
                book.id,
            )

            _choose_exact_hardcover_title(
                book,
                exact_hardcover_lookup.metadata,
                exact_identifiers,
            )
            _choose_exact_hardcover_cover(book, exact_hardcover_lookup.metadata)

            if _apply_metadata_to_book(book, exact_hardcover_lookup.metadata, calibre_db_instance):
                log.info(f"Successfully applied exact Hardcover metadata for book: {book.title}")
                metadata_found = True
            else:
                log.info(
                    "Metadata fetch: exact Hardcover metadata produced no applied changes for book_id=%s; "
                    "falling back to fuzzy lookup",
                    book.id,
                )

        if metadata_found:
            calibre_db_instance.session.close()
            return True

        for provider_id in provider_hierarchy:
            # Check if explicitly disabled (default is enabled if not specified)
            is_enabled = enabled_map.get(provider_id, True)
            if not is_enabled:
                log.debug(f"Provider {provider_id} is globally disabled")
                continue
            try:
                # Find the provider
                provider = _find_metadata_provider(provider_id)
                        
                if not provider or not provider.active:
                    continue
                    
                log.debug(f"Trying metadata provider: {provider.__name__}")
                
                # Search for metadata
                results = provider.search(search_query, "", "en")
                if not results or len(results) == 0:
                    continue
                    
                # Use the first result
                metadata = results[0]
                
                # Apply metadata to book
                if _apply_metadata_to_book(book, metadata, calibre_db_instance):
                    log.info(f"Successfully applied metadata from {provider.__name__} for book: {book.title}")
                    metadata_found = True
                    break
                    
            except Exception as e:
                log.warning(f"Error fetching metadata from provider {provider_id}: {e}")
                continue
                
        calibre_db_instance.session.close()
        return metadata_found
        
    except Exception as e:
        log.error(f"Error in fetch_and_apply_metadata: {e}", exc_info=True)
        return False


def _apply_metadata_to_book(book, metadata, calibre_db_instance) -> bool:
    """
    Apply fetched metadata to a book record.
    
    Args:
        book: The book database record
        metadata: The metadata record from provider
        calibre_db_instance: Database instance
        
    Returns:
        bool: True if metadata was successfully applied
    """
    try:
        # Get CWA settings to check smart application preference and field selections
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        use_smart_application = cwa_settings.get('auto_metadata_smart_application', False)
        
        updated = False
        cover_updated = False
        
        # Update title - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_title', True) and 
            metadata.title and metadata.title.strip()):
            if use_smart_application:
                if len(metadata.title.strip()) > len(book.title.strip()):
                    book.title = metadata.title.strip()
                    updated = True
            else:
                book.title = metadata.title.strip()
                updated = True
            
        # Update authors - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_authors', True) and 
            metadata.authors and len(metadata.authors) > 0):
            # Clear existing authors
            book.authors.clear()
            for author_name in metadata.authors:
                if author_name and author_name.strip():
                    author = calibre_db_instance.get_author_by_name(author_name.strip())
                    if not author:
                        author = db.Authors(author_name.strip(), author_name.strip())
                        calibre_db_instance.session.add(author)
                    book.authors.append(author)
            updated = True
            
        # Update description - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_description', True) and 
            metadata.description and metadata.description.strip()):
            current_description = book.comments[0].text if book.comments else ""
            if use_smart_application:
                if len(metadata.description.strip()) > len(current_description):
                    if book.comments:
                        book.comments[0].text = metadata.description.strip()
                    else:
                        comment = db.Comments(metadata.description.strip(), book.id)
                        calibre_db_instance.session.add(comment)
                    updated = True
            else:
                if book.comments:
                    book.comments[0].text = metadata.description.strip()
                else:
                    comment = db.Comments(metadata.description.strip(), book.id)
                    calibre_db_instance.session.add(comment)
                updated = True
            
        # Update publisher - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_publisher', True) and 
            metadata.publisher and metadata.publisher.strip()):
            if use_smart_application:
                if not book.publishers or len(book.publishers) == 0:
                    publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                    if not publisher:
                        publisher = db.Publishers(metadata.publisher.strip(), metadata.publisher.strip())
                        calibre_db_instance.session.add(publisher)
                    book.publishers = [publisher]
                    updated = True
            else:
                # Clear existing publishers and add new one
                book.publishers.clear()
                publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                if not publisher:
                    publisher = db.Publishers(metadata.publisher.strip(), metadata.publisher.strip())
                    calibre_db_instance.session.add(publisher)
                book.publishers = [publisher]
                updated = True
                
        # Update tags if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_tags', True) and 
            hasattr(metadata, 'tags') and metadata.tags):
            for tag_name in metadata.tags:
                if tag_name and tag_name.strip():
                    tag = calibre_db_instance.get_tag_by_name(tag_name.strip())
                    if not tag:
                        tag = db.Tags(name=tag_name.strip())
                        calibre_db_instance.session.add(tag)
                    if tag not in book.tags:
                        book.tags.append(tag)
            updated = True
            
        # Update series if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_series', True) and 
            hasattr(metadata, 'series') and metadata.series and metadata.series.strip()):
            series = calibre_db_instance.get_series_by_name(metadata.series.strip())
            if not series:
                series = db.Series(metadata.series.strip(), metadata.series.strip())
                calibre_db_instance.session.add(series)
            book.series.clear()
            book.series.append(series)
            
            # Set series index if available
            if hasattr(metadata, 'series_index') and metadata.series_index:
                try:
                    # Convert to float first to validate, then store as string (DB column is String)
                    float_value = float(metadata.series_index)
                    book.series_index = str(float_value)
                except (ValueError, TypeError):
                    book.series_index = '1.0'
            updated = True
            
        # Update published date if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_published_date', True) and 
            hasattr(metadata, 'publishedDate') and metadata.publishedDate):
            try:
                if isinstance(metadata.publishedDate, str):
                    # Try to parse various date formats
                    for fmt in ['%Y-%m-%d', '%Y-%m', '%Y']:
                        try:
                            book.pubdate = datetime.strptime(metadata.publishedDate, fmt).date()
                            updated = True
                            break
                        except ValueError:
                            continue
                elif hasattr(metadata.publishedDate, 'date'):
                    book.pubdate = metadata.publishedDate.date()
                    updated = True
            except Exception as e:
                log.warning(f"Error parsing published date: {e}")
                
        # Update rating if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_rating', True) and 
            hasattr(metadata, 'rating') and metadata.rating):
            try:
                rating_value = float(metadata.rating)
                if 0 <= rating_value <= 10:  # Calibre uses 0-10 scale
                    if book.ratings:
                        book.ratings[0].rating = int(rating_value * 2)  # Convert to Calibre's 0-10 scale
                    else:
                        rating = db.Ratings(rating=int(rating_value * 2))
                        calibre_db_instance.session.add(rating)
                        book.ratings = [rating]
                    updated = True
            except (ValueError, TypeError):
                pass
                
        # Update identifiers if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_identifiers', True) and 
            hasattr(metadata, 'identifiers') and metadata.identifiers):
            for identifier_type, identifier_value in metadata.identifiers.items():
                if identifier_type and identifier_value:
                    persisted_identifier = False
                    # Check if identifier already exists
                    existing = False
                    for identifier in book.identifiers:
                        if identifier.type == identifier_type:
                            identifier.val = identifier_value
                            existing = True
                            persisted_identifier = True
                            break
                    if not existing:
                        new_identifier = db.Identifiers(identifier_value, identifier_type, book.id)
                        calibre_db_instance.session.add(new_identifier)
                        book.identifiers.append(new_identifier)
                        persisted_identifier = True
                    if (
                        persisted_identifier
                        and identifier_type == 'hardcover-edition'
                        and _metadata_source_id(metadata) == 'hardcover'
                        and _normalize_text(getattr(metadata, 'hardcover_preferred_edition_id', None))
                    ):
                        log.info(
                            "Persisted hardcover-edition=%s after exact Hardcover provenance resolution for book_id=%s",
                            identifier_value,
                            getattr(book, 'id', 'unknown'),
                        )
                    updated = True
        
        # Handle cover image for exact Hardcover metadata - only if enabled in settings
        if cwa_settings.get('auto_metadata_update_cover', True):
            cover_updated = _apply_hardcover_cover_to_book(book, metadata)
            updated |= cover_updated
        
        if updated:
            if cover_updated and hasattr(book, 'last_modified'):
                book.last_modified = datetime.now(timezone.utc)
                set_dirty = getattr(calibre_db_instance, 'set_metadata_dirty', None)
                if callable(set_dirty):
                    set_dirty(getattr(book, 'id', None))
            calibre_db_instance.session.commit()
            
        return updated
        
    except Exception as e:
        log.error(f"Error applying metadata to book {getattr(book, 'id', 'unknown')}: {e}")
        calibre_db_instance.session.rollback()
        return False


def _parse_metadata_providers_enabled(raw_value):
    """Lightweight parser for metadata_providers_enabled without importing cwa_functions."""
    try:
        if raw_value is None:
            return {}
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode('utf-8', errors='ignore')
        if isinstance(raw_value, str):
            s = raw_value.strip()
            if not s:
                return {}
            if s.startswith("'") and s.endswith("'"):
                s = s[1:-1]
            if not s:
                return {}
            data = json.loads(s)
            return data if isinstance(data, dict) else {}
        if isinstance(raw_value, dict):
            return raw_value
        return {}
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}
