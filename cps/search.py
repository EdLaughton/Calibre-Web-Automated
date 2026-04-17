# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
from datetime import datetime

from flask import Blueprint, request, redirect, render_template, url_for, flash, jsonify
from flask import session as flask_session
from .cw_login import current_user
from flask_babel import format_date
from flask_babel import gettext as _
from sqlalchemy.sql.expression import func, not_, and_, or_, text, true
from sqlalchemy.sql.functions import coalesce

from . import logger, db, calibre_db, config, ub
from .string_helper import strip_whitespaces
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .pagination import Pagination
from .services.shelfmark_search import (
    DEFAULT_SHELFMARK_FILTER_HAS_COVER,
    DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
    DEFAULT_SHELFMARK_SERIES_FILTER,
    ShelfmarkIntegrationError,
    build_shelfmark_advanced_query,
    fetch_shelfmark_detail,
    get_shelfmark_preferred_release_settings,
    lookup_visible_library_matches,
    result_matches_shelfmark_filters,
    search_shelfmark_results,
)
from .services.search_autocomplete import get_autocomplete_payload


search = Blueprint('search', __name__)

log = logger.create()

SHELFMARK_TRANSIENT_QUERY_KEYS = (
    "shelfmark_detail_provider",
    "shelfmark_detail_id",
    "shelfmark_filter_high_confidence",
    "shelfmark_triage_filter",
)


@search.route("/search", methods=["GET"])
@login_required_if_no_ano
def simple_search():
    term = request.args.get("query")
    if term:
        # Track search activity
        if current_user.is_authenticated:
            try:
                from scripts.cwa_db import CWA_DB
                cwa_db = CWA_DB()
                cwa_db.log_activity(
                    user_id=int(current_user.id),
                    user_name=current_user.name,
                    event_type='SEARCH',
                    extra_data=term[:100]  # Limit search term length
                )
            except Exception as e:
                log.debug(f"Failed to log search activity: {e}")
        return redirect(url_for('web.books_list', data="search", sort_param='stored', query=term.strip()))
    else:
        return render_title_template('search.html',
                                     searchterm="",
                                     result_count=0,
                                     title=_("Search"),
                                     page="search")


@search.route("/search/autocomplete", methods=["GET"])
@login_required_if_no_ano
def autocomplete():
    labels = {
        "book": _("Book"),
        "author": _("Author"),
        "series": _("Series"),
        "show_all": _('Show all results for "%(query)s"'),
        "author_count_singular": _("1 book"),
        "author_count_plural": _("%(count)d books"),
        "series_count_singular": _("1 book"),
        "series_count_plural": _("%(count)d books"),
    }
    return jsonify(get_autocomplete_payload(request.args.get("q"), labels))


@search.route("/advsearch", methods=['POST'])
@login_required_if_no_ano
def advanced_search():
    values = dict(request.form)
    params = ['include_tag', 'exclude_tag', 'include_serie', 'exclude_serie', 'include_shelf', 'exclude_shelf',
              'include_language', 'exclude_language', 'include_extension', 'exclude_extension']
    for param in params:
        values[param] = list(request.form.getlist(param))
    flask_session['query'] = json.dumps(values)
    return redirect(url_for('web.books_list', data="advsearch", sort_param='stored', query=""))


@search.route("/advsearch", methods=['GET'])
@login_required_if_no_ano
def advanced_search_form():
    # Build custom columns names
    cc = calibre_db.get_cc_columns(config, filter_config_custom_read=True)
    return render_prepare_search_form(cc)


def adv_search_custom_columns(cc, term, q):
    for c in cc:
        if c.datatype == "datetime":
            custom_start = term.get('custom_column_' + str(c.id) + '_start')
            custom_end = term.get('custom_column_' + str(c.id) + '_end')
            if custom_start:
                q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                    func.datetime(db.cc_classes[c.id].value) >= func.datetime(custom_start)))
            if custom_end:
                q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                    func.datetime(db.cc_classes[c.id].value) <= func.datetime(custom_end)))
        elif c.datatype in ["int", "float"]:
            custom_low = term.get('custom_column_' + str(c.id) + '_low')
            custom_high = term.get('custom_column_' + str(c.id) + '_high')
            if custom_low:
                q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                    db.cc_classes[c.id].value >= custom_low))
            if custom_high:
                q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                    db.cc_classes[c.id].value <= custom_high))
        else:
            custom_query = term.get('custom_column_' + str(c.id))
            if c.datatype == 'bool':
                if custom_query != "Any":
                    if custom_query == "":
                        q = q.filter(~getattr(db.Books, 'custom_column_' + str(c.id)).
                                     any(db.cc_classes[c.id].value >= 0))
                    else:
                        q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                            db.cc_classes[c.id].value == bool(custom_query == "True")))
            elif custom_query != '' and custom_query is not None:
                if c.datatype == 'rating':
                    q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                        db.cc_classes[c.id].value == int(float(custom_query) * 2)))
                else:
                    q = q.filter(getattr(db.Books, 'custom_column_' + str(c.id)).any(
                        func.lower(db.cc_classes[c.id].value).ilike("%" + custom_query + "%")))
    return q


