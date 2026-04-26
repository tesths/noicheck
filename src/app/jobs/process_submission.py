from __future__ import annotations

from src.app import create_app
from src.app.services.submission_pipeline import process_submission

_app = None


def _get_app():
    global _app
    if _app is None:
        _app = create_app()
    return _app


def process_submission_job(public_id: str) -> bool:
    app = _get_app()
    with app.app_context():
        return process_submission(public_id)
