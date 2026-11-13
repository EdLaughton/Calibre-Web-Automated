"""Extra series stored in Calibre's own custom Series columns.

Each custom Series column has one value per book. More slots are provisioned
when a book needs them. No second catalogue database is used.
"""

import fcntl
import hashlib
import re
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path


KINDS = {"series": "Series", "universe": "Universe", "reading_order": "Reading order"}
PREFIX = {"series": "nova_series", "universe": "nova_universe", "reading_order": "nova_reading_order"}
LABEL = {"series": "Additional Series", "universe": "Universe", "reading_order": "Reading Order"}
CUSTOM_COLUMN = re.compile(r"nova_custom_([0-9a-f]{16})_([1-9][0-9]*)$")
CUSTOM_NAME = re.compile(r"Nova custom: (.+) \(([1-9][0-9]*)\)$")


def normalize_kind(kind):
    if not isinstance(kind, str):
        raise ValueError("Choose a valid series type")
    if kind in KINDS:
        return kind
    if not kind.startswith("custom:"):
        raise ValueError("Choose a valid series type")
    name = " ".join(kind[7:].split())
    if (not name or len(name) > 40 or
            not re.fullmatch(r"[\w &'’().,-]+", name, re.UNICODE) or
            name.casefold() in {label.casefold() for label in KINDS.values()}):
        raise ValueError("Custom type must be 1 to 40 letters, numbers or simple punctuation")
    return "custom:" + name


def kind_label(kind):
    return KINDS.get(kind, kind[7:] if kind.startswith("custom:") else kind)


def custom_hash(kind):
    return hashlib.sha256(kind.casefold().encode("utf-8")).hexdigest()[:16]