def adv_search_language(q, include_languages_inputs, exclude_languages_inputs):
    if current_user.filter_language() != "all":
        q = q.filter(db.Books.languages.any(db.Languages.lang_code == current_user.filter_language()))
    else:
        for language in include_languages_inputs:
            q = q.filter(db.Books.languages.any(db.Languages.id == language))
        for language in exclude_languages_inputs:
            q = q.filter(not_(db.Books.series.any(db.Languages.id == language)))
    return q


def adv_search_ratings(q, rating_high, rating_low):
    if rating_high:
        rating_high = int(rating_high) * 2
        q = q.filter(db.Books.ratings.any(db.Ratings.rating <= rating_high))
    if rating_low:
        rating_low = int(rating_low) * 2
        q = q.filter(db.Books.ratings.any(db.Ratings.rating >= rating_low))
    return q


def adv_search_read_status(read_status):
    if not config.config_read_column:
        if read_status == "True":
            db_filter = and_(ub.ReadBook.user_id == int(current_user.id),
                             ub.ReadBook.read_status == ub.ReadBook.STATUS_FINISHED)
        else:
            db_filter = coalesce(ub.ReadBook.read_status, 0) != ub.ReadBook.STATUS_FINISHED
    else:
        try:
            if read_status == "":
                db_filter = coalesce(db.cc_classes[config.config_read_column].value, 2) == 2
            else:
                db_filter = db.cc_classes[config.config_read_column].value == bool(read_status == "True")
        except (KeyError, AttributeError, IndexError):
            log.error("Custom Column No.{} does not exist in calibre database".format(config.config_read_column))
            flash(_("Custom Column No.%(column)d does not exist in calibre database",
                    column=config.config_read_column),
                  category="error")
            return true()
    return db_filter


def adv_search_extension(q, include_extension_inputs, exclude_extension_inputs):
    for extension in include_extension_inputs:
        q = q.filter(db.Books.data.any(db.Data.format == extension))
    for extension in exclude_extension_inputs:
        q = q.filter(not_(db.Books.data.any(db.Data.format == extension)))
    return q


def adv_search_tag(q, include_tag_inputs, exclude_tag_inputs):
    for tag in include_tag_inputs:
        q = q.filter(db.Books.tags.any(db.Tags.id == tag))
    for tag in exclude_tag_inputs:
        q = q.filter(not_(db.Books.tags.any(db.Tags.id == tag)))
    return q


def adv_search_serie(q, include_series_inputs, exclude_series_inputs):
    for serie in include_series_inputs:
        q = q.filter(db.Books.series.any(db.Series.id == serie))
    for serie in exclude_series_inputs:
        q = q.filter(not_(db.Books.series.any(db.Series.id == serie)))
    return q

def adv_search_shelf(q, include_shelf_inputs, exclude_shelf_inputs):
    q = q.outerjoin(ub.BookShelf, db.Books.id == ub.BookShelf.book_id)\
        .filter(or_(ub.BookShelf.shelf == None, ub.BookShelf.shelf.notin_(exclude_shelf_inputs)))
    if len(include_shelf_inputs) > 0:
        q = q.filter(ub.BookShelf.shelf.in_(include_shelf_inputs))
    return q

