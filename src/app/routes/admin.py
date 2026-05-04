from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import StudentUser, Submission
from ..services.auth import (
    authenticate_admin,
    ensure_student_user,
    hash_password,
    login_admin,
    logout_admin,
)
from ..services.job_queue import JobQueueError
from ..services.jobs import enqueue_diagnosis_job
from ..services.pagination import paginate_query, normalize_page
from ..services.settings import (
    ALLOWED_AI_MODELS,
    get_active_ai_model,
    get_student_system_prompt,
    get_teacher_system_prompt,
    set_ai_prompts,
    set_active_ai_model,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _student_list_query():
    return StudentUser.query.order_by(StudentUser.created_at.desc())


def _submission_list_query():
    return Submission.query.filter(Submission.deleted_at.is_(None)).order_by(Submission.created_at.desc())


def _selected_student_id() -> int | None:
    raw_value = request.args.get("student_user_id", "").strip()
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _page_url(page: int | None) -> str | None:
    if page is None:
        return None

    params = request.args.to_dict(flat=True)
    if page <= 1:
        params.pop("page", None)
    else:
        params["page"] = str(page)
    return url_for(request.endpoint, **(request.view_args or {}), **params)


def _admin_return_to_url() -> str | None:
    raw_value = request.values.get("next", "").strip()
    if not raw_value:
        return None

    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/admin/"):
        return None
    return raw_value


def _render_submission_list(*, student: StudentUser | None = None):
    selected_student_id = student.id if student else _selected_student_id()
    query = _submission_list_query()
    if selected_student_id is not None:
        query = query.filter_by(student_user_id=selected_student_id)
    pagination = paginate_query(query, page=normalize_page(request.args.get("page")))
    return render_template(
        "admin/submissions.html",
        submissions=pagination.items,
        students=_student_list_query().all(),
        selected_student_user_id=selected_student_id,
        student_page=student,
        pagination=pagination,
        prev_page_url=_page_url(pagination.prev_page),
        next_page_url=_page_url(pagination.next_page),
        detail_return_to=request.full_path.removesuffix("?"),
    )


def _submission_detail_query(public_id: str):
    return Submission.query.filter_by(public_id=public_id, deleted_at=None)


def _settings_page_context(
    *,
    teacher_system_prompt: str | None = None,
    student_system_prompt: str | None = None,
) -> dict[str, object]:
    return {
        "active_ai_model": get_active_ai_model(),
        "allowed_ai_models": ALLOWED_AI_MODELS,
        "teacher_system_prompt": teacher_system_prompt or get_teacher_system_prompt(),
        "student_system_prompt": student_system_prompt or get_student_system_prompt(),
    }


def _student_redirect_response(student_id: int):
    if request.form.get("return_to", "").strip() == "detail":
        return redirect(url_for("admin.student_detail", student_id=student_id))
    return redirect(url_for("admin.student_list"))


def _delete_redirect_response():
    return_to = _admin_return_to_url()
    if return_to:
        return redirect(return_to)

    student_id = request.form.get("student_id", "").strip()
    if student_id:
        return redirect(url_for("admin.student_submission_list", student_id=int(student_id)))

    selected_student_id = request.form.get("student_user_id", "").strip()
    if selected_student_id:
        return redirect(url_for("admin.submission_list", student_user_id=int(selected_student_id)))
    return redirect(url_for("admin.submission_list"))


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
    logout_admin()
    flash("已退出后台。", "success")
    return redirect(url_for("admin.login"))


@admin_bp.get("/submissions")
@login_required
def submission_list():
    return _render_submission_list()


@admin_bp.get("/students/<int:student_id>/submissions")
@login_required
def student_submission_list(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    return _render_submission_list(student=student)


@admin_bp.get("/submissions/<public_id>")
@login_required
def submission_detail(public_id: str):
    submission = _submission_detail_query(public_id).first_or_404()
    return render_template(
        "admin/submission_detail.html",
        submission=submission,
        return_url=_admin_return_to_url() or url_for("admin.submission_list"),
    )


@admin_bp.get("/submissions/<public_id>/student-view")
@login_required
def submission_student_view(public_id: str):
    submission = _submission_detail_query(public_id).first_or_404()
    if submission.student_user is None:
        abort(404)

    return render_template(
        "student/submission_detail.html",
        student=submission.student_user,
        submission=submission,
        viewer_mode="admin_preview",
        return_url=_admin_return_to_url() or url_for("admin.submission_list"),
    )


@admin_bp.get("/settings")
@login_required
def settings_page():
    return render_template("admin/settings.html", **_settings_page_context())


@admin_bp.post("/submissions/<public_id>/diagnose")
@login_required
def generate_diagnosis(public_id: str):
    submission = _submission_detail_query(public_id).first_or_404()
    return_to = _admin_return_to_url()
    try:
        enqueue_diagnosis_job(submission, requested_by="admin")
        flash("后台任务已入队，请刷新详情查看结果。", "success")
    except JobQueueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except SQLAlchemyError:
        db.session.rollback()
        flash("提交后台任务失败，请稍后再试。", "error")

    detail_url = url_for("admin.submission_detail", public_id=public_id)
    if return_to:
        detail_url = url_for("admin.submission_detail", public_id=public_id, next=return_to)
    return redirect(detail_url)


@admin_bp.post("/submissions/<public_id>/delete")
@login_required
def delete_submission(public_id: str):
    submission = _submission_detail_query(public_id).first_or_404()
    submission.mark_deleted()
    try:
        db.session.commit()
        flash("提交记录已删除。", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("删除提交记录失败，请稍后再试。", "error")
        return redirect(url_for("admin.submission_detail", public_id=public_id))
    return _delete_redirect_response()


@admin_bp.post("/settings/ai-model")
@login_required
def update_ai_model():
    model_name = request.form.get("model_name", "").strip()
    try:
        set_active_ai_model(model_name)
        db.session.commit()
        flash(f"当前模型已切换为 {model_name}。", "success")
    except ValueError:
        db.session.rollback()
        flash("只能切换到 deepseek-v4-flash 或 deepseek-v4-pro。", "error")
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存模型设置失败，请稍后再试。", "error")
    return redirect(url_for("admin.settings_page"))


@admin_bp.post("/settings/prompts")
@login_required
def update_ai_prompts():
    teacher_system_prompt = request.form.get("teacher_system_prompt", "").strip()
    student_system_prompt = request.form.get("student_system_prompt", "").strip()
    if not teacher_system_prompt or not student_system_prompt:
        flash("请填写老师和学生的系统提示词。", "error")
        return (
            render_template(
                "admin/settings.html",
                **_settings_page_context(
                    teacher_system_prompt=teacher_system_prompt,
                    student_system_prompt=student_system_prompt,
                ),
            ),
            400,
        )

    try:
        set_ai_prompts(
            teacher_system_prompt=teacher_system_prompt,
            student_system_prompt=student_system_prompt,
        )
        db.session.commit()
        flash("老师和学生的系统提示词已更新。", "success")
    except ValueError:
        db.session.rollback()
        flash("请填写老师和学生的系统提示词。", "error")
        return (
            render_template(
                "admin/settings.html",
                **_settings_page_context(
                    teacher_system_prompt=teacher_system_prompt,
                    student_system_prompt=student_system_prompt,
                ),
            ),
            400,
        )
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存系统提示词失败，请稍后再试。", "error")
    return redirect(url_for("admin.settings_page"))


@admin_bp.get("/students")
@login_required
def student_list():
    students = _student_list_query().all()
    return render_template("admin/students.html", students=students)


@admin_bp.get("/students/<int:student_id>")
@login_required
def student_detail(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    return render_template("admin/student_detail.html", student=student)


@admin_bp.post("/students")
@login_required
def create_student():
    nickname = request.form.get("nickname", "").strip()
    real_name = request.form.get("real_name", "").strip()
    password = request.form.get("password", "")
    if not nickname or not real_name or not password:
        flash("请填写学生用户名、真实姓名和密码。", "error")
        students = _student_list_query().all()
        return render_template(
            "admin/students.html",
            students=students,
            nickname=nickname,
            real_name=real_name,
        ), 400

    try:
        student = ensure_student_user(nickname=nickname, real_name=real_name, password=password)
        db.session.add(student)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存学生信息失败，请稍后再试。", "error")
        students = _student_list_query().all()
        return render_template(
            "admin/students.html",
            students=students,
            nickname=nickname,
            real_name=real_name,
        ), 500

    flash(f"学生 {real_name}（{nickname}）已保存。", "success")
    return redirect(url_for("admin.student_list"))


@admin_bp.post("/students/<int:student_id>/profile")
@login_required
def update_student_profile(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    real_name = request.form.get("real_name", "").strip()
    if not real_name:
        flash("请填写真实姓名。", "error")
        return redirect(url_for("admin.student_list"))

    student.real_name = real_name
    try:
        db.session.commit()
        flash(f"学生 {student.nickname} 的真实姓名已更新。", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("更新真实姓名失败，请稍后再试。", "error")
    return _student_redirect_response(student_id)


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
    return _student_redirect_response(student_id)


@admin_bp.post("/students/<int:student_id>/toggle-active")
@login_required
def toggle_student_active(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    student.is_active = not student.is_active
    db.session.commit()
    flash(f"学生 {student.nickname} 已{'启用' if student.is_active else '停用'}。", "success")
    return _student_redirect_response(student_id)


@admin_bp.post("/students/<int:student_id>/delete")
@login_required
def delete_student(student_id: int):
    student = StudentUser.query.filter_by(id=student_id).first_or_404()
    for submission in list(student.submissions):
        if submission.deleted_at is None:
            submission.mark_deleted()
        submission.student_user = None

    try:
        db.session.delete(student)
        db.session.commit()
        flash("学生账号已删除，关联提交已隐藏。", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("删除学生失败，请稍后再试。", "error")
        return redirect(url_for("admin.student_detail", student_id=student_id))
    return redirect(url_for("admin.student_list"))
