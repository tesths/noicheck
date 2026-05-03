import hashlib
import time

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import DiagnosisRun, ProblemSnapshot, Submission
from .ai import (
    DeepSeekDiagnosisService,
    DiagnosisPayload,
    DiagnosisServiceError,
    PROMPT_VERSION,
    STUDENT_PROMPT_VERSION,
)
from .job_queue import JobMessage, JobQueueError, enqueue_job
from .problem_fetcher import OpenJudgeProblemFetcher, ProblemFetchError

FETCH_PROBLEM_JOB = "fetch-problem"
DIAGNOSE_SUBMISSION_JOB = "diagnose-submission"
FETCH_AND_DIAGNOSE_JOB = "fetch-and-diagnose"
FETCH_AND_STUDENT_DIAGNOSE_JOB = "fetch-and-student-diagnose"

PROCESSING_DIAGNOSIS_STATUSES = {"queued", "running"}


def enqueue_fetch_problem_job(submission: Submission, *, requested_by: str) -> None:
    previous_fetch_status = submission.fetch_status
    submission.fetch_status = "queued"
    db.session.commit()

    message = JobMessage(
        job_type=FETCH_PROBLEM_JOB,
        submission_public_id=submission.public_id,
        requested_by=requested_by,
    )
    try:
        enqueue_job(message, idempotency_key=_fetch_idempotency_key(submission))
    except JobQueueError:
        db.session.rollback()
        submission.fetch_status = previous_fetch_status
        db.session.commit()
        raise


def enqueue_diagnosis_job(submission: Submission, *, requested_by: str) -> None:
    if submission.diagnosis_status in PROCESSING_DIAGNOSIS_STATUSES:
        raise JobQueueError("已有后台任务正在处理这条提交，请稍后刷新查看结果。")
    if submission.student_hint_status in PROCESSING_DIAGNOSIS_STATUSES:
        raise JobQueueError("学生提示任务正在处理这条提交，请稍后刷新查看结果。")

    previous_fetch_status = submission.fetch_status
    previous_diagnosis_status = submission.diagnosis_status

    if submission.fetch_status == "success" and submission.problem_snapshot is not None:
        submission.diagnosis_status = "queued"
        job_type = DIAGNOSE_SUBMISSION_JOB
    else:
        submission.fetch_status = "queued"
        submission.diagnosis_status = "queued"
        job_type = FETCH_AND_DIAGNOSE_JOB

    db.session.commit()

    message = JobMessage(
        job_type=job_type,
        submission_public_id=submission.public_id,
        requested_by=requested_by,
    )
    try:
        enqueue_job(message, idempotency_key=_diagnosis_idempotency_key(submission))
    except JobQueueError:
        db.session.rollback()
        submission.fetch_status = previous_fetch_status
        submission.diagnosis_status = previous_diagnosis_status
        db.session.commit()
        raise


def enqueue_student_hint_job(submission: Submission, *, requested_by: str) -> None:
    if submission.student_hint_status in PROCESSING_DIAGNOSIS_STATUSES:
        raise JobQueueError("已有学生提示任务正在处理这条提交，请稍后刷新查看结果。")

    previous_fetch_status = submission.fetch_status
    previous_student_hint_status = submission.student_hint_status

    submission.fetch_status = "queued"
    submission.student_hint_status = "queued"
    db.session.commit()

    message = JobMessage(
        job_type=FETCH_AND_STUDENT_DIAGNOSE_JOB,
        submission_public_id=submission.public_id,
        requested_by=requested_by,
    )
    try:
        enqueue_job(message, idempotency_key=_student_hint_idempotency_key(submission))
    except JobQueueError:
        db.session.rollback()
        submission.fetch_status = previous_fetch_status
        submission.student_hint_status = previous_student_hint_status
        db.session.commit()
        raise


def process_job_message(*, job_type: str, submission_public_id: str) -> str:
    if job_type == FETCH_PROBLEM_JOB:
        return process_fetch_problem_job(submission_public_id)
    if job_type == DIAGNOSE_SUBMISSION_JOB:
        return process_diagnosis_job(submission_public_id, fetch_before_diagnosis=False)
    if job_type == FETCH_AND_DIAGNOSE_JOB:
        return process_diagnosis_job(submission_public_id, fetch_before_diagnosis=True)
    if job_type == FETCH_AND_STUDENT_DIAGNOSE_JOB:
        return process_student_hint_job(submission_public_id, fetch_before_diagnosis=True)
    raise JobQueueError(f"未知任务类型：{job_type}")


def process_fetch_problem_job(submission_public_id: str) -> str:
    submission = _get_submission(submission_public_id)
    if submission is None:
        return "skipped"
    if submission.fetch_status == "success" and submission.problem_snapshot is not None:
        return "success"

    submission.fetch_status = "running"
    db.session.commit()
    return _sync_problem_snapshot(submission)