def extend_search_term(searchterm,
                       author_name,
                       book_title,
                       publisher,
                       pub_start,
                       pub_end,
                       tags,
                       rating_high,
                       rating_low,
                       read_status,
                       ):
    searchterm.extend((author_name.replace('|', ','), book_title, publisher))
    if pub_start:
        try:
            searchterm.extend([_("Published after ") +
                               format_date(datetime.strptime(pub_start, "%Y-%m-%d"),
                                           format='medium')])
        except ValueError:
            pub_start = ""
    if pub_end:
        try:
            searchterm.extend([_("Published before ") +
                               format_date(datetime.strptime(pub_end, "%Y-%m-%d"),
                                           format='medium')])
        except ValueError:
            pub_end = ""
    elements = {'tag': db.Tags, 'serie':db.Series, 'shelf':ub.Shelf}
    for key, db_element in elements.items():
        tag_names = calibre_db.session.query(db_element).filter(db_element.id.in_(tags['include_' + key])).all()
        searchterm.extend(tag.name for tag in tag_names)
        tag_names = calibre_db.session.query(db_element).filter(db_element.id.in_(tags['exclude_' + key])).all()
        searchterm.extend(tag.name for tag in tag_names)
    language_names = calibre_db.session.query(db.Languages). \
        filter(db.Languages.id.in_(tags['include_language'])).all()
    if language_names:
        language_names = calibre_db.speaking_language(language_names)
    searchterm.extend(language.name for language in language_names)
    language_names = calibre_db.session.query(db.Languages). \
        filter(db.Languages.id.in_(tags['exclude_language'])).all()
    if language_names:
        language_names = calibre_db.speaking_language(language_names)
    searchterm.extend(language.name for language in language_names)
    if rating_high:
        searchterm.extend([_("Rating <= %(rating)s", rating=rating_high)])
    if rating_low:
        searchterm.extend([_("Rating >= %(rating)s", rating=rating_low)])
    if read_status != "Any":
        searchterm.extend([_("Read Status = '%(status)s'", status=read_status)])
    searchterm.extend(ext for ext in tags['include_extension'])
    searchterm.extend(ext for ext in tags['exclude_extension'])
    # handle custom columns
    searchterm = " + ".join(filter(None, searchterm))
    return searchterm, pub_start, pub_end


