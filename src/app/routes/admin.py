from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import StudentUser, Submission
from ..services.auth import authenticate_admin, ensure_student_user, hash_password, login_admin
from ..services.job_queue import JobQueueError
from ..services.jobs import enqueue_diagnosis_job

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
    try:
        enqueue_diagnosis_job(submission, requested_by="admin")
        flash("后台任务已入队，请刷新详情查看结果。", "success")
    except JobQueueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except SQLAlchemyError:
        db.session.rollback()
        flash("提交后台任务失败，请稍后再试。", "error")

    return redirect(url_for("admin.submission_detail", public_id=public_id))


@admin_bp.get("/students")
@login_required
def student_list():
    students = StudentUser.query.order_by(StudentUser.created_at.desc()).all()
    return render_template("admin/students.html", students=students)


@admin_bp.post("/students")
@login_required
def create_student():
    nickname = request.form.get("nickname", "").strip()
    password = request.form.get("password", "")
    if not nickname or not password:
        flash("请填写学生昵称和密码。", "error")
        students = StudentUser.query.order_by(StudentUser.created_at.desc()).all()
        return render_template("admin/students.html", students=students, nickname=nickname), 400

    try:
        student = ensure_student_user(nickname=nickname, password=password)
        db.session.add(student)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存学生信息失败，请稍后再试。", "error")
        students = StudentUser.query.order_by(StudentUser.created_at.desc()).all()
        return render_template("admin/students.html", students=students, nickname=nickname), 500

    flash(f"学生 {nickname} 已保存。", "success")
    return redirect(url_for("admin.student_list"))


@admin_bp.post("/students/<int:student_id>/reset-password")
@login_required
def reset_student_password(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    password = request.form.get("password", "")
    if not password:
        flash("请填写新密码。", "error")
        return redirect(url_for("admin.student_list"))

    student.password_hash = hash_password(password)
    student.is_active = True
    db.session.commit()
    flash(f"学生 {student.nickname} 密码已重置。", "success")
    return redirect(url_for("admin.student_list"))


@admin_bp.post("/students/<int:student_id>/toggle-active")
@login_required
def toggle_student_active(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    student.is_active = not student.is_active
    db.session.commit()
    flash(f"学生 {student.nickname} 已{'启用' if student.is_active else '停用'}。", "success")
    return redirect(url_for("admin.student_list"))
