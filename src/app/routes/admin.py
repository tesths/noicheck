from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Submission
from ..services.auth import authenticate_admin, login_admin
from ..services.queue import QueueServiceError, enqueue_submission

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.submission_list"))

    if request.method == "GET":
        return render_template("admin/login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    admin = authenticate_admin(username, password)
    if admin is None:
        flash("用户名或密码错误。", "error")
        return render_template("admin/login.html", username=username), 401

    login_admin(admin)
    db.session.commit()
    return redirect(url_for("admin.submission_list"))


@admin_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("已退出后台。", "success")
    return redirect(url_for("admin.login"))


@admin_bp.get("/submissions")
@login_required
def submission_list():
    submissions = Submission.query.order_by(Submission.created_at.desc()).all()
    return render_template("admin/submissions.html", submissions=submissions)


@admin_bp.get("/submissions/<public_id>")
@login_required
def submission_detail(public_id: str):
    submission = Submission.query.filter_by(public_id=public_id).first_or_404()
    return render_template("admin/submission_detail.html", submission=submission)


@admin_bp.post("/submissions/<public_id>/diagnose")
@login_required
def generate_diagnosis(public_id: str):
    submission = Submission.query.filter_by(public_id=public_id).first_or_404()
    if submission.diagnosis_status == "running":
        flash("该提交已经在后台分析中。", "success")
        return redirect(url_for("admin.submission_detail", public_id=public_id))

    try:
        if submission.fetch_status == "failed":
            submission.fetch_status = "pending"
            if submission.problem_snapshot is not None:
                submission.problem_snapshot.fetch_error = None
        submission.diagnosis_status = "pending"
        db.session.flush()
        enqueue_submission(submission.public_id)
        db.session.commit()
        flash("已加入后台分析队列。", "success")
    except (QueueServiceError, SQLAlchemyError) as exc:
        db.session.rollback()
        current_app.logger.exception("加入后台分析队列失败")
        flash(f"加入后台分析队列失败：{exc}", "error")

    return redirect(url_for("admin.submission_detail", public_id=public_id))