def render_adv_search_results(term, offset=None, order=None, limit=None):
    sort = order[0] if order else [db.Books.sort]
    pagination = None

    cc = calibre_db.get_cc_columns(config, filter_config_custom_read=True)
    calibre_db.create_functions()
    # calibre_db.session.connection().connection.connection.create_function("lower", 1, db.lcase)
    query = calibre_db.generate_linked_query(config.config_read_column, db.Books)
    q = query.outerjoin(db.books_series_link, db.Books.id == db.books_series_link.c.book)\
        .outerjoin(db.Series)\
        .filter(calibre_db.common_filters(True))

    # parse multi selects to a complete dict
    tags = dict()
    elements = ['tag', 'serie', 'shelf', 'language', 'extension']
    for element in elements:
        tags['include_' + element] = term.get('include_' + element)
        tags['exclude_' + element] = term.get('exclude_' + element)

    author_name = term.get("authors")
    book_title = term.get("title")
    publisher = term.get("publisher")
    pub_start = term.get("publishstart")
    pub_end = term.get("publishend")
    rating_low = term.get("ratinghigh")
    rating_high = term.get("ratinglow")
    description = term.get("comments")
    read_status = term.get("read_status")
    if author_name:
        author_name = strip_whitespaces(author_name).lower().replace(',', '|')
    if book_title:
        book_title = strip_whitespaces(book_title).lower()
    if publisher:
        publisher = strip_whitespaces(publisher).lower()

    search_term = []
    cc_present = False
    for c in cc:
        if c.datatype == "datetime":
            column_start = term.get('custom_column_' + str(c.id) + '_start')
            column_end = term.get('custom_column_' + str(c.id) + '_end')
            if column_start:
                search_term.extend(["{} >= {}".format(c.name,
                                                       format_date(datetime.strptime(column_start, "%Y-%m-%d").date(),
                                                                   format='medium')
                                                       )])
                cc_present = True
            if column_end:
                search_term.extend(["{} <= {}".format(c.name,
                                                      format_date(datetime.strptime(column_end, "%Y-%m-%d").date(),
                                                                   format='medium')
                                                       )])
                cc_present = True
        if c.datatype in ["int", "float"]:
            column_low = term.get('custom_column_' + str(c.id) + '_low')
            column_high = term.get('custom_column_' + str(c.id) + '_high')
            if column_low:
                search_term.extend(["{} >= {}".format(c.name, column_low)])
                cc_present = True
            if column_high:
                search_term.extend(["{} <= {}".format(c.name,column_high)])
                cc_present = True
        elif c.datatype == "bool":
            if term.get('custom_column_' + str(c.id)) != "Any":
                search_term.extend([("{}: {}".format(c.name, term.get('custom_column_' + str(c.id))))])
                cc_present = True
        elif term.get('custom_column_' + str(c.id)):
            search_term.extend([("{}: {}".format(c.name, term.get('custom_column_' + str(c.id))))])
            cc_present = True

    if any(tags.values()) or author_name or book_title or publisher or pub_start or pub_end or rating_low \
       or rating_high or description or cc_present or read_status != "Any":
        search_term, pub_start, pub_end = extend_search_term(search_term,
                                                             author_name,
                                                             book_title,
                                                             publisher,
                                                             pub_start,
                                                             pub_end,
                                                             tags,
                                                             rating_high,
                                                             rating_low,
                                                             read_status)
        if author_name:
            q = q.filter(db.Books.authors.any(func.lower(db.Authors.name).ilike("%" + author_name + "%")))
        if book_title:
            q = q.filter(func.lower(db.Books.title).ilike("%" + book_title + "%"))
        if pub_start:
            q = q.filter(func.datetime(db.Books.pubdate) > func.datetime(pub_start))
        if pub_end:
            q = q.filter(func.datetime(db.Books.pubdate) < func.datetime(pub_end))
        if read_status != "Any":
            q = q.filter(adv_search_read_status(read_status))
        if publisher:
            q = q.filter(db.Books.publishers.any(func.lower(db.Publishers.name).ilike("%" + publisher + "%")))
        q = adv_search_tag(q, tags['include_tag'], tags['exclude_tag'])
        q = adv_search_serie(q, tags['include_serie'], tags['exclude_serie'])
        q = adv_search_shelf(q, tags['include_shelf'], tags['exclude_shelf'])
        q = adv_search_extension(q, tags['include_extension'], tags['exclude_extension'])
        q = adv_search_language(q, tags['include_language'], tags['exclude_language'])
        q = adv_search_ratings(q, rating_high, rating_low)

        if description:
            q = q.filter(db.Books.comments.any(func.lower(db.Comments.text).ilike("%" + description + "%")))

        # search custom columns
        try:
            q = adv_search_custom_columns(cc, term, q)
        except AttributeError as ex:
            log.debug_or_exception(ex)
            flash(_("Error on search for custom columns, please restart Calibre-Web"), category="error")

    q = q.order_by(*sort)
    flask_session['query'] = json.dumps(term)

    # Perform a count query for pagination, which is much faster than fetching all results.
    result_count = q.count()

    if offset is not None and limit is not None:
        offset = int(offset)
        pagination = Pagination(page=(offset // limit + 1), per_page=limit, total_count=result_count)
        # Fetch only the required page of results from the database
        results = q.offset(offset).limit(limit).all()
    else:
        offset = 0
        limit = result_count if result_count > 0 else 1
        pagination = Pagination(page=1, per_page=limit, total_count=result_count)
        results = q.all()

    # Note: store_combo_ids will now only contain the IDs of the currently visible page.
    # This improves performance drastically for large search results, but affects
    # functionality that relies on having all search result IDs (e.g., "download all").
    ub.store_combo_ids(results)

    entries = calibre_db.order_authors(results, list_return=True, combined=True)
    shelfmark_query, shelfmark_fields = build_shelfmark_advanced_query(term)
    shelfmark_section = _build_shelfmark_section(
        shelfmark_query,
        detail_url_builder=lambda book: _build_shelfmark_detail_url(
            book,
            query=shelfmark_query or search_term,
            return_to=_current_shelfmark_search_state_url(),
        ),
        query_label=_("Advanced external query"),
        context_hint=(
            _("Built from %(fields)s only. Other advanced filters stay local to CWA.", fields=", ".join(shelfmark_fields))
            if shelfmark_query
            else _("Advanced external search only uses title, author, and publisher fields when present.")
        ),
        empty_message=_("Add a title, author, or publisher filter to include Shelfmark external results in advanced search."),
    )
    return render_title_template('search.html',
                                 adv_searchterm=search_term,
                                 pagination=pagination,
                                 entries=entries,
                                 query="",
                                 shelfmark_section=shelfmark_section,
                                 result_count=result_count,
                                 title=_("Advanced Search"), page="advsearch",
                                 order=order[1])


def render_prepare_search_form(cc):
    # prepare data for search-form
    tags = calibre_db.session.query(db.Tags)\
        .join(db.books_tags_link)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()) \
        .group_by(text('books_tags_link.tag'))\
        .order_by(db.Tags.name).all()
    series = calibre_db.session.query(db.Series)\
        .join(db.books_series_link)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()) \
        .group_by(text('books_series_link.series'))\
        .order_by(db.Series.name)\
        .filter(calibre_db.common_filters()).all()
    shelves = ub.session.query(ub.Shelf)\
        .filter(or_(ub.Shelf.is_public == 1, ub.Shelf.user_id == int(current_user.id)))\
        .order_by(ub.Shelf.name).all()
    extensions = calibre_db.session.query(db.Data)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()) \
        .group_by(db.Data.format)\
        .order_by(db.Data.format).all()
    if current_user.filter_language() == "all":
        languages = calibre_db.speaking_language()
    else:
        languages = None
    return render_title_template('search_form.html', tags=tags, languages=languages, extensions=extensions,
                                 series=series,shelves=shelves, title=_("Advanced Search"), cc=cc, page="advsearch")


