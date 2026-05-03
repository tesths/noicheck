from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Submission
from ..services.auth import (
    authenticate_student,
    current_student,
    hash_client_ip,
    login_student,
    logout_student,
    student_login_required,
)
from ..services.job_queue import JobMessage, JobQueueError, enqueue_job
from ..services.problem_fetcher import ProblemFetchError, normalize_openjudge_url

student_bp = Blueprint("student", __name__, url_prefix="/student")


def _validate_submission_form(problem_url: str, code_text: str) -> list[str]:
    errors: list[str] = []
    if not problem_url:
        errors.append("请输入题目链接。")
    if not code_text:
        errors.append("请输入代码。")
    if len(problem_url) > 500:
        errors.append("题目链接长度不能超过 500 个字符。")
    if len(code_text) > current_app.config["SUBMISSION_CODE_MAX_LENGTH"]:
        errors.append("代码长度超出系统限制。")
    return errors


def _build_submission(student_id: int, student_name: str, problem_url: str, code_text: str):
    return Submission(
        student_name=student_name,
        student_user_id=student_id,
        problem_url=problem_url,
        code_text=code_text,
        language="cpp",
        fetch_status="queued",
        student_hint_status="queued",
        diagnosis_status="pending",
        client_ip_hash=hash_client_ip(request.headers.get("X-Forwarded-For", request.remote_addr)),
    )


@student_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_student() is not None:
        return redirect(url_for("student.submissions"))

    if request.method == "GET":
        return render_template("student/login.html")

    nickname = request.form.get("nickname", "").strip()
    password = request.form.get("password", "")
    student = authenticate_student(nickname, password)
    if student is None:
        flash("昵称或密码错误。", "error")
        return render_template("student/login.html", nickname=nickname), 401

    login_student(student)
    db.session.commit()
    return redirect(url_for("student.submissions"))


@student_bp.post("/logout")
@student_login_required
def logout():
    logout_student()
    flash("已退出学生端。", "success")
    return redirect(url_for("student.login"))


@student_bp.get("/submissions")
@student_login_required
def submissions():
    student = current_student()
    submissions = (
        Submission.query.filter_by(student_user_id=student.id).order_by(Submission.created_at.desc()).all()
    )
    return render_template("student/submissions.html", student=student, submissions=submissions)


@student_bp.route("/submissions/new", methods=["GET", "POST"])
@student_login_required
def submission_new():
    student = current_student()
    if request.method == "GET":
        return render_template("student/submission_new.html", student=student)

    form_data = {
        "problem_url": request.form.get("problem_url", "").strip(),
        "code_text": request.form.get("code_text", "").strip(),
    }
    errors = _validate_submission_form(form_data["problem_url"], form_data["code_text"])
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("student/submission_new.html", student=student, form_data=form_data), 400

    try:
        normalized_problem_url = normalize_openjudge_url(form_data["problem_url"])
    except ProblemFetchError as exc:
        flash(str(exc), "error")
        return render_template("student/submission_new.html", student=student, form_data=form_data), 400

    submission = _build_submission(
        student_id=student.id,
        student_name=student.nickname,
        problem_url=normalized_problem_url,
        code_text=form_data["code_text"],
    )
    try:
        db.session.add(submission)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存提交记录时失败，请稍后再试。", "error")
        return render_template("student/submission_new.html", student=student, form_data=form_data), 500

    try:
        enqueue_job(
            JobMessage(
                job_type="fetch-and-student-diagnose",
                submission_public_id=submission.public_id,
                requested_by="student",
            )
        )
    except (JobQueueError, SQLAlchemyError):
        db.session.rollback()
        current_app.logger.exception("学生提交后排队抓题和提示失败")
        flash("提交记录已保存，但后台分析排队失败，请稍后重试或联系老师。", "error")
        return render_template("student/submission_new.html", student=student, form_data=form_data), 500

    return redirect(url_for("student.submission_detail", public_id=submission.public_id))


@student_bp.get("/submissions/<public_id>")
@student_login_required
def submission_detail(public_id: str):
    student = current_student()
    submission = Submission.query.filter_by(public_id=public_id, student_user_id=student.id).first_or_404()
    return render_template("student/submission_detail.html", student=student, submission=submission)
