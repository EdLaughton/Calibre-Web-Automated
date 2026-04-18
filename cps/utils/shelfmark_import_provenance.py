from __future__ import annotations

import json
import os
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _normalize_identifier(identifier_type: Any, identifier_value: Any) -> str | None:
    normalized_type = _normalize_text(identifier_type)
    normalized_value = _normalize_text(identifier_value)
    if normalized_type is None or normalized_value is None:
        return None
    return f"{normalized_type}:{normalized_value}"


def _iter_identifier_entries(raw_identifiers: Any) -> list[str]:
    identifiers: list[str] = []
    if isinstance(raw_identifiers, Mapping):
        for identifier_type, identifier_value in raw_identifiers.items():
            normalized = _normalize_identifier(identifier_type, identifier_value)
            if normalized is not None:
                identifiers.append(normalized)
        return identifiers

    if isinstance(raw_identifiers, Sequence) and not isinstance(raw_identifiers, (str, bytes, bytearray)):
        for item in raw_identifiers:
            if isinstance(item, str):
                normalized = _normalize_text(item)
                if normalized is not None and ":" in normalized:
                    identifiers.append(normalized)
            elif isinstance(item, Mapping):
                normalized = _normalize_identifier(item.get("type"), item.get("value"))
                if normalized is not None:
                    identifiers.append(normalized)
        return identifiers

    normalized = _normalize_text(raw_identifiers)
    if normalized is not None and ":" in normalized:
        identifiers.append(normalized)
    return identifiers


def extract_import_manifest_identifiers(manifest: Mapping[str, Any] | None) -> list[str]:
    """Extract stable `calibredb --identifier` values from a CWA sidecar manifest."""
    if not isinstance(manifest, Mapping):
        return []

    ordered_identifiers: OrderedDict[str, None] = OrderedDict()

    def add_entries(raw_identifiers: Any) -> None:
        for identifier in _iter_identifier_entries(raw_identifiers):
            ordered_identifiers.setdefault(identifier, None)

    add_entries(manifest.get("identifiers"))

    provenance = manifest.get("provenance")
    if isinstance(provenance, Mapping):
        provider = _normalize_text(provenance.get("provider"))
        provider_id = _normalize_text(provenance.get("provider_id"))
        if provider == "hardcover" and provider_id is not None:
            ordered_identifiers.setdefault(f"hardcover-id:{provider_id}", None)

        explicit_hardcover_fields = (
            ("hardcover_id", "hardcover-id"),
            ("hardcover_slug", "hardcover-slug"),
            ("hardcover_edition", "hardcover-edition"),
        )
        for manifest_key, identifier_type in explicit_hardcover_fields:
            normalized = _normalize_identifier(identifier_type, provenance.get(manifest_key))
            if normalized is not None:
                ordered_identifiers.setdefault(normalized, None)

        add_entries(provenance.get("identifiers"))

    return list(ordered_identifiers.keys())


def summarize_import_manifest_identifiers(identifiers: Sequence[str] | None) -> str:
    """Return a concise log-friendly summary of extracted sidecar identifiers."""
    if not identifiers:
        return "no stable identifiers"

    interesting_types = ("hardcover-id", "hardcover-edition", "hardcover-slug")
    summary_fields: OrderedDict[str, str] = OrderedDict()
    stable_identifier_count = 0

    for identifier in identifiers:
        normalized_identifier = _normalize_text(identifier)
        if normalized_identifier is None or ":" not in normalized_identifier:
            continue
        stable_identifier_count += 1
        identifier_type, identifier_value = normalized_identifier.split(":", 1)
        normalized_type = _normalize_text(identifier_type)
        normalized_value = _normalize_text(identifier_value)
        if normalized_type in interesting_types and normalized_value is not None:
            summary_fields.setdefault(normalized_type, normalized_value)

    if summary_fields:
        return ", ".join(f"{identifier_type}={identifier_value}" for identifier_type, identifier_value in summary_fields.items())

    noun = "identifier" if stable_identifier_count == 1 else "identifiers"
    return f"{stable_identifier_count} stable {noun}"


def build_calibredb_identifier_args(identifiers: Sequence[str] | None) -> list[str]:
    args: list[str] = []
    for identifier in identifiers or []:
        normalized_identifier = _normalize_text(identifier)
        if normalized_identifier is None or ":" not in normalized_identifier:
            continue
        args.extend(["--identifier", normalized_identifier])
    return args


def load_import_manifest(manifest_path: str) -> dict[str, Any] | None:
    try:
        if not Path(manifest_path).exists():
            return None
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        return dict(manifest) if isinstance(manifest, Mapping) else None
    except Exception:
        return None


def finalize_import_manifest(manifest_path: str, success: bool) -> str | None:
    try:
        if not Path(manifest_path).exists():
            return None
        if success:
            os.remove(manifest_path)
            return None
        failed_manifest_path = manifest_path.replace(".cwa.json", ".cwa.failed.json")
        if failed_manifest_path == manifest_path:
            failed_manifest_path = manifest_path + ".failed"
        os.replace(manifest_path, failed_manifest_path)
        return failed_manifest_path
    except Exception:
        return None