def render_search_results(term, offset=None, order=None, limit=None):
    shelfmark_section = None
    if term:
        join = db.books_series_link, db.Books.id == db.books_series_link.c.book, db.Series
        entries, result_count, pagination = calibre_db.get_search_results(term,
                                                                          config,
                                                                          offset,
                                                                          order,
                                                                          limit,
                                                                          *join)
        shelfmark_section = _build_shelfmark_section(
            term,
            detail_url_builder=lambda book: _build_shelfmark_detail_url(
                book,
                query=term,
                return_to=_current_shelfmark_search_state_url(),
            ),
            query_label=_("External lookup query"),
        )
    else:
        entries = list()
        order = [None, None]
        pagination = result_count = None

    return render_title_template('search.html',
                                 searchterm=term,
                                 pagination=pagination,
                                 query=term,
                                 adv_searchterm=term,
                                 entries=entries,
                                 shelfmark_section=shelfmark_section,
                                 result_count=result_count,
                                 title=_("Search"),
                                 page="search",
                                 order=order[1])

@search.route("/search/external/shelfmark/<provider>/<provider_id>", methods=["GET"])
@login_required_if_no_ano
def shelfmark_external_detail(provider, provider_id):
    query = (request.args.get("query") or "").strip()
    return_to = _safe_local_return_url(request.args.get("return_to"))
    modal_view = (request.args.get("view") or "").strip().lower() == "modal"
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    detail_url = url_for(
        "search.shelfmark_external_detail",
        provider=provider,
        provider_id=provider_id,
        query=query,
        return_to=return_to,
    )

    try:
        result = fetch_shelfmark_detail(
            provider,
            provider_id,
            detail_url=detail_url,
        ).to_template_dict()
        if modal_view:
            return render_template(
                "shelfmark_external_detail_content.html",
                result=result,
                modal_mode=True,
                preferred_release=preferred_release,
                shelfmark_error=None,
            )
        return render_title_template(
            "shelfmark_external_detail.html",
            title=result.get("title") or _("Shelfmark External Result"),
            page="search",
            result=result,
            search_query=query,
            return_to=return_to,
            modal_mode=False,
            preferred_release=preferred_release,
        )
    except ShelfmarkIntegrationError as exc:
        flash(str(exc), category="error")
        if modal_view:
            return render_template(
                "shelfmark_external_detail_content.html",
                title=_("Shelfmark External Result"),
                result=None,
                modal_mode=True,
                preferred_release=preferred_release,
                shelfmark_error=str(exc),
            )
        return render_title_template(
            "shelfmark_external_detail.html",
            title=_("Shelfmark External Result"),
            page="search",
            result=None,
            search_query=query,
            return_to=return_to,
            shelfmark_error=str(exc),
            modal_mode=False,
            preferred_release=preferred_release,
        )


