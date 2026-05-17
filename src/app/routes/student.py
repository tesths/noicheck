import json
import secrets
import time

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Submission
from ..services.ai import DeepSeekDiagnosisService
from ..services.auth import (
    authenticate_student,
    current_student,
    hash_client_ip,
    login_student,
    logout_student,
    student_login_required,
)
from ..services.job_queue import JobQueueError
from ..services.jobs import enqueue_diagnosis_job, enqueue_student_hint_job
from ..services.pagination import normalize_page, paginate_query
from ..services.problem_fetcher import ProblemFetchError, normalize_openjudge_url
from ..services.settings import get_student_system_prompt
from ..services.student_followups import (
    DiagnosisServiceError,
    FOLLOWUP_POLICY_REFUSAL_TEXT,
    create_student_followup_exchange,
    prepare_student_followup,
    record_followup_exchange,
    validate_followup_form,
)

student_bp = Blueprint("student", __name__, url_prefix="/student")


def _page_url(page: int | None) -> str | None:
    if page is None:
        return None

    params = request.args.to_dict(flat=True)
    if page <= 1:
        params.pop("page", None)
    else:
        params["page"] = str(page)
    return url_for(request.endpoint, **(request.view_args or {}), **params)


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


def _build_submission(
    student_id: int,
    student_name: str,
    problem_url: str,
    code_text: str,
    *,
    request_token: str,
    submission_mode: str,
):
    return Submission(
        student_name=student_name,
        student_user_id=student_id,
        problem_url=problem_url,
        code_text=code_text,
        language="cpp",
        request_token=request_token,
        submission_mode=submission_mode,
        fetch_status="pending",
        student_hint_status="pending",
        diagnosis_status="pending",
        client_ip_hash=hash_client_ip(request.headers.get("X-Forwarded-For", request.remote_addr)),
    )


def _mode_copy(submission_mode: str) -> dict[str, str]:
    if submission_mode == "self_check":
        return {
            "eyebrow": "学生端 · 自己提交",
            "title": "提交给自己检查",
            "description": "系统会先抓题，再生成只给提示、不直接给答案的学生版 AI 引导。",
            "submit_label": "提交并获取 AI 提示",
            "submitting_label": "提交中，请稍候…",
        }
    return {
        "eyebrow": "学生端 · 提交给老师",
        "title": "提交给老师查看",
        "description": "系统会自动生成老师版完整诊断，包含修改建议和正确程序，但这些内容只在老师端可见。",
        "submit_label": "提交给老师",
        "submitting_label": "提交中，请稍候…",
    }


def _new_request_token() -> str:
    return secrets.token_urlsafe(18)


def _render_submission_form(*, student, submission_mode: str, form_data=None, status_code: int = 200):
    request_token = ""
    if form_data is not None:
        request_token = str(form_data.get("request_token", "")).strip()
    if not request_token:
        request_token = _new_request_token()

    rendered = render_template(
        "student/submission_form.html",
        student=student,
        submission_mode=submission_mode,
        form_data=form_data,
        mode_copy=_mode_copy(submission_mode),
        request_token=request_token,
    )
    if status_code == 200:
        return rendered
    return rendered, status_code


def _existing_submission_for_request(*, student_id: int, request_token: str) -> Submission | None:
    if not request_token:
        return None
    return Submission.query.filter_by(
        student_user_id=student_id,
        request_token=request_token,
        deleted_at=None,
    ).first()


def _student_submission_detail_query(*, student_id: int, public_id: str):
    return Submission.query.filter_by(
        public_id=public_id,
        student_user_id=student_id,
        deleted_at=None,
    )


def _render_submission_detail(
    *,
    student,
    submission: Submission,
    followup_form_data=None,
    followup_drawer_open: bool | None = None,
    status_code: int = 200,
):
    rendered = render_template(
        "student/submission_detail.html",
        student=student,
        submission=submission,
        followup_form_data=followup_form_data,
        followup_drawer_open=_followup_drawer_open_value(followup_drawer_open),
    )
    if status_code == 200:
        return rendered
    return rendered, status_code


def _followup_drawer_open_value(explicit_value: bool | None = None) -> bool:
    if explicit_value is not None:
        return explicit_value
    return request.args.get("followup", "").strip().lower() == "open"


def _wants_stream_response() -> bool:
    accept_header = request.headers.get("Accept", "")
    return "text/event-stream" in accept_header


def _wants_json_response() -> bool:
    accept_header = request.headers.get("Accept", "")
    return not _wants_stream_response() and "application/json" in accept_header


def _render_followup_history(submission: Submission) -> str:
    return render_template(
        "_followup_history.html",
        followup_session=submission.followup_session,
        followup_empty_text="学生还没有继续追问。",
    )


