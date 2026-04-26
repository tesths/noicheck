from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import DiagnosisRun, ProblemSnapshot, Submission
from ..services.ai import DeepSeekDiagnosisService, DiagnosisPayload, DiagnosisServiceError, PROMPT_VERSION
from ..services.auth import authenticate_admin, login_admin
from ..services.problem_fetcher import OpenJudgeProblemFetcher, ProblemFetchError

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
    diagnosis_service = DeepSeekDiagnosisService(
        api_key=current_app.config["DEEPSEEK_API_KEY"],
        base_url=current_app.config["DEEPSEEK_BASE_URL"],
        model_name=current_app.config["DEEPSEEK_MODEL"],
    )

    try:
        submission.diagnosis_status = "running"
        db.session.commit()

        snapshot = submission.problem_snapshot
        if submission.fetch_status != "success":
            fetcher = OpenJudgeProblemFetcher(timeout=current_app.config["OPENJUDGE_REQUEST_TIMEOUT"])
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
                submission.diagnosis_status = "failed"
                if snapshot is None:
                    snapshot = ProblemSnapshot(submission=submission, normalized_url=submission.problem_url)
                    db.session.add(snapshot)
                snapshot.fetch_error = str(exc)
                db.session.add(
                    DiagnosisRun(
                        submission=submission,
                        model_name=current_app.config["DEEPSEEK_MODEL"],
                        prompt_version=PROMPT_VERSION,
                        status="failed",
                        error_message=f"抓取题面失败：{exc}",
                    )
                )
                db.session.commit()
                flash(f"抓取题面失败：{exc}", "error")
                return redirect(url_for("admin.submission_detail", public_id=public_id))
            db.session.commit()

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
        flash("AI 诊断已生成。", "success")
    except (DiagnosisServiceError, SQLAlchemyError) as exc:
        db.session.rollback()
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
        flash(f"AI 诊断生成失败：{exc}", "error")

    return redirect(url_for("admin.submission_detail", public_id=public_id))