@search.route("/search/external/shelfmark/<provider>/<provider_id>/row", methods=["GET"])
@login_required_if_no_ano
def shelfmark_external_row(provider, provider_id):
    query = (request.args.get("query") or "").strip()
    return_to = _safe_local_return_url(request.args.get("return_to"))
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    detail_url = url_for(
        "search.shelfmark_external_detail",
        provider=provider,
        provider_id=provider_id,
        query=query,
        return_to=return_to,
    )

    try:
        result_view = fetch_shelfmark_detail(
            provider,
            provider_id,
            detail_url=detail_url,
        )
        result = result_view.to_template_dict()
        _populate_shelfmark_row_state(result)
        result["needs_progressive_enrichment"] = False
        result["progressive_filter_pending"] = False
        return jsonify(
            {
                "ok": True,
                "matches_filters": result_matches_shelfmark_filters(
                    result_view,
                    requestable_only=_requested_shelfmark_flag(
                        "shelfmark_filter_requestable",
                        default=DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
                    ),
                    has_cover_only=_requested_shelfmark_flag(
                        "shelfmark_filter_has_cover",
                        default=DEFAULT_SHELFMARK_FILTER_HAS_COVER,
                    ),
                    series_filter=_requested_shelfmark_series_filter(),
                ),
                "row_class_name": result["row_class_name"],
                "row_status_provider": result["row_status_provider"],
                "row_status_provider_id": result["row_status_provider_id"],
                "row_status_in_library": result["row_status_in_library"],
                "row_has_cover": result["row_has_cover"],
                "row_series_matched": result["row_series_matched"],
                "row_series_next_missing": result["row_series_next_missing"],
                "hidden_reasons": _build_shelfmark_hidden_reason_keys(result_view),
                "library_book_url": result.get("library_book_url"),
                "library_book_title": result.get("library_book_title"),
                "html": render_template(
                    "shelfmark_external_result_card_inner.html",
                    result=result,
                    preferred_release=preferred_release,
                ),
            }
        )
    except ShelfmarkIntegrationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503


@search.route("/search/external/shelfmark/topup", methods=["GET"])
@login_required_if_no_ano
def shelfmark_external_topup():
    query = (request.args.get("query") or "").strip()
    return_to = _safe_local_return_url(request.args.get("return_to"))
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    try:
        source_page = int(request.args.get("shelfmark_source_page", "1"))
    except (TypeError, ValueError):
        source_page = 1
    if source_page < 1:
        source_page = 1

    try:
        section = search_shelfmark_results(
            query,
            detail_url_builder=lambda book: _build_shelfmark_detail_url(
                book,
                query=query,
                return_to=return_to,
            ),
            page=source_page,
            page_size=_requested_shelfmark_page_size(),
            sort=_requested_shelfmark_sort(),
            series_filter=_requested_shelfmark_series_filter(),
            filter_requestable=_requested_shelfmark_flag(
                "shelfmark_filter_requestable",
                default=DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
            ),
            filter_has_cover=_requested_shelfmark_flag(
                "shelfmark_filter_has_cover",
                default=DEFAULT_SHELFMARK_FILTER_HAS_COVER,
            ),
        ).to_template_dict()
        section["state_url"] = return_to
        _decorate_shelfmark_result_rows(section, query=query)
        rows = []
        for result in section.get("results") or []:
            rows.append(
                {
                    "provider": result.get("provider") or "",
                    "provider_id": result.get("provider_id") or "",
                    "row_class_name": result.get("row_class_name") or "",
                    "row_status_provider": result.get("row_status_provider") or "",
                    "row_status_provider_id": result.get("row_status_provider_id") or "",
                    "row_status_in_library": result.get("row_status_in_library") or "0",
                    "row_has_cover": result.get("row_has_cover") or "0",
                    "row_series_matched": result.get("row_series_matched") or "0",
                    "row_series_next_missing": result.get("row_series_next_missing") or "0",
                    "library_book_url": result.get("library_book_url"),
                    "library_book_title": result.get("library_book_title"),
                    "row_enrichment_url": result.get("row_enrichment_url") or "",
                    "html": render_template(
                        "shelfmark_external_result_card_inner.html",
                        result=result,
                        preferred_release=preferred_release,
                    ),
                }
            )
        return jsonify(
            {
                "ok": True,
                "page": source_page,
                "has_more": bool(section.get("has_more")),
                "next_page": section.get("next_page"),
                "rows": rows,
            }
        )
    except ShelfmarkIntegrationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503


@search.route("/search/external/shelfmark/library-status", methods=["GET"])
@login_required_if_no_ano
def shelfmark_external_library_status():
    provider_ids = []
    seen_provider_ids = set()
    for raw_value in request.args.getlist("provider_id"):
        normalized = (raw_value or "").strip()
        if not normalized or normalized in seen_provider_ids:
            continue
        seen_provider_ids.add(normalized)
        provider_ids.append(normalized)

    matches = lookup_visible_library_matches(provider_ids)
    payload = {}
    for provider_id in provider_ids:
        library_match = matches.get(provider_id)
        payload[provider_id] = {
            "in_library": bool(library_match),
            "book_id": library_match.book_id if library_match is not None else None,
            "book_title": library_match.title if library_match is not None else None,
            "book_url": (
                url_for("web.show_book", book_id=library_match.book_id)
                if library_match is not None
                else None
            ),
        }

    return jsonify({"ok": True, "matches": payload})