def _sse_event(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_response(event_name: str, payload: dict[str, object]) -> Response:
    return Response(
        _sse_event(event_name, payload),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _create_student_submission(*, submission_mode: str):
    student = current_student()
    form_data = {
        "request_token": request.form.get("request_token", "").strip(),
        "problem_url": request.form.get("problem_url", "").strip(),
        "code_text": request.form.get("code_text", "").strip(),
    }
    if not form_data["request_token"]:
        flash("提交页面已过期，请刷新后再试。", "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=400,
        )

    errors = _validate_submission_form(form_data["problem_url"], form_data["code_text"])
    if errors:
        for error in errors:
            flash(error, "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=400,
        )

    try:
        normalized_problem_url = normalize_openjudge_url(form_data["problem_url"])
    except ProblemFetchError as exc:
        flash(str(exc), "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=400,
        )

    submission = _build_submission(
        student_id=student.id,
        student_name=student.nickname,
        problem_url=normalized_problem_url,
        code_text=form_data["code_text"],
        request_token=form_data["request_token"],
        submission_mode=submission_mode,
    )
    try:
        db.session.add(submission)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing_submission = _existing_submission_for_request(
            student_id=student.id,
            request_token=form_data["request_token"],
        )
        if existing_submission is not None:
            flash("请勿重复提交，已打开你刚才那条记录。", "info")
            return redirect(url_for("student.submission_detail", public_id=existing_submission.public_id))
        flash("保存提交记录时失败，请稍后再试。", "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=500,
        )
    except SQLAlchemyError:
        db.session.rollback()
        flash("保存提交记录时失败，请稍后再试。", "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=500,
        )

    submission_public_id = submission.public_id
    try:
        if submission_mode == "self_check":
            enqueue_student_hint_job(submission, requested_by="student")
        else:
            enqueue_diagnosis_job(submission, requested_by="student")
    except (JobQueueError, SQLAlchemyError):
        db.session.rollback()
        current_app.logger.exception("学生提交后排队后台任务失败")
        flash("提交记录已保存，但后台分析排队失败，请稍后重试或联系老师。", "error")
        return _render_submission_form(
            student=student,
            submission_mode=submission_mode,
            form_data=form_data,
            status_code=500,
        )

    return redirect(url_for("student.submission_detail", public_id=submission_public_id))


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
    pagination = paginate_query(
        Submission.query.filter_by(student_user_id=student.id, deleted_at=None)
        .order_by(Submission.created_at.desc()),
        page=normalize_page(request.args.get("page")),
    )
    return render_template(
        "student/submissions.html",
        student=student,
        submissions=pagination.items,
        pagination=pagination,
        prev_page_url=_page_url(pagination.prev_page),
        next_page_url=_page_url(pagination.next_page),
    )


@student_bp.get("/submissions/new")
@student_login_required
def submission_new():
    student = current_student()
    return render_template("student/submission_new.html", student=student)


@student_bp.route("/submissions/new/self-check", methods=["GET", "POST"])
@student_login_required
def submission_new_self_check():
    student = current_student()
    if request.method == "GET":
        return _render_submission_form(student=student, submission_mode="self_check")
    return _create_student_submission(submission_mode="self_check")


@student_bp.route("/submissions/new/teacher-review", methods=["GET", "POST"])
@student_login_required
def submission_new_teacher_review():
    student = current_student()
    if request.method == "GET":
        return _render_submission_form(student=student, submission_mode="teacher_review")
    return _create_student_submission(submission_mode="teacher_review")


@student_bp.get("/submissions/<public_id>")
@student_login_required
def submission_detail(public_id: str):
    student = current_student()
    submission = _student_submission_detail_query(student_id=student.id, public_id=public_id).first_or_404()
    return _render_submission_detail(
        student=student,
        submission=submission,
        followup_drawer_open=_followup_drawer_open_value(),
    )


@student_bp.post("/submissions/<public_id>/follow-ups")
@student_login_required
def submission_followup(public_id: str):
    student = current_student()
    submission = _student_submission_detail_query(student_id=student.id, public_id=public_id).first_or_404()
    form_data = {
        "question_text": request.form.get("question_text", "").strip(),
        "context_label": request.form.get("context_label", "").strip(),
        "context_text": request.form.get("context_text", "").strip(),
    }

    errors = validate_followup_form(
        form_data["question_text"],
        form_data["context_label"],
        form_data["context_text"],
    )
    if errors:
        if _wants_stream_response():
            return _sse_response("error", {"error": errors[0]})
        if _wants_json_response():
            return jsonify({"ok": False, "error": errors[0]}), 400
        for error in errors:
            flash(error, "error")
        return _render_submission_detail(
            student=student,
            submission=submission,
            followup_form_data=form_data,
            followup_drawer_open=True,
            status_code=400,
        )

    if _wants_stream_response():
        try:
            preparation = prepare_student_followup(
                submission,
                question_text=form_data["question_text"],
                context_label=form_data["context_label"],
                context_text=form_data["context_text"],
            )
        except ValueError as exc:
            db.session.rollback()
            return _sse_response("error", {"error": str(exc)})

        def generate():
            if preparation.policy_refusal_text:
                try:
                    response = record_followup_exchange(
                        submission,
                        preparation=preparation,
                        student_content=form_data["question_text"],
                        context_label=form_data["context_label"],
                        context_text=form_data["context_text"],
                        assistant_content=FOLLOWUP_POLICY_REFUSAL_TEXT,
                        latency_ms=0,
                    )
                    yield _sse_event("delta", {"text": response.answer_text})
                    yield _sse_event(
                        "complete",
                        {
                            "ok": True,
                            "answer_text": response.answer_text,
                            "model_name": response.model_name,
                            "messages_html": _render_followup_history(submission),
                            "clear_form": True,
                        },
                    )
                except SQLAlchemyError:
                    db.session.rollback()
                    current_app.logger.exception("学生追问记录保存失败")
                    yield _sse_event("error", {"error": "保存追问记录失败，请稍后再试。"})
                return

            ai_config = {
                "api_key": str(
                    current_app.config.get("AI_API_KEY") or current_app.config.get("DEEPSEEK_API_KEY") or ""
                ).strip(),
                "base_url": str(
                    current_app.config.get("AI_BASE_URL")
                    or current_app.config.get("DEEPSEEK_BASE_URL")
                    or "https://api.deepseek.com"
                ).strip(),
            }
            service = DeepSeekDiagnosisService(
                api_key=ai_config["api_key"],
                base_url=ai_config["base_url"],
                model_name=preparation.model_name,
                student_system_prompt=get_student_system_prompt(),
            )

            chunks: list[str] = []
            started_at = time.perf_counter()
            try:
                for chunk in service.stream_student_followup(preparation.payload):
                    chunks.append(chunk)
                    yield _sse_event("delta", {"text": chunk})

                answer_text = "".join(chunks).strip()
                if not answer_text:
                    raise DiagnosisServiceError("模型没有返回可展示的追问回答。")

                response = record_followup_exchange(
                    submission,
                    preparation=preparation,
                    student_content=form_data["question_text"],
                    context_label=form_data["context_label"],
                    context_text=form_data["context_text"],
                    assistant_content=answer_text,
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )
                yield _sse_event(
                    "complete",
                    {
                        "ok": True,
                        "answer_text": response.answer_text,
                        "model_name": response.model_name,
                        "messages_html": _render_followup_history(submission),
                        "clear_form": True,
                    },
                )
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("学生追问记录保存失败")
                yield _sse_event("error", {"error": "保存追问记录失败，请稍后再试。"})
            except DiagnosisServiceError as exc:
                db.session.rollback()
                current_app.logger.exception("学生追问 AI 流式调用失败")
                yield _sse_event("error", {"error": str(exc)})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        response = create_student_followup_exchange(
            submission,
            question_text=form_data["question_text"],
            context_label=form_data["context_label"],
            context_text=form_data["context_text"],
        )
    except ValueError as exc:
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"ok": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return _render_submission_detail(
            student=student,
            submission=submission,
            followup_form_data=form_data,
            followup_drawer_open=True,
            status_code=400,
        )
    except SQLAlchemyError:
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"ok": False, "error": "保存追问记录失败，请稍后再试。"}), 500
        current_app.logger.exception("学生追问记录保存失败")
        flash("保存追问记录失败，请稍后再试。", "error")
        return _render_submission_detail(
            student=student,
            submission=submission,
            followup_form_data=form_data,
            followup_drawer_open=True,
            status_code=500,
        )
    except DiagnosisServiceError as exc:
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"ok": False, "error": str(exc)}), 502
        current_app.logger.exception("学生追问 AI 调用失败")
        flash(str(exc), "error")
        return _render_submission_detail(
            student=student,
            submission=submission,
            followup_form_data=form_data,
            followup_drawer_open=True,
            status_code=502,
        )

    if _wants_json_response():
        return jsonify(
            {
                "ok": True,
                "answer_text": response.answer_text,
                "model_name": response.model_name,
                "messages_html": _render_followup_history(submission),
                "clear_form": True,
            }
        )

    return redirect(f"{url_for('student.submission_detail', public_id=public_id, followup='open')}#followup-drawer")
