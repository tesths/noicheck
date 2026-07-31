import hmac
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from ..extensions import csrf
from ..models import Submission
from ..services.job_queue import JobQueueError
from ..services.jobs import process_job_message
from ..services.operations import build_operation_health_report

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


@internal_bp.get("/operations/health")
def operations_health():
    if not _is_authorized():
        return jsonify({"ok": False, "error": "forbidden"}), 403

    submissions = Submission.query.filter(Submission.deleted_at.is_(None)).all()
    report = build_operation_health_report(submissions, failure_limit=0)
    summary = report.summary
    is_healthy = summary.total_failed == 0
    payload = {
        "ok": is_healthy,
        "status": "ok" if is_healthy else "unhealthy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_submissions": summary.total_submissions,
            "total_failed": summary.total_failed,
            "total_processing": summary.total_processing,
            "fetch_failed": summary.fetch_failed,
            "student_hint_failed": summary.student_hint_failed,
            "teacher_diagnosis_failed": summary.teacher_diagnosis_failed,
            "fetch_processing": summary.fetch_processing,
            "student_hint_processing": summary.student_hint_processing,
            "teacher_diagnosis_processing": summary.teacher_diagnosis_processing,
        },
    }
    status_code = 503 if not is_healthy and _fail_on_unhealthy_requested() else 200
    return jsonify(payload), status_code


def _fail_on_unhealthy_requested() -> bool:
    return request.args.get("fail_on_unhealthy", "").strip().lower() in {"1", "true", "yes", "on"}