def _build_shelfmark_detail_url(book, *, query, return_to=None):
    provider = (book or {}).get("provider")
    provider_id = (book or {}).get("provider_id")
    if not provider or not provider_id:
        return None
    return url_for(
        "search.shelfmark_external_detail",
        provider=provider,
        provider_id=provider_id,
        query=query,
        return_to=_safe_local_return_url(return_to),
    )


def _build_shelfmark_row_enrichment_url(book, *, query, return_to=None):
    provider = (book or {}).get("provider")
    provider_id = (book or {}).get("provider_id")
    if not provider or not provider_id:
        return None

    params = _current_request_params(include_transient=False)
    params["query"] = query
    safe_return_to = _safe_local_return_url(return_to)
    if safe_return_to:
        params["return_to"] = safe_return_to
    else:
        params.pop("return_to", None)
    return url_for(
        "search.shelfmark_external_row",
        provider=provider,
        provider_id=provider_id,
        **params,
    )


def _build_shelfmark_top_up_url(*, query, return_to=None):
    params = _current_request_params(include_transient=False)
    params["query"] = query
    params.pop("shelfmark_source_page", None)
    safe_return_to = _safe_local_return_url(return_to)
    if safe_return_to:
        params["return_to"] = safe_return_to
    else:
        params.pop("return_to", None)
    return url_for("search.shelfmark_external_topup", **params)


def _build_shelfmark_hidden_reason_keys(result_view):
    requestable_only = _requested_shelfmark_flag(
        "shelfmark_filter_requestable",
        default=DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
    )
    has_cover_only = _requested_shelfmark_flag(
        "shelfmark_filter_has_cover",
        default=DEFAULT_SHELFMARK_FILTER_HAS_COVER,
    )
    series_filter = _requested_shelfmark_series_filter()
    reasons = []

    if requestable_only and (
        result_view.already_in_library
        or not result_view.hardcover_id
        or not result_view.request_payload
    ):
        if result_view.already_in_library:
            reasons.append("already_in_library")
        else:
            reasons.append("filtered")
    if has_cover_only and not result_view.cover_url:
        reasons.append("no_cover")
    if series_filter == "owned" and not (
        result_view.series_context and result_view.series_context.matched
    ):
        reasons.append("owned_series")
    if series_filter == "next_missing" and not (
        result_view.series_context and result_view.series_context.is_next_missing
    ):
        reasons.append("next_missing")

    if not reasons and not result_matches_shelfmark_filters(
        result_view,
        requestable_only=requestable_only,
        has_cover_only=has_cover_only,
        series_filter=series_filter,
    ):
        reasons.append("filtered")

    return reasons


def _build_shelfmark_result_row_class_name(result):
    library_state = result.get("library_state") or {}
    classes = [
        "shelfmark-result-card",
        "js-shelfmark-result-row",
        "shelfmark-result-card--%s" % (library_state.get("row_class") or "info"),
    ]
    if result.get("workflow_state") and not result.get("already_in_library"):
        classes.append("js-shelfmark-status-target")
    if result.get("request_payload") and not result.get("already_in_library"):
        classes.append("js-shelfmark-batch-row")
    if result.get("needs_progressive_enrichment"):
        classes.append("js-shelfmark-progressive-row")
    if result.get("needs_progressive_enrichment") or result.get("progressive_filter_pending"):
        classes.append("shelfmark-result-card--refining")
    return " ".join(classes)


def _populate_shelfmark_row_state(result):
    result["row_class_name"] = _build_shelfmark_result_row_class_name(result)
    result["row_status_provider"] = (
        "hardcover"
        if result.get("workflow_state") and not result.get("already_in_library")
        else ""
    )
    result["row_status_provider_id"] = result.get("hardcover_id") or ""
    result["row_status_in_library"] = "1" if result.get("already_in_library") else "0"
    result["row_has_cover"] = "1" if result.get("cover_url") else "0"
    series_context = result.get("series_context") or {}
    result["row_series_matched"] = "1" if series_context.get("matched") else "0"
    result["row_series_next_missing"] = (
        "1" if series_context.get("is_next_missing") else "0"
    )


def _decorate_shelfmark_result_rows(section, *, query):
    results = section.get("results") or []
    state_url = section.get("state_url")
    for index, result in enumerate(results):
        result["row_index"] = index
        _populate_shelfmark_row_state(result)
        result["row_enrichment_url"] = (
            _build_shelfmark_row_enrichment_url(
                result,
                query=query,
                return_to=state_url,
            )
            if result.get("needs_progressive_enrichment")
            else None
        )


