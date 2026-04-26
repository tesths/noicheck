from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from ..bootstrap import ensure_database_schema
from ..extensions import db
from ..models import ProblemSnapshot, Submission
from ..services.auth import hash_client_ip
from ..services.problem_fetcher import OpenJudgeProblemFetcher, ProblemFetchError, normalize_openjudge_url

public_bp = Blueprint("public", __name__)


def _validate_submission_form(form_data: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not form_data["student_name"]:
        errors.append("请输入学生姓名或昵称。")
    if not form_data["problem_url"]:
        errors.append("请输入题目链接。")
    if not form_data["code_text"]:
        errors.append("请输入代码。")
    if len(form_data["student_name"]) > 80:
        errors.append("学生姓名或昵称长度不能超过 80 个字符。")
    if len(form_data["problem_url"]) > 500:
        errors.append("题目链接长度不能超过 500 个字符。")
    if len(form_data["code_text"]) > current_app.config["SUBMISSION_CODE_MAX_LENGTH"]:
        errors.append("代码长度超出系统限制。")
    return errors


def _check_rate_limit(client_ip_hash: str | None) -> bool:
    if not client_ip_hash:
        return False

    window_start = datetime.now(timezone.utc) - timedelta(
        seconds=current_app.config["RATE_LIMIT_WINDOW_SECONDS"]
    )
    try:
        recent_count = _count_recent_submissions(client_ip_hash, window_start)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("查询提交频率失败，准备强制修复数据库后重试")
        ensure_database_schema(current_app, force=True)
        recent_count = _count_recent_submissions(client_ip_hash, window_start)
    return recent_count >= current_app.config["RATE_LIMIT_MAX_SUBMISSIONS"]


def _count_recent_submissions(client_ip_hash: str, window_start: datetime) -> int:
    statement = (
        select(func.count(Submission.id))
        .where(Submission.client_ip_hash == client_ip_hash)
        .where(Submission.created_at >= window_start)
    )
    return int(db.session.execute(statement).scalar_one())


def _build_submission(
    *,
    student_name: str,
    problem_url: str,
    code_text: str,
    client_ip_hash: str | None,
) -> Submission:
    return Submission(
        student_name=student_name,
        problem_url=problem_url,
        code_text=code_text,
        language="cpp",
        client_ip_hash=client_ip_hash,
        fetch_status="pending",
        diagnosis_status="pending",
    )


def _submission_write_state() -> dict[str, bool]:
    return current_app.extensions.setdefault("submission_write_state", {"explicit_id_mode": False})


def _allocate_submission_id() -> int:
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 310701})

    next_id = db.session.execute(select(func.coalesce(func.max(Submission.id), 0) + 1)).scalar_one()
    return int(next_id)


def _sync_submission_id_sequence_best_effort() -> None:
    if db.engine.dialect.name != "postgresql":
        return

    try:
        sequence_name = db.session.execute(
            text("SELECT pg_get_serial_sequence('submissions', 'id')")
        ).scalar()
        if not sequence_name:
            return

        db.session.execute(
            text(
                """
                SELECT setval(
                    CAST(:sequence_name AS regclass),
                    COALESCE((SELECT MAX(id) FROM submissions), 1),
                    true
                )
                """
            ),
            {"sequence_name": sequence_name},
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("同步 submissions.id 序列失败，后续提交将继续走显式主键兜底")


def _persist_submission_with_explicit_id(submission: Submission) -> Submission:
    retried_submission = _build_submission(
        student_name=submission.student_name,
        problem_url=submission.problem_url,
        code_text=submission.code_text,
        client_ip_hash=submission.client_ip_hash,
    )
    retried_submission.id = _allocate_submission_id()
    db.session.add(retried_submission)
    db.session.commit()

    _submission_write_state()["explicit_id_mode"] = True
    _sync_submission_id_sequence_best_effort()
    return retried_submission


def _persist_submission(submission: Submission) -> Submission:
    write_state = _submission_write_state()
    if write_state["explicit_id_mode"]:
        return _persist_submission_with_explicit_id(submission)

    try:
        db.session.add(submission)
        db.session.commit()
        return submission
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("保存提交记录失败，准备强制修复数据库后重试")

    try:
        ensure_database_schema(current_app, force=True)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("强制修复数据库失败，准备改用显式主键重试保存")

    retried_submission = _build_submission(
        student_name=submission.student_name,
        problem_url=submission.problem_url,
        code_text=submission.code_text,
        client_ip_hash=submission.client_ip_hash,
    )
    try:
        db.session.add(retried_submission)
        db.session.commit()
        return retried_submission
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("修表后再次保存仍失败，准备改用显式主键兜底")
        return _persist_submission_with_explicit_id(submission)

def _sync_problem_snapshot(submission: Submission) -> None:
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
    except ProblemFetchError as exc:
        submission.fetch_status = "failed"
        if snapshot is None:
            snapshot = ProblemSnapshot(submission=submission, normalized_url=submission.problem_url)
            db.session.add(snapshot)
        snapshot.fetch_error = str(exc)
    db.session.commit()


@public_bp.get("/")
def home():
    return redirect(url_for("public.submit"))


@public_bp.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "GET":
        return render_template("submit.html")

    form_data = {
        "student_name": request.form.get("student_name", "").strip(),
        "problem_url": request.form.get("problem_url", "").strip(),
        "code_text": request.form.get("code_text", "").strip(),
    }
    errors = _validate_submission_form(form_data)
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("submit.html", form_data=form_data), 400

    try:
        normalized_problem_url = normalize_openjudge_url(form_data["problem_url"])
    except ProblemFetchError as exc:
        flash(str(exc), "error")
        return render_template("submit.html", form_data=form_data), 400

    client_ip_hash = hash_client_ip(request.headers.get("X-Forwarded-For", request.remote_addr))
    if _check_rate_limit(client_ip_hash):
        flash("提交过于频繁，请稍后再试。", "error")
        return render_template("submit.html", form_data=form_data), 429

    submission = _build_submission(
        student_name=form_data["student_name"],
        problem_url=normalized_problem_url,
        code_text=form_data["code_text"],
        client_ip_hash=client_ip_hash,
    )
    try:
        submission = _persist_submission(submission)
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存提交记录时失败，请稍后再试。", "error")
        return render_template("submit.html", form_data=form_data), 500

    try:
        _sync_problem_snapshot(submission)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("提交后同步抓题失败，已保留提交记录")

    return redirect(url_for("public.submit_success", public_id=submission.public_id))


@public_bp.get("/submit/success/<public_id>")
def submit_success(public_id: str):
    submission = Submission.query.filter_by(public_id=public_id).first_or_404()
    return render_template("submit_success.html", submission=submission)
