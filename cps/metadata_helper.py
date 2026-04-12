# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from dataclasses import dataclass, field
import json

from cps import logger, db
from cps.search_metadata import cl as metadata_providers
from cps.utils.shelfmark_import_provenance import select_exact_hardcover_result
import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()


@dataclass
class ExactHardcoverLookupOutcome:
    attempted: bool = False
    metadata: object | None = None
    existing_identifiers: dict[str, str] = field(default_factory=dict)
    match_basis: str | None = None
    reason: str | None = None
    error: str | None = None


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

    metadata = select_exact_hardcover_result(results, existing_identifiers)
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
                from datetime import datetime
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
                    # Check if identifier already exists
                    existing = False
                    for identifier in book.identifiers:
                        if identifier.type == identifier_type:
                            identifier.val = identifier_value
                            existing = True
                            break
                    if not existing:
                        new_identifier = db.Identifiers(identifier_value, identifier_type, book.id)
                        calibre_db_instance.session.add(new_identifier)
                        book.identifiers.append(new_identifier)
                    updated = True
        
        # Handle cover image - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_cover', True) and 
            hasattr(metadata, 'cover') and metadata.cover):
            # TODO: Implement cover resolution checking for smart mode
            # For now, just apply the cover in normal mode
            if not use_smart_application:
                # Apply cover (implementation depends on how covers are handled in Calibre-Web)
                pass
        
        if updated:
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