def _current_request_params(*, include_transient=True):
    params = request.args.to_dict(flat=True)
    if include_transient:
        return params
    for key in SHELFMARK_TRANSIENT_QUERY_KEYS:
        params.pop(key, None)
    return params


def _request_url_for_params(params):
    if not params:
        return url_for(request.endpoint, **(request.view_args or {}))
    return url_for(request.endpoint, **(request.view_args or {}), **params)


def _current_request_path(*, include_transient=True):
    return _request_url_for_params(
        _current_request_params(include_transient=include_transient)
    )


def _current_shelfmark_search_state_url():
    return _current_request_path(include_transient=False)


def _requested_shelfmark_page():
    try:
        page = int(request.args.get("shelfmark_page", "1"))
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _requested_shelfmark_page_size():
    try:
        page_size = int(request.args.get("shelfmark_page_size", "12"))
    except (TypeError, ValueError):
        return 12
    return page_size if page_size > 0 else 12


def _requested_shelfmark_sort():
    return (request.args.get("shelfmark_sort", "popularity") or "popularity").strip().lower()


def _requested_shelfmark_series_filter():
    values = request.args.getlist("shelfmark_series_filter")
    if not values:
        return DEFAULT_SHELFMARK_SERIES_FILTER
    return (values[-1] or DEFAULT_SHELFMARK_SERIES_FILTER).strip().lower()


def _requested_shelfmark_flag(name, default=False):
    values = request.args.getlist(name)
    if not values:
        return default
    return (values[-1] or "").strip().lower() in {"1", "true", "yes", "on"}


def _current_request_url_with(**updates):
    params = _current_request_params(include_transient=False)
    params.update({key: str(value) for key, value in updates.items() if value not in (None, "")})
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
    return _request_url_for_params(params)


def _build_shelfmark_section(query, **kwargs):
    preferred_release = get_shelfmark_preferred_release_settings().to_template_dict()
    section = search_shelfmark_results(
        query,
        page=_requested_shelfmark_page(),
        page_size=_requested_shelfmark_page_size(),
        sort=_requested_shelfmark_sort(),
        series_filter=_requested_shelfmark_series_filter(),
        filter_requestable=_requested_shelfmark_flag(
            "shelfmark_filter_requestable",
            default=DEFAULT_SHELFMARK_FILTER_REQUESTABLE,
        ),
        filter_has_cover=_requested_shelfmark_flag(
            "shelfmark_filter_has_cover",
            default=DEFAULT_SHELFMARK_FILTER_HAS_COVER,
        ),
        **kwargs,
    ).to_template_dict()
    if not section.get("enabled"):
        return section

    section["state_url"] = _current_request_url_with(
        shelfmark_page=section.get("page") or 1,
        shelfmark_page_size=section.get("page_size") or 12,
        shelfmark_sort=section.get("selected_sort"),
        shelfmark_series_filter=section.get("selected_series_filter"),
        shelfmark_filter_requestable="1" if section.get("filter_requestable") else "0",
        shelfmark_filter_has_cover="1" if section.get("filter_has_cover") else "0",
    )

    previous_page = section.get("previous_page")
    next_page = section.get("next_page")
    section["previous_page_url"] = (
        _current_request_url_with(shelfmark_page=previous_page)
        if previous_page
        else None
    )
    section["next_page_url"] = (
        _current_request_url_with(shelfmark_page=next_page)
        if next_page
        else None
    )
    section["clear_filters_url"] = _current_request_url_with(
        shelfmark_page=1,
        shelfmark_sort=None,
        shelfmark_series_filter=None,
        shelfmark_filter_requestable=None,
        shelfmark_filter_has_cover=None,
    )
    section["requestable_toggle_url"] = _current_request_url_with(
        shelfmark_page=1,
        shelfmark_filter_requestable="0" if section.get("filter_requestable") else "1",
    )
    section["requestable_toggle_label"] = (
        _("Show all matches")
        if section.get("filter_requestable")
        else _("Focus on requestable")
    )
    section["top_up_url"] = _build_shelfmark_top_up_url(
        query=query,
        return_to=section.get("state_url"),
    )
    section["preferred_release_settings"] = preferred_release
    _decorate_shelfmark_result_rows(section, query=query)
    return section


def _safe_local_return_url(value):
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return None
    return candidate
