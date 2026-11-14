"""CWA reader-facing discovery and durable request intake."""

import json
import os
import time
from contextlib import closing
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, redirect, request, url_for
from flask_wtf.csrf import validate_csrf
from itsdangerous import BadData, URLSafeTimedSerializer
from wtforms.validators import ValidationError

from . import calibre_db, config, ub
from .book_reader_store import ACTIVE, DELIVERIES, QUEUE, hardcover, kindle_address, open_queue, owned
from .cw_login import current_user, login_required


requests_ui = Blueprint("nova_reader_requests", __name__, url_prefix="/book-requests")
CONFIG = QUEUE.parent
ADMIN_PAGE_SIZE = 20
STATUS_LABELS = {
    "owned": "Already in the library",
    "queued": "Queued",
    "searching": "Searching for an EPUB",
    "submitting": "Sending to Bookshelf",
    "downloading": "Downloading",
    "checking": "Checking the download",
    "waiting_release": "Waiting for release",
    "waiting_epub": "Watching for an EPUB",
    "imported": "Added to the library",
    "no_match": "No suitable EPUB found",
    "excluded": "Unavailable for automatic requests",
    "held": "Needs review",
    "dismissed": "Closed by an administrator",
}
SEARCH_QUERY = """
query($query: String!) {
  search(query: $query, query_type: "Book", per_page: 10) { results }
}
"""
SERIES_SEARCH_QUERY = """
query($query: String!) {
  search(query: $query, query_type: "Series", per_page: 10) { results }
}
"""
SERIES_BOOKS_QUERY = """
query($id: Int!) {
  series_by_pk(id: $id) {
    id name
    book_series(limit: 301, order_by: {position: asc}) {
      position compilation
      book { id title canonical_id release_year
        contributions { contribution author { name } } }
    }
    book_series_aggregate { aggregate { count } }
  }
}
"""


def search_ticket():
    return URLSafeTimedSerializer(current_app.secret_key, salt="nova-reader-work-search")


def series_ticket():
    return URLSafeTimedSerializer(current_app.secret_key, salt="nova-reader-series-request")


def library_book_url(match):
    if match is None:
        return None
    book_id = match[0]
    if calibre_db.get_book_read_archived(book_id, config.config_read_column, allow_show_archived=True):
        return url_for("web.show_book", book_id=book_id)
    return None


def can_send_to_kindle():
    return bool(current_user.role_download() and kindle_address(current_user.kindle_mail)
                and current_user.filter_language() == "all"
                and current_user.list_allowed_tags() == [''] and current_user.list_denied_tags() == ['']
                and not config.config_restricted_column)


def enabled_for_reader():
    if not current_user.is_authenticated or not (CONFIG / "reader-requests.enabled").is_file():
        return False
    pilot = CONFIG / "request-pilot.json"
    return not pilot.is_file() or str(json.loads(pilot.read_text())["reader"]) == str(current_user.get_id())


@requests_ui.app_context_processor
def request_navigation():
    return {"nova_reader_request_enabled": enabled_for_reader,
            "manual_book_search_url": os.environ.get("CWA_BOOK_REQUEST_MANUAL_URL", "")}


@requests_ui.before_request
def require_enabled_reader():
    if (CONFIG / "reader-requests.enabled").is_file() and not current_user.is_authenticated:
        login_url = url_for("web.login", next=url_for("nova_reader_requests.page"))
        if request.endpoint in ("nova_reader_requests.page", "nova_reader_requests.admin"):
            return redirect(url_for("web.login", next=request.full_path.rstrip("?")))
        return jsonify(error="Your session expired. Sign in to continue.", login_url=login_url), 401
    if not enabled_for_reader():
        abort(404)


@requests_ui.after_request
def private_response(response):
    response.cache_control.no_store = True
    return response


@lru_cache(maxsize=128)
def search_catalogue(term, time_bucket):
    result = hardcover(SEARCH_QUERY, {"query": term})["search"]["results"]
    if isinstance(result, str):
        result = json.loads(result)
    matches = {}
    for hit in (result or {}).get("hits", []):
        doc = hit.get("document", {})
        work = str(doc.get("id", ""))
        canonical = doc.get("canonical_id")
        if not work.isascii() or not work.isdecimal() or canonical not in (None, "", int(work), work):
            continue
        authors = [author for author in doc.get("author_names", []) if isinstance(author, str)]
        if not doc.get("title") or not authors:
            continue
        image = (doc.get("image") or {}).get("url") or ""
        cover = urlsplit(image)
        featured = doc.get("featured_series") or {}
        series = (featured.get("series") or {}).get("name")
        position = featured.get("position")
        release_date = doc.get("release_date")
        matches[int(work)] = {
            "work": int(work),
            "title": doc["title"],
            "authors": authors,
            "year": doc.get("release_year"),
            "cover_url": image if cover.scheme == "https" and cover.netloc == "assets.hardcover.app" else None,
            "series": series,
            "position": position,
            "release_date": release_date if release_date and release_date > date.today().isoformat() else None,
        }
    return list(matches.values())