def process_diagnosis_job(submission_public_id: str, *, fetch_before_diagnosis: bool) -> str:
    job_started_at = time.perf_counter()
    submission = _get_submission(submission_public_id)
    if submission is None:
        return "skipped"
    if submission.diagnosis_status == "success":
        return "success"

    needs_fetch = fetch_before_diagnosis or submission.fetch_status != "success" or submission.problem_snapshot is None
    fetch_latency_ms: int | None = None
    if needs_fetch:
        submission.fetch_status = "running"
        db.session.commit()
        fetch_started_at = time.perf_counter()
        fetch_status = _sync_problem_snapshot(submission)
        fetch_latency_ms = int((time.perf_counter() - fetch_started_at) * 1000)
        if fetch_status != "success":
            refreshed = _get_submission(submission_public_id)
            if refreshed is None:
                return "failed"
            refreshed.diagnosis_status = "failed"
            db.session.add(
                DiagnosisRun(
                    submission=refreshed,
                    model_name=_ai_model_name(),
                    prompt_version=PROMPT_VERSION,
                    status="failed",
                    error_message=_fetch_failure_message(refreshed),
                )
            )
            db.session.commit()
            return "failed"
        submission = _get_submission(submission_public_id)
        if submission is None:
            return "failed"

    submission.diagnosis_status = "running"
    db.session.commit()

    ai_config = _ai_config()
    diagnosis_service = DeepSeekDiagnosisService(
        api_key=ai_config["api_key"],
        base_url=ai_config["base_url"],
        model_name=ai_config["model_name"],
    )

    snapshot = submission.problem_snapshot
    try:
        diagnosis = diagnosis_service.diagnose(
            DiagnosisPayload(
                student_name=submission.student_name,
                problem_url=submission.problem_url,
                problem_title=submission.problem_title,
                description_text=snapshot.description_text if snapshot else None,
                input_text=snapshot.input_text if snapshot else None,
                output_text=snapshot.output_text if snapshot else None,
                sample_input_text=snapshot.sample_input_text if snapshot else None,
                sample_output_text=snapshot.sample_output_text if snapshot else None,
                code_text=submission.code_text,
            )
        )

        submission.diagnosis_status = "success"
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="teacher",
                model_name=diagnosis.model_name,
                prompt_version=PROMPT_VERSION,
                status="success",
                structured_result_json=diagnosis.result.model_dump(),
                summary_text=diagnosis.result.overall_assessment,
                latency_ms=diagnosis.latency_ms,
            )
        )
        db.session.commit()
        current_app.logger.info(
            "老师诊断完成 submission=%s fetch_ms=%s ai_ms=%s total_ms=%s base_url=%s model=%s",
            submission.public_id,
            fetch_latency_ms,
            diagnosis.latency_ms,
            int((time.perf_counter() - job_started_at) * 1000),
            ai_config["base_url"],
            ai_config["model_name"],
        )
        return "success"
    except (DiagnosisServiceError, SQLAlchemyError) as exc:
        db.session.rollback()
        failed_submission = _get_submission(submission_public_id)
        if failed_submission is None:
            return "failed"
        failed_submission.diagnosis_status = "failed"
        db.session.add(
            DiagnosisRun(
                submission=failed_submission,
                audience="teacher",
                model_name=ai_config["model_name"],
                prompt_version=PROMPT_VERSION,
                status="failed",
                error_message=str(exc),
            )
        )
        db.session.commit()
        return "failed"


