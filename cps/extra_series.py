"""Browse additional Calibre series from the normal CWA series page."""

import re

from flask import Blueprint, abort, redirect, url_for

from . import calibre_db, constants, db
from .cw_login import current_user
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .extra_series_store import CalibreSeriesStore, KINDS, kind_label, normalize_kind


extra_series = Blueprint("extra_series", __name__, url_prefix="/additional-series")
store = CalibreSeriesStore()


@extra_series.app_context_processor
def helpers():
    def for_book(book_id):
        return store.for_book(book_id)

    return {"extra_series_for_book": for_book,
            "extra_series_groups": visible_groups,
            "extra_series_kinds": KINDS,
            "is_extra_series_column": is_extra_series_column}


def is_extra_series_column(column):
    return column.datatype == "series" and bool(re.fullmatch(
        r"(?:nova_series|nova_universe|nova_reading_order)[1-9][0-9]*|nova_custom_[0-9a-f]{16}_[1-9][0-9]*",
        column.label))


def visible_groups():
    rows = store.all_memberships()
    calibre_db.ensure_session()
    book_ids = {row["book_id"] for row in rows}
    books = (calibre_db.session.query(db.Books)
             .filter(db.Books.id.in_(book_ids))
             .filter(calibre_db.common_filters()).all()) if book_ids else []
    by_id = {book.id: book for book in books}
    groups = {}
    for row in rows:
        if row["book_id"] not in by_id:
            continue
        key = row["kind"], row["name"]
        item = groups.setdefault(key, {"kind": row["kind"], "type": kind_label(row["kind"]),
                                      "name": row["name"], "count": 0, "book": None,
                                      "first": (True, float("inf"))})
        item["count"] += 1
        order = (row["position"] is None, row["position"] if row["position"] is not None else 0)
        if order < item["first"]:
            item["first"] = order
            item["book"] = by_id[row["book_id"]]
    return sorted(groups.values(), key=lambda item: (item["name"].casefold(), item["type"].casefold()))


@extra_series.after_request
def no_cache(response):
    response.cache_control.no_store = True
    return response


@extra_series.route("/")
@login_required_if_no_ano
def index():
    return redirect(url_for("web.series_list"))


@extra_series.route("/group/<kind>/<path:name>")
@login_required_if_no_ano
def group(kind, name):
    if not current_user.check_visibility(constants.SIDEBAR_SERIES):
        abort(404)
    try:
        kind = normalize_kind(kind)
    except ValueError:
        abort(404)
    rows = store.for_group(kind, name)
    if not rows:
        abort(404)
    calibre_db.ensure_session()
    ids = [row["book_id"] for row in rows]
    books = (calibre_db.session.query(db.Books)
             .filter(db.Books.id.in_(ids))
             .filter(calibre_db.common_filters()).all())
    by_id = {book.id: book for book in books}
    members = [{"book": by_id[row["book_id"]], "position": row["position"]}
               for row in rows if row["book_id"] in by_id]
    if not members:
        abort(404)
    return render_title_template("extra_series_group.html", title=name,
                                 page="serieslist", kind=kind,
                                 name=name, members=members, kind_label=kind_label(kind))


@extra_series.route("/book/<int:book_id>")
@login_required_if_no_ano
def edit(book_id):
    if not current_user.role_admin():
        abort(403)
    book = calibre_db.get_filtered_book(book_id)
    if book is None:
        abort(404)
    return redirect(url_for("edit-book.show_edit_book", book_id=book_id))
