from __future__ import annotations

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import DiagnosisRun, ProblemSnapshot, Submission
from .ai import DeepSeekDiagnosisService, DiagnosisPayload, DiagnosisServiceError, PROMPT_VERSION
from .problem_fetcher import OpenJudgeProblemFetcher, ProblemFetchError


def process_pending_submissions(limit: int) -> dict[str, int]:
    statement = (
        select(Submission.public_id)
        .where(Submission.diagnosis_status == "pending")
        .order_by(Submission.created_at.asc(), Submission.id.asc())
        .limit(max(limit, 0))
    )
    public_ids = list(db.session.execute(statement).scalars())
    summary = {"selected": len(public_ids), "processed": 0, "failed": 0, "skipped": 0}

    for public_id in public_ids:
        outcome = process_submission(public_id)
        summary[outcome] += 1

    return summary


def process_submission(public_id: str) -> str:
    submission = _claim_submission(public_id)
    if submission is None:
        return "skipped"

    if _needs_problem_fetch(submission):
        try:
            _fetch_problem_snapshot(submission)
        except ProblemFetchError as exc:
            db.session.rollback()
            _mark_fetch_failure(public_id, str(exc))
            return "failed"
        except SQLAlchemyError as exc:
            db.session.rollback()
            _mark_diagnosis_failure(public_id, str(exc))
            return "failed"

    try:
        _run_diagnosis(public_id)
    except (DiagnosisServiceError, SQLAlchemyError) as exc:
        db.session.rollback()
        _mark_diagnosis_failure(public_id, str(exc))
        return "failed"

    return "processed"


def _claim_submission(public_id: str) -> Submission | None:
    statement = select(Submission).where(Submission.public_id == public_id).with_for_update()
    submission = db.session.execute(statement).scalar_one_or_none()
    if submission is None:
        db.session.rollback()
        return None
    if submission.diagnosis_status in {"running", "success"}:
        db.session.rollback()
        return None

    if _needs_problem_fetch(submission):
        submission.fetch_status = "running"
    submission.diagnosis_status = "running"
    db.session.commit()
    return submission


def _needs_problem_fetch(submission: Submission) -> bool:
    snapshot = submission.problem_snapshot
    return submission.fetch_status != "success" or snapshot is None or bool(snapshot.fetch_error)


def _fetch_problem_snapshot(submission: Submission) -> None:
    fetcher = OpenJudgeProblemFetcher(timeout=float(current_app.config["OPENJUDGE_REQUEST_TIMEOUT"]))
    problem = fetcher.fetch(submission.problem_url)

    snapshot = submission.problem_snapshot
    if snapshot is None:
        snapshot = ProblemSnapshot(submission=submission, normalized_url=problem.normalized_url)
        db.session.add(snapshot)

    submission.problem_url = problem.normalized_url
    submission.problem_path = problem.problem_path
    submission.problem_title = problem.title
    submission.fetch_status = "success"

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


def _run_diagnosis(public_id: str) -> None:
    submission = Submission.query.filter_by(public_id=public_id).first()
    if submission is None:
        return

    snapshot = submission.problem_snapshot
    diagnosis_service = DeepSeekDiagnosisService(
        api_key=current_app.config["DEEPSEEK_API_KEY"],
        base_url=current_app.config["DEEPSEEK_BASE_URL"],
        model_name=current_app.config["DEEPSEEK_MODEL"],
    )
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
            model_name=diagnosis.model_name,
            prompt_version=PROMPT_VERSION,
            status="success",
            structured_result_json=diagnosis.result.model_dump(),
            summary_text=diagnosis.result.overall_assessment,
            latency_ms=diagnosis.latency_ms,
        )
    )
    db.session.commit()


def _mark_fetch_failure(public_id: str, error_message: str) -> None:
    submission = Submission.query.filter_by(public_id=public_id).first()
    if submission is None:
        return

    submission.fetch_status = "failed"
    submission.diagnosis_status = "failed"
    snapshot = submission.problem_snapshot
    if snapshot is None:
        snapshot = ProblemSnapshot(submission=submission, normalized_url=submission.problem_url)
        db.session.add(snapshot)
    snapshot.fetch_error = error_message
    db.session.add(
        DiagnosisRun(
            submission=submission,
            model_name=current_app.config["DEEPSEEK_MODEL"],
            prompt_version=PROMPT_VERSION,
            status="failed",
            error_message=f"抓取题面失败：{error_message}",
        )
    )
    db.session.commit()


def _mark_diagnosis_failure(public_id: str, error_message: str) -> None:
    submission = Submission.query.filter_by(public_id=public_id).first()
    if submission is None:
        return

    submission.diagnosis_status = "failed"
    db.session.add(
        DiagnosisRun(
            submission=submission,
            model_name=current_app.config["DEEPSEEK_MODEL"],
            prompt_version=PROMPT_VERSION,
            status="failed",
            error_message=error_message,
        )
    )
    db.session.commit()
