# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[2] / "cps" / "metadata_helper.py"


def _load_metadata_helper_module(monkeypatch, *, book, providers, settings):
    logger_instance = types.SimpleNamespace(
        error=mock.Mock(),
        warning=mock.Mock(),
        info=mock.Mock(),
        debug=mock.Mock(),
    )

    class DummyCalibreDB:
        session_factory = object()

        def __init__(self, expire_on_commit=False, init=True):
            self.session = types.SimpleNamespace(close=lambda: None)

        def get_book(self, book_id):
            assert book_id == book.id
            return book

    cps_module = types.ModuleType("cps")
    cps_module.logger = types.SimpleNamespace(create=lambda: logger_instance)
    cps_module.db = types.SimpleNamespace(CalibreDB=DummyCalibreDB)

    search_metadata_module = types.ModuleType("cps.search_metadata")
    search_metadata_module.cl = providers

    provenance_module = types.ModuleType("cps.utils.shelfmark_import_provenance")
    provenance_module.select_exact_hardcover_result = (
        lambda results, identifiers: results[0] if results else None
    )
    utils_module = types.ModuleType("cps.utils")

    cwa_db_module = types.ModuleType("cwa_db")

    class DummyCwaDb:
        def get_cwa_settings(self):
            return settings

    cwa_db_module.CWA_DB = DummyCwaDb

    monkeypatch.setitem(sys.modules, "cps", cps_module)
    monkeypatch.setitem(sys.modules, "cps.search_metadata", search_metadata_module)
    monkeypatch.setitem(sys.modules, "cps.utils", utils_module)
    monkeypatch.setitem(sys.modules, "cps.utils.shelfmark_import_provenance", provenance_module)
    monkeypatch.setitem(sys.modules, "cwa_db", cwa_db_module)

    module_name = "test_metadata_helper_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, logger_instance


def _flatten_log_messages(log_mock):
    messages: list[str] = []
    for call in log_mock.call_args_list:
        if not call.args:
            continue
        template = call.args[0]
        if len(call.args) > 1:
            try:
                rendered = template % call.args[1:]
            except TypeError:
                rendered = " ".join(str(part) for part in call.args)
        else:
            rendered = str(template)
        messages.append(rendered)
    return messages


def _build_hardcover_edition_result(
    *,
    edition_id: str,
    title: str,
    language: str = "",
    edition_format: str = "E-Book",
    publisher: str = "",
    published_date: str = "",
    isbn: str | None = None,
    book_title: str = "Equal Rites",
    default_ebook_title: str = "Equal Rites",
    default_ebook_language: str = "eng",
    default_ebook_edition_id: str = "17801818",
    matched_cover_url: str = "",
    default_cover_url: str = "",
    default_ebook_cover_url: str = "",
):
    identifiers = {
        "hardcover-id": "434155",
        "hardcover-slug": "equal-rites",
        "hardcover-edition": edition_id,
    }
    if isbn is not None:
        identifiers["isbn"] = isbn
    return types.SimpleNamespace(
        identifiers=identifiers,
        title=title,
        cover=matched_cover_url,
        publisher=publisher,
        publishedDate=published_date,
        format=edition_format,
        languages=["English"] if language == "eng" else [],
        hardcover_book_title=book_title,
        hardcover_book_subtitle="Discworld: The Witches Collection",
        hardcover_book_release_date="1987-01-01",
        hardcover_default_ebook_title=default_ebook_title,
        hardcover_default_ebook_language=default_ebook_language,
        hardcover_default_ebook_edition_id=default_ebook_edition_id,
        hardcover_default_cover_title="Equal Rites",
        hardcover_default_cover_edition_id="31705896",
        hardcover_default_cover_url=default_cover_url,
        hardcover_default_ebook_cover_url=default_ebook_cover_url,
        hardcover_matched_edition_title=title,
        hardcover_matched_edition_cover_url=matched_cover_url,
        hardcover_matched_edition_language=language,
        hardcover_matched_edition_pages=288,
        hardcover_matched_edition_release_date=published_date,
        hardcover_matched_edition_publisher=publisher,
        hardcover_matched_edition_format=edition_format,
        description="A witchy Discworld novel",
        series="Discworld",
        series_index=3,
        source=types.SimpleNamespace(id="hardcover"),
    )


