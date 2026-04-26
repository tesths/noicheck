from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import DiagnosisRun, ProblemSnapshot, Submission
from ..services.ai import DeepSeekDiagnosisService, DiagnosisPayload, DiagnosisServiceError, PROMPT_VERSION
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
    recent_count = Submission.query.filter(
        Submission.client_ip_hash == client_ip_hash,
        Submission.created_at >= window_start,
    ).count()
    return recent_count >= current_app.config["RATE_LIMIT_MAX_SUBMISSIONS"]


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

    submission = Submission(
        student_name=form_data["student_name"],
        problem_url=normalized_problem_url,
        code_text=form_data["code_text"],
        language="cpp",
        client_ip_hash=client_ip_hash,
        fetch_status="pending",
        diagnosis_status="pending",
    )
    db.session.add(submission)
    db.session.flush()

    fetcher = OpenJudgeProblemFetcher(timeout=current_app.config["OPENJUDGE_REQUEST_TIMEOUT"])
    try:
        problem = fetcher.fetch(normalized_problem_url)
        submission.problem_url = problem.normalized_url
        submission.problem_path = problem.problem_path
        submission.problem_title = problem.title
        submission.fetch_status = "success"
        db.session.add(
            ProblemSnapshot(
                submission=submission,
                normalized_url=problem.normalized_url,
                title=problem.title,
                description_text=problem.description_text,
                input_text=problem.input_text,
                output_text=problem.output_text,
                sample_input_text=problem.sample_input_text,
                sample_output_text=problem.sample_output_text,
                source_text=problem.source_text,
                raw_excerpt=problem.raw_excerpt,
            )
        )
    except ProblemFetchError as exc:
        submission.fetch_status = "failed"
        db.session.add(
            ProblemSnapshot(
                submission=submission,
                normalized_url=normalized_problem_url,
                fetch_error=str(exc),
            )
        )

    db.session.flush()

    diagnosis_service = DeepSeekDiagnosisService(
        api_key=current_app.config["DEEPSEEK_API_KEY"],
        base_url=current_app.config["DEEPSEEK_BASE_URL"],
        model_name=current_app.config["DEEPSEEK_MODEL"],
    )
    try:
        submission.diagnosis_status = "running"
        db.session.flush()
        snapshot = submission.problem_snapshot
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
    except DiagnosisServiceError as exc:
        submission.diagnosis_status = "failed"
        db.session.add(
            DiagnosisRun(
                submission=submission,
                model_name=current_app.config["DEEPSEEK_MODEL"],
                prompt_version=PROMPT_VERSION,
                status="failed",
                error_message=str(exc),
            )
        )

    db.session.commit()
    return redirect(url_for("public.submit_success", public_id=submission.public_id))


@public_bp.get("/submit/success/<public_id>")
def submit_success(public_id: str):
    submission = Submission.query.filter_by(public_id=public_id).first_or_404()
    return render_template("submit_success.html", submission=submission)
