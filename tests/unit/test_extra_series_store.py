"""Read additional series from Calibre custom columns without a second DB."""

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


def load_store():
    source = Path(__file__).resolve().parents[2] / "cps" / "extra_series_store.py"
    spec = importlib.util.spec_from_file_location("extra_series_store_test", source)
    module = importlib.util.module_from_spec(spec)
    # Windows development hosts lack fcntl; these read tests never take a lock.
    with patch.dict(sys.modules, {"fcntl": sys.modules.get("fcntl", types.ModuleType("fcntl"))}):
        spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_custom_series_columns_are_read_with_independent_positions(tmp_path):
    module = load_store()
    library = tmp_path / "books #1"
    library.mkdir()
    database = library / "metadata.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE custom_columns (id INTEGER, label TEXT, name TEXT, datatype TEXT);
            CREATE TABLE custom_column_1 (id INTEGER, value TEXT);
            CREATE TABLE books_custom_column_1_link (book INTEGER, value INTEGER, extra REAL);
            CREATE TABLE custom_column_2 (id INTEGER, value TEXT);
            CREATE TABLE books_custom_column_2_link (book INTEGER, value INTEGER, extra REAL);
            INSERT INTO custom_columns VALUES (1, 'nova_universe1', 'Universe', 'series');
            INSERT INTO custom_columns VALUES (2, 'nova_reading_order1', 'Reading order', 'series');
            INSERT INTO custom_column_1 VALUES (10, 'Cosmere');
            INSERT INTO books_custom_column_1_link VALUES (19, 10, NULL);
            INSERT INTO books_custom_column_1_link VALUES (20, 10, 36.0);
            INSERT INTO custom_column_2 VALUES (11, 'Publication order');
            INSERT INTO books_custom_column_2_link VALUES (19, 11, 3.5);
        """)
    store = module.CalibreSeriesStore(library)
    assert [(row["kind"], row["name"], row["position"]) for row in store.for_book(19)] == [
        ("reading_order", "Publication order", 3.5),
        ("universe", "Cosmere", None),
    ]
    assert [row["book_id"] for row in store.for_group("universe", "Cosmere")] == [20, 19]
    assert len(store.all_memberships()) == 3


@pytest.mark.unit
def test_custom_type_and_position_validation():
    module = load_store()
    assert module.CalibreSeriesStore.validate("custom:Publication path", "  Way of Kings  ", "2.500") == (
        "custom:Publication path", "Way of Kings", "2.5")
    for kind, name, position in (("custom:", "Book", None),
                                 ("universe", "Book [1]", None),
                                 ("series", "Book", "NaN"),
                                 ("series", "Book", "1.2345")):
        with pytest.raises(ValueError):
            module.CalibreSeriesStore.validate(kind, name, position)