def test_fetch_and_apply_metadata_prefers_exact_hardcover_lookup(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Mort",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="379631"),
            types.SimpleNamespace(type="hardcover-edition", val="91234"),
        ],
    )

    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(
            return_value=[
                types.SimpleNamespace(
                    identifiers={"hardcover-id": "379631", "hardcover-edition": "91234"},
                    title="Mort",
                )
            ]
        ),
    )
    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[]),
    )
    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider, google_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover","google"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    hardcover_provider.search.assert_called_once_with("hardcover-id:379631", "", "en")
    google_provider.search.assert_not_called()
    apply_metadata.assert_called_once()

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Metadata fetch: using exact Hardcover lookup for book_id=1 hardcover-id=379631" in message
        for message in info_messages
    )
    assert any(
        "Metadata fetch: exact Hardcover result matched via hardcover-edition=91234 for book_id=1" in message
        for message in info_messages
    )
    assert any(
        "Resolved preferred exact Hardcover edition 91234 for book_id=1 from explicit hardcover-edition" in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_prefers_default_ebook_title_for_book_level_exact_lookup(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        languages=[types.SimpleNamespace(lang_code="eng")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    foreign_first = _build_hardcover_edition_result(
        edition_id="30541142",
        title="Das Erbe des Zauberers",
        language="ger",
        publisher="German Publisher",
        published_date="1987-01-15",
        isbn="9780000000001",
        matched_cover_url="https://covers.example/foreign.jpg",
        default_cover_url="https://covers.example/default-cover.jpg",
        default_ebook_cover_url="https://covers.example/default-ebook.jpg",
    )
    preferred_ebook = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        matched_cover_url="https://covers.example/17801818.jpg",
        default_cover_url="https://covers.example/default-cover.jpg",
        default_ebook_cover_url="https://covers.example/default-ebook.jpg",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[foreign_first, preferred_ebook]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.title == "Equal Rites"
    assert applied_metadata.publisher == "Corgi"
    assert applied_metadata.publishedDate == "1987-01-15"
    assert applied_metadata.identifiers["hardcover-edition"] == "17801818"
    assert applied_metadata.identifiers["isbn"] == "9780552131056"
    assert applied_metadata.hardcover_preferred_edition_id == "17801818"
    assert applied_metadata.hardcover_preferred_edition_reason == "default_ebook_edition"
    assert applied_metadata.cover == "https://covers.example/17801818.jpg"
    assert applied_metadata.hardcover_cover_source == "chosen edition cover"
    assert applied_metadata.description == "A witchy Discworld novel"
    assert applied_metadata.series == "Discworld"

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Exact Hardcover metadata titles for book 1:" in message
        and "matched_edition_title='Equal Rites'" in message
        and "default_ebook_title='Equal Rites'" in message
        for message in info_messages
    )
    assert any(
        "Resolved preferred exact Hardcover edition 17801818 for book_id=1 from default_ebook_edition" in message
        for message in info_messages
    )
    assert any(
        "Using edition-level metadata from Hardcover edition 17801818 for title/isbn/language/publisher/pages/release date" in message
        for message in info_messages
    )
    assert any(
        "Choosing default ebook edition title for exact Hardcover metadata on book 1" in message
        for message in info_messages
    )
    assert any(
        "Using chosen edition cover for exact Hardcover provenance on book_id=1" in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_prefers_english_ebook_edition_when_default_ebook_missing(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    spanish_ebook = _build_hardcover_edition_result(
        edition_id="30669326",
        title="Ritos iguales",
        language="spa",
        publisher="Spanish Publisher",
        published_date="1987-01-15",
        isbn="9780000000002",
        default_ebook_title="",
        default_ebook_language="",
        default_ebook_edition_id="",
    )
    english_ebook = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        default_ebook_title="",
        default_ebook_language="",
        default_ebook_edition_id="",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[spanish_ebook, english_ebook]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.title == "Equal Rites"
    assert applied_metadata.publisher == "Corgi"
    assert applied_metadata.identifiers["hardcover-edition"] == "17801818"

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Resolved preferred exact Hardcover edition 17801818 for book_id=1 from english ebook edition search" in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_prefers_matching_language_ebook_for_non_english_import(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Ritos iguales",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        languages=[types.SimpleNamespace(lang_code="spa")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    english_default = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        matched_cover_url="https://covers.example/17801818.jpg",
        default_ebook_cover_url="https://covers.example/default-ebook.jpg",
    )
    spanish_ebook = _build_hardcover_edition_result(
        edition_id="30669326",
        title="Ritos iguales",
        language="spa",
        publisher="Spanish Publisher",
        published_date="2003-05-01",
        isbn="9788497932615",
        matched_cover_url="https://covers.example/30669326.jpg",
        default_ebook_cover_url="https://covers.example/default-ebook.jpg",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[english_default, spanish_ebook]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.title == "Ritos iguales"
    assert applied_metadata.publisher == "Spanish Publisher"
    assert applied_metadata.publishedDate == "2003-05-01"
    assert applied_metadata.identifiers["hardcover-edition"] == "30669326"
    assert applied_metadata.identifiers["isbn"] == "9788497932615"
    assert applied_metadata.hardcover_preferred_edition_id == "30669326"
    assert applied_metadata.hardcover_preferred_edition_reason == "language-matching ebook edition"
    assert applied_metadata.cover == "https://covers.example/30669326.jpg"

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Imported ebook language=spa; rejecting default_ebook_edition 17801818 for book_id=1 because language=eng does not match imported language"
        in message
        for message in info_messages
    )
    assert any(
        "Imported ebook language=spa; preferring matching Hardcover ebook edition 30669326 for book_id=1"
        in message
        for message in info_messages
    )
    assert any(
        "Resolved preferred exact Hardcover edition 30669326 for book_id=1 from language-matching ebook edition"
        in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_falls_back_to_parent_default_cover_when_chosen_edition_cover_missing(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        languages=[types.SimpleNamespace(lang_code="eng")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    preferred_ebook = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        matched_cover_url="",
        default_cover_url="https://covers.example/default-cover.jpg",
        default_ebook_cover_url="",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[preferred_ebook]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.identifiers["hardcover-edition"] == "17801818"
    assert applied_metadata.cover == "https://covers.example/default-cover.jpg"
    assert applied_metadata.hardcover_cover_source == "parent/default cover fallback"

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Falling back to parent/default cover because chosen edition cover was unavailable for book_id=1"
        in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_preserves_non_english_import_when_no_matching_language_ebook_exists(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Ritos iguales",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        languages=[types.SimpleNamespace(lang_code="spa")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    english_default = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        default_cover_url="https://covers.example/default-cover.jpg",
        default_ebook_cover_url="https://covers.example/default-ebook.jpg",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[english_default]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.title == "Ritos iguales"
    assert applied_metadata.identifiers == {
        "hardcover-id": "434155",
        "hardcover-slug": "equal-rites",
    }
    assert applied_metadata.publisher == ""
    assert applied_metadata.publishedDate == "1987-01-01"
    assert applied_metadata.hardcover_preferred_edition_id is None
    assert applied_metadata.cover == "https://covers.example/default-cover.jpg"
    assert applied_metadata.hardcover_cover_source == "parent/default cover fallback"

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Imported ebook language=spa; rejecting default_ebook_edition 17801818 for book_id=1 because language=eng does not match imported language"
        in message
        for message in info_messages
    )
    assert any(
        "Preserving imported title for book 1; exact Hardcover matched edition title appears language-mismatched"
        in message
        for message in info_messages
    )
    assert any(
        "Falling back to parent/default cover because chosen edition cover was unavailable for book_id=1"
        in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_preserves_imported_title_when_only_foreign_edition_title_exists(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    hardcover_metadata = _build_hardcover_edition_result(
        edition_id="30669326",
        title="Ritos iguales",
        language="spa",
        publisher="Spanish Publisher",
        published_date="1987-01-15",
        isbn="9780000000002",
        book_title="",
        default_ebook_title="",
        default_ebook_language="",
        default_ebook_edition_id="",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[hardcover_metadata]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    applied_metadata = apply_metadata.call_args[0][1]
    assert applied_metadata.title == "Equal Rites"
    assert applied_metadata.identifiers == {
        "hardcover-id": "434155",
        "hardcover-slug": "equal-rites",
    }
    assert applied_metadata.publisher == ""
    assert applied_metadata.publishedDate == "1987-01-01"
    assert applied_metadata.hardcover_preferred_edition_id is None

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Preserving imported title for book 1; exact Hardcover matched edition title appears language-mismatched"
        in message
        for message in info_messages
    )
    assert any(
        "No safe preferred exact Hardcover edition was resolved for book_id=1; falling back to book-level title safety"
        in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_logs_fuzzy_fallback_when_exact_lookup_fails(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Mort",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[],
        identifiers=[types.SimpleNamespace(type="hardcover-id", val="379631")],
    )

    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[]),
    )
    google_metadata = types.SimpleNamespace(title="Mort")
    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[google_metadata]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider, google_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover","google"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    assert hardcover_provider.search.call_args_list == [
        mock.call("hardcover-id:379631", "", "en"),
        mock.call("Mort Terry Pratchett", "", "en"),
    ]
    google_provider.search.assert_called_once_with("Mort Terry Pratchett", "", "en")

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Metadata fetch: exact Hardcover lookup returned no results for book_id=1 hardcover-id=379631; falling back to fuzzy lookup" in message
        for message in info_messages
    )
    assert any(
        "Successfully applied metadata from Google for book: Mort" in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_logs_missing_provenance_before_fuzzy_lookup(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Mort",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[],
        identifiers=[],
    )

    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[types.SimpleNamespace(title="Mort")]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[google_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["google"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=True)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is True
    google_provider.search.assert_called_once_with("Mort Terry Pratchett", "", "en")

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Metadata fetch: no exact Hardcover provenance present for book_id=1; falling back to fuzzy lookup" in message
        for message in info_messages
    )


def test_fetch_and_apply_metadata_does_not_fallback_to_fuzzy_after_exact_resolution(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Lords and Ladies",
        authors=[types.SimpleNamespace(name="Terry Pratchett")],
        data=[types.SimpleNamespace(format="EPUB")],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
    )

    exact_result = _build_hardcover_edition_result(
        edition_id="17801818",
        title="Equal Rites",
        language="eng",
        publisher="Corgi",
        published_date="1987-01-15",
        isbn="9780552131056",
        matched_cover_url="https://covers.example/17801818.jpg",
    )
    hardcover_provider = types.SimpleNamespace(
        __id__="hardcover",
        __name__="Hardcover",
        active=True,
        search=mock.Mock(return_value=[exact_result]),
    )
    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[types.SimpleNamespace(title="Bad Fallback Metadata")]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[hardcover_provider, google_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "metadata_provider_hierarchy": '["hardcover","google"]',
            "metadata_providers_enabled": "{}",
        },
    )

    apply_metadata = mock.Mock(return_value=False)
    monkeypatch.setattr(module, "_apply_metadata_to_book", apply_metadata)

    assert module.fetch_and_apply_metadata(1) is False
    hardcover_provider.search.assert_called_once_with("hardcover-id:434155", "", "en")
    google_provider.search.assert_not_called()

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Metadata fetch: exact Hardcover metadata resolved for book_id=1 but produced no applied changes; not falling back to fuzzy lookup because exact provenance is authoritative"
        in message
        for message in info_messages
    )


def test_apply_metadata_persists_resolved_hardcover_edition_identifier(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[],
        comments=[],
        publishers=[],
        tags=[],
        series=[],
        ratings=[],
        identifiers=[
            types.SimpleNamespace(type="hardcover-id", val="434155"),
            types.SimpleNamespace(type="hardcover-slug", val="equal-rites"),
        ],
        languages=[],
    )

    google_provider = types.SimpleNamespace(
        __id__="google",
        __name__="Google",
        active=True,
        search=mock.Mock(return_value=[]),
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[google_provider],
        settings={
            "auto_metadata_fetch_enabled": True,
            "auto_metadata_update_title": False,
            "auto_metadata_update_authors": False,
            "auto_metadata_update_description": False,
            "auto_metadata_update_publisher": False,
            "auto_metadata_update_tags": False,
            "auto_metadata_update_series": False,
            "auto_metadata_update_published_date": False,
            "auto_metadata_update_rating": False,
            "auto_metadata_update_identifiers": True,
            "auto_metadata_update_cover": False,
        },
    )

    monkeypatch.setattr(
        module.db,
        "Identifiers",
        lambda value, identifier_type, book_id: types.SimpleNamespace(
            val=value,
            type=identifier_type,
            book=book_id,
        ),
    )

    session = types.SimpleNamespace(
        add=lambda *args, **kwargs: None,
        commit=lambda: None,
        rollback=lambda: None,
    )
    calibre_db_instance = types.SimpleNamespace(session=session)
    metadata = types.SimpleNamespace(
        identifiers={
            "hardcover-id": "434155",
            "hardcover-slug": "equal-rites",
            "hardcover-edition": "17801818",
        },
        source=types.SimpleNamespace(id="hardcover"),
        hardcover_preferred_edition_id="17801818",
        hardcover_preferred_edition_reason="default_ebook_edition",
    )

    assert module._apply_metadata_to_book(book, metadata, calibre_db_instance) is True
    assert any(
        identifier.type == "hardcover-edition" and identifier.val == "17801818"
        for identifier in book.identifiers
    )

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Persisted hardcover-edition=17801818 after exact Hardcover provenance resolution for book_id=1"
        in message
        for message in info_messages
    )


def test_apply_metadata_applies_exact_hardcover_cover_during_ingest(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[],
        comments=[],
        publishers=[],
        tags=[],
        series=[],
        ratings=[],
        identifiers=[],
        languages=[],
        path="Pratchett/Equal Rites (1)",
        has_cover=0,
        last_modified=None,
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[],
        settings={
            "auto_metadata_fetch_enabled": True,
            "auto_metadata_update_title": False,
            "auto_metadata_update_authors": False,
            "auto_metadata_update_description": False,
            "auto_metadata_update_publisher": False,
            "auto_metadata_update_tags": False,
            "auto_metadata_update_series": False,
            "auto_metadata_update_published_date": False,
            "auto_metadata_update_rating": False,
            "auto_metadata_update_identifiers": False,
            "auto_metadata_update_cover": True,
        },
    )

    save_cover_from_url = mock.Mock(return_value=(True, None))
    replace_cover_thumbnail_cache = mock.Mock()

    def fake_apply_selected_cover_url(**kwargs):
        kwargs["save_cover_from_url"](kwargs["cover_url"], kwargs["book_path"])
        kwargs["refresh_thumbnail_cache"](kwargs["book_id"])
        return types.SimpleNamespace(
            applied=True,
            modify_date=True,
            error=None,
            cleared_cover=False,
            normalized_cover_url=kwargs["cover_url"],
        )

    monkeypatch.setattr(
        module,
        "_load_cover_update_dependencies",
        lambda: (
            types.SimpleNamespace(
                save_cover_from_url=save_cover_from_url,
                replace_cover_thumbnail_cache=replace_cover_thumbnail_cache,
            ),
            fake_apply_selected_cover_url,
        ),
    )

    session = types.SimpleNamespace(
        add=lambda *args, **kwargs: None,
        commit=mock.Mock(),
        rollback=lambda: None,
    )
    set_metadata_dirty = mock.Mock()
    calibre_db_instance = types.SimpleNamespace(
        session=session,
        set_metadata_dirty=set_metadata_dirty,
    )
    metadata = types.SimpleNamespace(
        identifiers={},
        title="",
        authors=[],
        description="",
        publisher="",
        tags=[],
        series="",
        publishedDate="",
        source=types.SimpleNamespace(id="hardcover"),
        cover="https://covers.example/17801818.jpg",
        hardcover_cover_source="chosen edition cover",
    )

    assert module._apply_metadata_to_book(book, metadata, calibre_db_instance) is True
    assert book.has_cover == 1
    assert book.last_modified is not None
    save_cover_from_url.assert_called_once_with(
        "https://covers.example/17801818.jpg",
        "Pratchett/Equal Rites (1)",
    )
    replace_cover_thumbnail_cache.assert_called_once_with(1)
    set_metadata_dirty.assert_called_once_with(1)
    session.commit.assert_called_once()

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "Applying exact Hardcover cover during ingest for book_id=1 from chosen edition cover"
        in message
        for message in info_messages
    )
    assert any(
        "Queued cover thumbnail invalidation after exact Hardcover ingest cover update for book_id=1"
        in message
        for message in info_messages
    )


def test_apply_metadata_preserves_existing_cover_when_exact_hardcover_cover_missing(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[],
        comments=[],
        publishers=[],
        tags=[],
        series=[],
        ratings=[],
        identifiers=[],
        languages=[],
        path="Pratchett/Equal Rites (1)",
        has_cover=1,
        last_modified=None,
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[],
        settings={
            "auto_metadata_fetch_enabled": True,
            "auto_metadata_update_title": False,
            "auto_metadata_update_authors": False,
            "auto_metadata_update_description": False,
            "auto_metadata_update_publisher": False,
            "auto_metadata_update_tags": False,
            "auto_metadata_update_series": False,
            "auto_metadata_update_published_date": False,
            "auto_metadata_update_rating": False,
            "auto_metadata_update_identifiers": False,
            "auto_metadata_update_cover": True,
        },
    )

    load_cover_deps = mock.Mock()
    monkeypatch.setattr(module, "_load_cover_update_dependencies", load_cover_deps)

    session = types.SimpleNamespace(
        add=lambda *args, **kwargs: None,
        commit=mock.Mock(),
        rollback=lambda: None,
    )
    calibre_db_instance = types.SimpleNamespace(
        session=session,
        set_metadata_dirty=mock.Mock(),
    )
    metadata = types.SimpleNamespace(
        identifiers={},
        title="",
        authors=[],
        description="",
        publisher="",
        tags=[],
        series="",
        publishedDate="",
        source=types.SimpleNamespace(id="hardcover"),
        cover="",
        hardcover_cover_source="no cover resolved",
    )

    assert module._apply_metadata_to_book(book, metadata, calibre_db_instance) is False
    assert book.has_cover == 1
    assert book.last_modified is None
    load_cover_deps.assert_not_called()
    session.commit.assert_not_called()

    info_messages = _flatten_log_messages(logger_instance.info)
    assert any(
        "No safe preferred exact cover found; preserving existing/imported cover for book_id=1"
        in message
        for message in info_messages
    )


def test_apply_metadata_does_not_enable_auto_cover_for_non_hardcover_provider(monkeypatch):
    book = types.SimpleNamespace(
        id=1,
        title="Equal Rites",
        authors=[],
        comments=[],
        publishers=[],
        tags=[],
        series=[],
        ratings=[],
        identifiers=[],
        languages=[],
        path="Pratchett/Equal Rites (1)",
        has_cover=0,
        last_modified=None,
    )

    module, logger_instance = _load_metadata_helper_module(
        monkeypatch,
        book=book,
        providers=[],
        settings={
            "auto_metadata_fetch_enabled": True,
            "auto_metadata_update_title": False,
            "auto_metadata_update_authors": False,
            "auto_metadata_update_description": False,
            "auto_metadata_update_publisher": False,
            "auto_metadata_update_tags": False,
            "auto_metadata_update_series": False,
            "auto_metadata_update_published_date": False,
            "auto_metadata_update_rating": False,
            "auto_metadata_update_identifiers": False,
            "auto_metadata_update_cover": True,
        },
    )

    load_cover_deps = mock.Mock()
    monkeypatch.setattr(module, "_load_cover_update_dependencies", load_cover_deps)

    session = types.SimpleNamespace(
        add=lambda *args, **kwargs: None,
        commit=mock.Mock(),
        rollback=lambda: None,
    )
    calibre_db_instance = types.SimpleNamespace(
        session=session,
        set_metadata_dirty=mock.Mock(),
    )
    metadata = types.SimpleNamespace(
        identifiers={},
        title="",
        authors=[],
        description="",
        publisher="",
        tags=[],
        series="",
        publishedDate="",
        source=types.SimpleNamespace(id="google"),
        cover="https://covers.example/google.jpg",
    )

    assert module._apply_metadata_to_book(book, metadata, calibre_db_instance) is False
    assert book.has_cover == 0
    load_cover_deps.assert_not_called()
    session.commit.assert_not_called()
    assert _flatten_log_messages(logger_instance.info) == []
