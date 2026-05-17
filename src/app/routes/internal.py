import hmac

from flask import Blueprint, current_app, jsonify, request

from ..extensions import csrf
from ..services.job_queue import JobQueueError
from ..services.jobs import process_job_message

internal_bp = Blueprint("internal", __name__, url_prefix="/internal")
csrf.exempt(internal_bp)


def _is_authorized() -> bool:
    expected = str(current_app.config.get("INTERNAL_JOB_TOKEN", "")).strip()
    provided = request.headers.get("X-Internal-Job-Token", "").strip()
    return bool(expected) and hmac.compare_digest(expected, provided)


@internal_bp.post("/jobs/process")
def process_job():
    if not _is_authorized():
        return jsonify({"ok": False, "error": "forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    job_type = str(payload.get("job_type", "")).strip()
    submission_public_id = str(payload.get("submission_public_id", "")).strip()
    if not job_type or not submission_public_id:
        return jsonify({"ok": False, "error": "invalid_payload"}), 400

    try:
        status = process_job_message(
            job_type=job_type,
            submission_public_id=submission_public_id,
        )
    except JobQueueError as exc:
        return jsonify({"ok": False, "error": str(exc), "retryable": False}), 400
    except Exception:
        current_app.logger.exception(
            "内部任务处理异常 job_type=%s submission=%s",
            job_type,
            submission_public_id,
        )
        return jsonify({"ok": False, "error": "internal_error", "retryable": True}), 500

    return jsonify({"ok": True, "status": status})