def process_student_hint_job(submission_public_id: str, *, fetch_before_diagnosis: bool) -> str:
    job_started_at = time.perf_counter()
    submission = _get_submission(submission_public_id)
    if submission is None:
        return "skipped"
    if submission.student_hint_status == "success":
        return "success"

    needs_fetch = fetch_before_diagnosis or submission.fetch_status != "success" or submission.problem_snapshot is None
    fetch_latency_ms: int | None = None
    if needs_fetch:
        submission.fetch_status = "running"
        db.session.commit()
        fetch_started_at = time.perf_counter()
        fetch_status = _sync_problem_snapshot(submission)
        fetch_latency_ms = int((time.perf_counter() - fetch_started_at) * 1000)
        if fetch_status != "success":
            refreshed = _get_submission(submission_public_id)
            if refreshed is None:
                return "failed"
            refreshed.student_hint_status = "failed"
            db.session.add(
                DiagnosisRun(
                    submission=refreshed,
                    audience="student",
                    model_name=_ai_model_name(),
                    prompt_version=STUDENT_PROMPT_VERSION,
                    status="failed",
                    error_message=_fetch_failure_message(refreshed),
                )
            )
            db.session.commit()
            return "failed"
        submission = _get_submission(submission_public_id)
        if submission is None:
            return "failed"

    submission.student_hint_status = "running"
    db.session.commit()

    ai_config = _ai_config()
    diagnosis_service = DeepSeekDiagnosisService(
        api_key=ai_config["api_key"],
        base_url=ai_config["base_url"],
        model_name=ai_config["model_name"],
    )

    snapshot = submission.problem_snapshot
    try:
        diagnosis = diagnosis_service.diagnose_student(
            DiagnosisPayload(
                student_name=submission.student_name,
                problem_url=submission.problem_url,
                problem_title=submission.problem_title,
                description_text=snapshot.description_text if snapshot else None,
                input_text=snapshot.input_text if snapshot else None,
                output_text=snapshot.output_text if snapshot else None,
                sample_input_text=snapshot.sample_input_text if snapshot else None,
                sample_output_text=snapshot.sample_output_text if snapshot else None,
                code_text=submission.code_text,
            )
        )

        submission.student_hint_status = "success"
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="student",
                model_name=diagnosis.model_name,
                prompt_version=STUDENT_PROMPT_VERSION,
                status="success",
                structured_result_json=diagnosis.result.model_dump(),
                summary_text=diagnosis.result.overall_assessment,
                latency_ms=diagnosis.latency_ms,
            )
        )
        db.session.commit()
        current_app.logger.info(
            "学生提示完成 submission=%s fetch_ms=%s ai_ms=%s total_ms=%s base_url=%s model=%s",
            submission.public_id,
            fetch_latency_ms,
            diagnosis.latency_ms,
            int((time.perf_counter() - job_started_at) * 1000),
            ai_config["base_url"],
            ai_config["model_name"],
        )
        return "success"
    except (DiagnosisServiceError, SQLAlchemyError) as exc:
        db.session.rollback()
        failed_submission = _get_submission(submission_public_id)
        if failed_submission is None:
            return "failed"
        failed_submission.student_hint_status = "failed"
        db.session.add(
            DiagnosisRun(
                submission=failed_submission,
                audience="student",
                model_name=ai_config["model_name"],
                prompt_version=STUDENT_PROMPT_VERSION,
                status="failed",
                error_message=str(exc),
            )
        )
        db.session.commit()
        return "failed"


def _sync_problem_snapshot(submission: Submission) -> str:
    fetcher = OpenJudgeProblemFetcher(timeout=float(current_app.config.get("OPENJUDGE_REQUEST_TIMEOUT", 10)))
    snapshot = submission.problem_snapshot
    try:
        problem = fetcher.fetch(submission.problem_url)
        submission.problem_url = problem.normalized_url
        submission.problem_path = problem.problem_path
        submission.problem_title = problem.title
        submission.fetch_status = "success"
        if snapshot is None:
            snapshot = ProblemSnapshot(submission=submission, normalized_url=problem.normalized_url)
            db.session.add(snapshot)
        snapshot.normalized_url = problem.normalized_url
        snapshot.title = problem.title
        snapshot.description_text = problem.description_text
        snapshot.input_text = problem.input_text
        snapshot.output_text = problem.output_text
        snapshot.sample_input_text = problem.sample_input_text
        snapshot.sample_output_text = problem.sample_output_text
        snapshot.source_text = problem.source_text
        snapshot.raw_excerpt = problem.raw_excerpt
        snapshot.fetch_error = None
        db.session.commit()
        return "success"
    except ProblemFetchError as exc:
        submission.fetch_status = "failed"
        if snapshot is None:
            snapshot = ProblemSnapshot(submission=submission, normalized_url=submission.problem_url)
            db.session.add(snapshot)
        snapshot.fetch_error = str(exc)
        db.session.commit()
        return "failed"


def _get_submission(public_id: str) -> Submission | None:
    return Submission.query.filter_by(public_id=public_id).first()


def _fetch_failure_message(submission: Submission) -> str:
    snapshot = submission.problem_snapshot
    if snapshot and snapshot.fetch_error:
        return f"抓取题面失败：{snapshot.fetch_error}"
    return "抓取题面失败：未获取到题面内容。"


def _fetch_idempotency_key(submission: Submission) -> str:
    digest = hashlib.sha256(submission.problem_url.encode("utf-8")).hexdigest()[:16]
    return f"fetch:{submission.public_id}:{digest}"


def _diagnosis_idempotency_key(submission: Submission) -> str:
    marker = submission.created_at.isoformat()
    digest = hashlib.sha256(f"{submission.public_id}:{marker}".encode("utf-8")).hexdigest()[:16]
    return f"diagnose:{submission.public_id}:{digest}"


def _student_hint_idempotency_key(submission: Submission) -> str:
    marker = submission.created_at.isoformat()
    digest = hashlib.sha256(f"student:{submission.public_id}:{marker}".encode("utf-8")).hexdigest()[:16]
    return f"student-hint:{submission.public_id}:{digest}"


def _ai_config() -> dict[str, str]:
    return {
        "api_key": str(
            current_app.config.get("AI_API_KEY") or current_app.config.get("DEEPSEEK_API_KEY") or ""
        ).strip(),
        "base_url": str(
            current_app.config.get("AI_BASE_URL")
            or current_app.config.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        ).strip(),
        "model_name": _ai_model_name(),
    }


def _ai_model_name() -> str:
    return str(
        current_app.config.get("AI_MODEL")
        or current_app.config.get("DEEPSEEK_MODEL")
        or "deepseek-v4-pro"
    ).strip()
