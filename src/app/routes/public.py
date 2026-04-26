from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Submission
from ..services.auth import hash_client_ip
from ..services.problem_fetcher import ProblemFetchError, normalize_openjudge_url

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
    try:
        db.session.add(submission)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存提交记录时失败，请稍后再试。", "error")
        return render_template("submit.html", form_data=form_data), 500

    return redirect(url_for("public.submit_success", public_id=submission.public_id))


@public_bp.get("/submit/success/<public_id>")
def submit_success(public_id: str):
    submission = Submission.query.filter_by(public_id=public_id).first_or_404()
    return render_template("submit_success.html", submission=submission)