def series_members(series_id):
    series = hardcover(SERIES_BOOKS_QUERY, {"id": series_id})["series_by_pk"]
    if not series or len(series["book_series"]) > 300:
        return None
    total = ((series.get("book_series_aggregate") or {}).get("aggregate") or {}).get("count")
    if total is not None and total > 300:
        return None
    books = []
    seen = set()
    for membership in series["book_series"]:
        book = membership.get("book") or {}
        work = book.get("id")
        if type(work) is not int or work in seen or book.get("canonical_id") not in (None, work):
            continue
        authors = list(dict.fromkeys(
            row["author"]["name"] for row in book.get("contributions", [])
            if row.get("author") and (row.get("contribution") or "").casefold()
            in {"", "author", "writer", "author/illustrator"}
        ))
        if not book.get("title") or not authors:
            continue
        seen.add(work)
        books.append({"work": work, "title": book["title"], "authors": authors,
                      "position": membership.get("position"), "owned": bool(owned(work)),
                      "compilation": bool(membership.get("compilation"))})
    return {"id": series["id"], "name": series["name"], "books": books}


@requests_ui.get("/")
@login_required
def page():
    from .render_template import render_title_template

    return render_title_template("nova_reader_requests.html", title="Request a book", page="nova_reader_requests")


@requests_ui.get("/admin")
@login_required
def admin():
    if not current_user.role_admin():
        abort(403)
    from .render_template import render_title_template

    state = request.args.get("state", "")
    person = request.args.get("person", "", type=str)
    if state and state not in STATUS_LABELS:
        abort(400)
    with closing(open_queue()) as db:
        people = [dict(id=row[0], name=row[1]) for row in
                  ub.session.query(ub.User.id, ub.User.name).order_by(ub.User.name).all()]
        if person and (not person.isdecimal() or int(person) not in {row["id"] for row in people}):
            abort(400)
        person_id = int(person) if person else None
        counts = dict(db.execute(
            "SELECT j.state,COUNT(*) FROM jobs j WHERE (? IS NULL OR EXISTS "
            "(SELECT 1 FROM readers r WHERE r.work=j.work AND r.reader=?)) GROUP BY j.state",
            (person_id, person_id),
        ).fetchall())
        total = counts.get(state, 0) if state else sum(counts.values())
        last_page = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        page_number = min(last_page, max(1, request.args.get("page", 1, type=int)))
        jobs = [dict(row) for row in db.execute(
            "SELECT j.work,j.title,j.authors,j.state,j.updated,j.book_id,j.release_title,"
            "j.protocol,j.indexer,j.size_bytes,j.format,j.review_reason,s.release_date,s.next_check "
            "FROM jobs j LEFT JOIN request_releases s USING(work) "
            "WHERE (?='' OR j.state=?) AND (? IS NULL OR EXISTS "
            "(SELECT 1 FROM readers r WHERE r.work=j.work AND r.reader=?)) "
            "ORDER BY j.updated DESC,j.work DESC LIMIT ? OFFSET ?",
            (state, state, person_id, person_id, ADMIN_PAGE_SIZE, (page_number - 1) * ADMIN_PAGE_SIZE),
        )]
        reader_ids = set()
        for job in jobs:
            job["readers"] = list(db.execute(
                "SELECT r.reader,n.state AS notice,k.state AS kindle FROM readers r "
                "LEFT JOIN request_notices n ON n.work=r.work AND n.reader=r.reader "
                "LEFT JOIN request_kindles k ON k.work=r.work AND k.reader=r.reader "
                "WHERE r.work=? ORDER BY r.reader", (job["work"],),
            ))
            reader_ids.update(row["reader"] for row in job["readers"])
            alert = db.execute("SELECT status FROM request_admin_alerts WHERE work=? "
                               "ORDER BY id DESC LIMIT 1", (job["work"],)).fetchone()
            job["alert"] = alert["status"] if alert else None
            job["book_url"] = library_book_url(owned(job["work"])) if job["state"] in ("owned", "imported") else None
    names = dict(ub.session.query(ub.User.id, ub.User.name).filter(ub.User.id.in_(reader_ids)).all()) if reader_ids else {}
    return render_title_template(
        "nova_reader_requests.html", title="All book requests", page="nova_reader_requests",
        admin_view=True, request_jobs=jobs, reader_names=names, status_labels=STATUS_LABELS,
        state_filter=state, person_filter=person, people=people, counts=counts, total=total,
        page_number=page_number, last_page=last_page,
        format_request_time=lambda value: datetime.fromtimestamp(value, timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
    )


@requests_ui.get("/search")
@login_required
def search():
    term = " ".join(request.args.get("q", "").split())
    if not 3 <= len(term) <= 100:
        return jsonify(results=[])
    try:
        matches = search_catalogue(term.casefold(), int(time.time()) // 120)
    except (OSError, RuntimeError, ValueError, KeyError):
        return jsonify(error="Hardcover search is temporarily unavailable."), 503
    reader = current_user.get_id()
    signer = search_ticket()
    pilot = CONFIG / "request-pilot.json"
    pilot_work = json.loads(pilot.read_text())["work"] if pilot.is_file() else None
    results = []
    for row in matches:
        match = owned(row["work"])
        ticket = signer.dumps([reader, row["work"], row["title"], row["authors"]]) if pilot_work in (None, row["work"]) else None
        results.append(dict(row, owned=bool(match), book_url=library_book_url(match), ticket=ticket))
    return jsonify(results=results)


@requests_ui.get("/series/search")
@login_required
def series_search():
    term = " ".join(request.args.get("q", "").split())
    if not 3 <= len(term) <= 100:
        return jsonify(results=[])
    try:
        result = hardcover(SERIES_SEARCH_QUERY, {"query": term})["search"]["results"]
        if isinstance(result, str):
            result = json.loads(result)
        rows = [hit.get("document") or {} for hit in (result or {}).get("hits", [])]
    except (OSError, RuntimeError, ValueError, KeyError):
        return jsonify(error="Hardcover series search is temporarily unavailable."), 503
    return jsonify(results=[{"id": int(row["id"]), "name": row["name"],
                             "count": row.get("primary_books_count")}
                            for row in rows if str(row.get("id", "")).isdecimal() and row.get("name")])


@requests_ui.get("/series/preview")
@login_required
def series_preview():
    series_id = request.args.get("id", type=int)
    if series_id is None or series_id <= 0:
        abort(400)
    try:
        series = series_members(series_id)
    except (OSError, RuntimeError, ValueError, KeyError):
        return jsonify(error="The series could not be checked right now."), 503
    if series is None:
        return jsonify(error="This series has more than 300 entries or is unavailable for automatic requests."), 422
    series["ticket"] = series_ticket().dumps([current_user.get_id(), series_id,
                                              [book["work"] for book in series["books"]]])
    return jsonify(series=series)


@requests_ui.post("/series/request")
@login_required
def series_request():
    try:
        validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError:
        abort(400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("ticket"), str):
        abort(400)
    try:
        ticket_reader, series_id, works = series_ticket().loads(payload["ticket"], max_age=900)
    except (BadData, ValueError):
        abort(400)
    if str(ticket_reader) != str(current_user.get_id()) or type(series_id) is not int:
        abort(403)
    if not isinstance(works, list) or len(works) > 300 or any(type(work) is not int for work in works):
        abort(400)
    try:
        series = series_members(series_id)
    except (OSError, RuntimeError, ValueError, KeyError):
        return jsonify(error="The series could not be checked right now."), 503
    if series is None or [book["work"] for book in series["books"]] != works:
        return jsonify(error="The series changed. Preview it again before requesting books."), 409
    reader = int(current_user.get_id())
    added = []
    remaining = 0
    with closing(open_queue()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        pending = db.execute(
            "SELECT COUNT(*) FROM readers JOIN jobs USING(work) WHERE reader=? "
            f"AND state IN ({','.join('?' for _ in ACTIVE)})", (reader, *ACTIVE),
        ).fetchone()[0]
        for book in series["books"]:
            if book["owned"] or book["compilation"]:
                continue
            if db.execute("SELECT 1 FROM readers WHERE work=? AND reader=?",
                          (book["work"], reader)).fetchone():
                continue
            if pending >= 5:
                remaining += 1
                continue
            db.execute("INSERT OR IGNORE INTO jobs(work,title,authors,state,updated) "
                       "VALUES(?,?,?,'queued',?)",
                       (book["work"], book["title"], ", ".join(book["authors"]), int(time.time())))
            db.execute("INSERT OR IGNORE INTO readers VALUES(?,?)", (book["work"], reader))
            added.append(book["work"])
            new_state = db.execute("SELECT state FROM jobs WHERE work=?", (book["work"],)).fetchone()[0]
            pending += new_state in ACTIVE
    return jsonify(queued=added, remaining=remaining, limit=5)


@requests_ui.route("/jobs", methods=["GET", "POST"])
@login_required
def jobs():
    reader = int(current_user.get_id())
    with closing(open_queue()) as db:
        if request.method == "GET":
            rows = db.execute(
                "SELECT j.work,j.title,j.authors,j.state,n.state AS notice,k.state AS kindle,s.release_date "
                "FROM jobs j JOIN readers r USING(work) "
                "LEFT JOIN request_notices n ON n.work=j.work AND n.reader=r.reader "
                "LEFT JOIN request_kindles k ON k.work=j.work AND k.reader=r.reader "
                "LEFT JOIN request_releases s ON s.work=j.work "
                "WHERE r.reader=? ORDER BY j.updated DESC LIMIT 30",
                (reader,),
            )
            return jsonify(can_notify=bool(current_user.email), can_kindle=can_send_to_kindle(), jobs=[
                dict(row, book_url=library_book_url(owned(row["work"])))
                if row["state"] in ("owned", "imported") else dict(row)
                for row in rows
            ])
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            abort(400)
        payload = request.get_json(silent=True) or {}
        ticket = payload.get("ticket") if isinstance(payload, dict) else None
        if not isinstance(ticket, str) or len(ticket) > 2048:
            abort(400)
        try:
            ticket_reader, work, title, authors = search_ticket().loads(ticket, max_age=900)
        except (BadData, ValueError):
            abort(400)
        if (type(work) is not int or not isinstance(title, str) or len(title) > 300
                or not isinstance(authors, list) or len(authors) > 8
                or any(not isinstance(author, str) or len(author) > 200 for author in authors)):
            abort(400)
        if str(ticket_reader) != str(reader):
            abort(403)
        pilot = CONFIG / "request-pilot.json"
        if pilot.is_file() and json.loads(pilot.read_text())["work"] != work:
            abort(403)
        match = owned(work)
        if match:
            return jsonify(state="owned", book_url=library_book_url(match))
        with db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT COUNT(*) FROM readers JOIN jobs USING(work) WHERE reader=? "
                f"AND state IN ({','.join('?' for _ in ACTIVE)})",
                (reader, *ACTIVE),
            ).fetchone()[0]
            followed = db.execute("SELECT 1 FROM readers WHERE work=? AND reader=?", (work, reader)).fetchone()
            if pending >= 5 and not followed:
                return jsonify(error="You already have five active requests."), 429
            db.execute(
                "INSERT OR IGNORE INTO jobs(work,title,authors,state,updated) VALUES(?,?,?,'queued',?)",
                (work, title, ", ".join(authors), int(time.time())),
            )
            db.execute("INSERT OR IGNORE INTO readers VALUES(?,?)", (work, reader))
            state = db.execute("SELECT state FROM jobs WHERE work=?", (work,)).fetchone()[0]
        return jsonify(state=state)


@requests_ui.post("/notify")
@login_required
def notify():
    try:
        validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError:
        abort(400)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get("work")) is not int or type(data.get("enabled")) is not bool:
        abort(400)
    kind = data.get("kind", "email")
    if not isinstance(kind, str) or kind not in DELIVERIES:
        abort(400)
    table = DELIVERIES[kind]
    if data["enabled"]:
        if kind == "kindle" and not can_send_to_kindle():
            return jsonify(error="Kindle delivery requires download access and a Kindle address in your CWA profile."), 403
        if kind == "email" and not current_user.email:
            return jsonify(error="Add an email address to your CWA profile first."), 400
    reader = int(current_user.get_id())
    with closing(open_queue()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(
            "SELECT j.state FROM jobs j JOIN readers r USING(work) WHERE r.work=? AND r.reader=?",
            (data["work"], reader),
        ).fetchone()
        if job is None:
            abort(404)
        if data["enabled"]:
            if job["state"] not in ACTIVE:
                return jsonify(error="This request is no longer active."), 409
            db.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?,'pending')", (data["work"], reader))
        else:
            db.execute(f"DELETE FROM {table} WHERE work=? AND reader=? AND state='pending'", (data["work"], reader))
    return jsonify(ok=True)


@requests_ui.post("/admin/action")
@login_required
def admin_action():
    if not current_user.role_admin():
        abort(403)
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400)
    work = request.form.get("work", "")
    action = request.form.get("action", "")
    if not work.isdecimal() or action not in ("retry", "dismiss"):
        abort(400)
    work_id = int(work)
    with closing(open_queue()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state FROM jobs WHERE work=?", (work_id,)).fetchone()
        if row is None:
            abort(404)
        if row["state"] != "held":
            abort(409)
        next_state = "queued" if action == "retry" else "dismissed"
        db.execute("UPDATE jobs SET state=?,updated=? WHERE work=? AND state='held'",
                   (next_state, int(time.time()), work_id))
        db.execute("INSERT INTO request_admin_actions(work,admin,action,previous_state,created) "
                   "VALUES(?,? ,?,'held',?)",
                   (work_id, int(current_user.get_id()), action, int(time.time())))
    return redirect(url_for("nova_reader_requests.admin", state=request.form.get("state", ""),
                            person=request.form.get("person", "")), code=303)
