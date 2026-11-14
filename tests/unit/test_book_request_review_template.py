"""The held-file admin view renders a complete match decision."""

from pathlib import Path
from types import SimpleNamespace

from jinja2 import DictLoader, Environment


def test_held_file_review_renders_without_a_note_minimum():
    template = Path(__file__).resolve().parents[2] / "cps/templates/nova_reader_requests.html"
    env = Environment(loader=DictLoader({
        "layout.html": "{% block header %}{% endblock %}{% block body %}{% endblock %}",
        "nova_reader_requests.html": template.read_text(encoding="utf-8"),
    }), autoescape=True)
    env.globals.update(url_for=lambda endpoint, **kwargs: "/" + kwargs.get("filename", endpoint),
                       csrf_token=lambda: "token",
                       g=SimpleNamespace(current_theme=1),
                       current_user=SimpleNamespace(role_admin=lambda: True))
    review = dict(status="available", source_name="1984.epub", reading_words=111492,
                  source_sha256="a" * 64, source_title="1984 (Penguin)",
                  source_authors=["George Orwell"], source_languages=["en-GB"],
                  source_isbns=["9780141919959"], source_excerpt=["PENGUIN BOOKS"],
                  source_evidence=dict(title_in_reading_pages=True,
                                       author_in_reading_pages=True, english_body_sample=True,
                                       explicit_abridgment=False, possible_sample_or_truncation=False))
    job = dict(work=379760, title="1984", authors="George Orwell", cover_url="https://assets.hardcover.app/cover.jpg",
               updated=1, state="held", book_url=None, readers=[], release_date=None,
               review_reason="Downloaded file held", review_guidance="Inspect this file",
               book_id=3181, download_id="download-id", file_review=review,
               decision=dict(action="approve", note="This is okay to get"),
               release_title=None, protocol=None, indexer=None, size_bytes=None,
               format=None, alert="sent")
    html = env.get_template("nova_reader_requests.html").render(
        admin_view=True, request_jobs=[job], counts={"held": 1}, status_labels={"held": "Needs review"},
        people=[], state_filter="held", person_filter="", total=1, reader_names={},
        page_number=1, last_page=1, format_request_time=lambda value: "1 Jan 2026")
    assert "Match and approve this downloaded file" in html
    assert "Approve matched file" in html
    assert "9780141919959" in html
    assert "minlength" not in html
    assert "nova_reader_review.js" in html