class CalibreSeriesStore:
    def __init__(self, library=None, lock=None):
        if library is None:
            from . import config
            library = config.get_book_path()
        self.library = Path(library)
        self.database = self.library / "metadata.db"
        # Keep the lock outside the library: Calibre may move or replace its files.
        self.lock = Path(lock) if lock else Path(tempfile.gettempdir()) / (
            "cwa-extra-series-" + hashlib.sha256(str(self.library.resolve()).encode()).hexdigest()[:16] + ".lock")

    @contextmanager
    def connect(self, readonly=True):
        if readonly:
            connection = sqlite3.connect(self.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        else:
            connection = sqlite3.connect(str(self.database), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            if not readonly:
                connection.commit()
        except Exception:
            if not readonly:
                connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def writer_lock(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def validate(kind, name, position):
        kind = normalize_kind(kind)
        name = " ".join(str(name).split())
        if not name or len(name) > 120 or re.search(r"\[[0-9.]+\]$", name):
            raise ValueError("Name must be 1 to 120 characters and cannot end in a number in brackets")
        if position is None or not str(position).strip():
            return kind, name, None
        try:
            number = Decimal(str(position).strip())
        except (InvalidOperation, ValueError):
            raise ValueError("Enter a numeric position")
        if not number.is_finite() or number < 0 or number > 100000 or -number.as_tuple().exponent > 3:
            raise ValueError("Position must be 0–100000 with at most three decimal places")
        return kind, name, format(number.normalize(), "f")

    def columns(self, connection):
        rows = connection.execute("SELECT id,label,name,datatype FROM custom_columns WHERE datatype='series'").fetchall()
        result = []
        for row in rows:
            matched = False
            for kind, prefix in PREFIX.items():
                match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)", row["label"])
                if match:
                    result.append({"id": row["id"], "label": row["label"], "kind": kind,
                                   "slot": int(match.group(1))})
                    matched = True
                    break
            if matched:
                continue
            match = CUSTOM_COLUMN.fullmatch(row["label"])
            display = CUSTOM_NAME.fullmatch(row["name"])
            if match and display:
                try:
                    kind = normalize_kind("custom:" + display.group(1))
                except ValueError:
                    continue
                if (match.group(1) == custom_hash(kind) and
                        int(match.group(2)) == int(display.group(2))):
                    result.append({"id": row["id"], "label": row["label"], "kind": kind,
                                   "slot": int(match.group(2))})
        return sorted(result, key=lambda item: (item["kind"], item["slot"]))

    def _memberships(self, book_id=None):
        result = []
        with self.connect() as connection:
            for column in self.columns(connection):
                table = "custom_column_%d" % column["id"]
                link = "books_custom_column_%d_link" % column["id"]
                query = "SELECT l.book, v.value, l.extra FROM %s l JOIN %s v ON v.id=l.value" % (link, table)
                params = ()
                if book_id is not None:
                    query += " WHERE l.book=?"
                    params = (book_id,)
                for row in connection.execute(query, params):
                    result.append({"book_id": row["book"], "kind": column["kind"],
                                   "name": row["value"], "position": row["extra"],
                                   "column": column["label"]})
        return result

    def all_memberships(self):
        return self._memberships()

    def for_book(self, book_id):
        return sorted(self._memberships(book_id),
                      key=lambda row: (row["kind"], row["name"].casefold()))

    def for_group(self, kind, name):
        kind = normalize_kind(kind)
        return sorted((row for row in self.all_memberships()
                       if row["kind"].casefold() == kind.casefold() and row["name"].casefold() == name.casefold()),
                      key=lambda row: (row["position"] is None,
                                       row["position"] if row["position"] is not None else 0,
                                       row["book_id"]))

    def _calibredb(self, *arguments):
        try:
            result = subprocess.run(["calibredb", *arguments, "--with-library", str(self.library)],
                                    capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("Calibre could not save the series change") from error
        if result.returncode:
            raise RuntimeError("Calibre could not save the series change")

    def _create_slot(self, kind, number):
        if kind in KINDS:
            label = PREFIX[kind] + str(number)
            title = LABEL[kind] + " " + str(number)
        else:
            label = "nova_custom_" + custom_hash(kind) + "_" + str(number)
            title = "Nova custom: " + kind[7:] + " (" + str(number) + ")"
        self._calibredb("add_custom_column", label, title, "series")
        return label

    def _write_slot(self, book_id, label, name, position):
        value = name + " [" + (position if position is not None else "0") + "]"
        self._calibredb("set_custom", label, str(book_id), value)
        if position is None:
            with self.connect(False) as connection:
                column = next((c for c in self.columns(connection) if c["label"] == label), None)
                if column is None:
                    raise RuntimeError("Calibre series column disappeared during save")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE books_custom_column_%d_link SET extra=NULL WHERE book=?" % column["id"],
                                   (book_id,))
        current = next((row for row in self.for_book(book_id) if row["column"] == label), None)
        expected = None if position is None else float(position)
        if (current is not None and current["name"] == name and position is not None
                and current["position"] != expected):
            # Calibre can initialize an occupied Series slot at 1 when its name
            # changes; a second native setter call applies the requested index.
            self._calibredb("set_custom", label, str(book_id), value)
            current = next((row for row in self.for_book(book_id) if row["column"] == label), None)
        return current

    def set_membership(self, book_id, kind, name, position):
        kind, name, position = self.validate(kind, name, position)
        with self.writer_lock():
            if kind.startswith("custom:"):
                with self.connect() as connection:
                    kind = next((column["kind"] for column in self.columns(connection)
                                 if column["kind"].casefold() == kind.casefold()), kind)
            existing = self.for_book(book_id)
            same = [r for r in existing if r["kind"] == kind and r["name"].casefold() == name.casefold()]
            if len(same) > 1:
                raise RuntimeError("Duplicate existing series membership needs review")
            if same:
                label = same[0]["column"]
            else:
                with self.connect() as connection:
                    slots = [c for c in self.columns(connection) if c["kind"] == kind]
                used = {r["column"] for r in existing}
                available = next((c for c in slots if c["label"] not in used), None)
                label = available["label"] if available else self._create_slot(
                    kind, max((c["slot"] for c in slots), default=0) + 1)
            current = self._write_slot(book_id, label, name, position)
            if (current is None or current["name"] != name or
                    current["position"] != (None if position is None else float(position))):
                raise RuntimeError("Calibre series readback failed")

    def replace_membership(self, book_id, old_kind, old_name, kind, name, position):
        """Rename or renumber within the same type without allocating another column."""
        kind, name, position = self.validate(kind, name, position)
        if old_kind.casefold() != kind.casefold():
            raise ValueError("Series type changed; use add and remove")
        with self.writer_lock():
            existing = self.for_book(book_id)
            found = [row for row in existing if row["kind"].casefold() == old_kind.casefold()
                     and row["name"].casefold() == old_name.casefold()]
            if len(found) != 1:
                raise ValueError("Series changed since this page loaded")
            if any(row["column"] != found[0]["column"] and row["kind"].casefold() == kind.casefold()
                   and row["name"].casefold() == name.casefold() for row in existing):
                raise ValueError("That additional series is already assigned to this book")
            current = self._write_slot(book_id, found[0]["column"], name, position)
            if (current is None or current["name"] != name or
                    current["position"] != (None if position is None else float(position))):
                raise RuntimeError("Calibre series readback failed")

    def remove_membership(self, book_id, kind, name):
        with self.writer_lock():
            found = [r for r in self.for_book(book_id)
                     if r["kind"] == kind and r["name"].casefold() == name.casefold()]
            if len(found) != 1:
                raise ValueError("Series membership not found")
            self._calibredb("set_custom", found[0]["column"], str(book_id), "")
            if any(r["kind"] == kind and r["name"].casefold() == name.casefold()
                   for r in self.for_book(book_id)):
                raise RuntimeError("Series membership removal did not verify")
