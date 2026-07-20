from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.app import create_app
from src.app.extensions import db
from src.app.models import AdminUser, ProblemSnapshot, StudentUser, Submission, SystemSetting
from src.app.routes import public as public_routes
from src.app.services.auth import (
    ACTIVE_ROLE_SESSION_KEY,
    ADMIN_ROLE,
    STUDENT_ROLE,
    current_student,
    hash_password,
    load_user,
)
from src.app.services.job_queue import JobMessage, JobQueueError, enqueue_job
from src.app.services.problem_fetcher import ProblemFetchError


def _login_admin(client, username="admin", password="secret123") -> None:
    response = client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _login_student(client, nickname="stu01", password="pw-1") -> None:
    response = client.post(
        "/student/login",
        data={"nickname": nickname, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_public_submission_helpers_validate_and_clone_legacy_submission(app):
    with app.app_context():
        app.config["SUBMISSION_CODE_MAX_LENGTH"] = 6
        errors = public_routes._validate_submission_form(
            {
                "student_name": "",
                "problem_url": "",
                "code_text": "1234567",
            }
        )
        assert "请输入学生姓名或昵称。" in errors
        assert "请输入题目链接。" in errors
        assert "代码长度超出系统限制。" in errors

        submission = public_routes._build_submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            client_ip_hash="hash-1",
        )
        submission.problem_title = "01:统计数字字符个数"
        submission.problem_path = "ch0107/01"
        submission.student_user_id = 7
        submission.fetch_status = "success"
        submission.student_hint_status = "failed"
        submission.diagnosis_status = "queued"

        cloned = public_routes._clone_submission_for_retry(submission)

        assert cloned is not submission
        assert cloned.student_name == "小明"
        assert cloned.problem_title == "01:统计数字字符个数"
        assert cloned.problem_path == "ch0107/01"
        assert cloned.student_user_id == 7
        assert cloned.submission_mode == "teacher_review"
        assert cloned.fetch_status == "success"
        assert cloned.student_hint_status == "failed"
        assert cloned.diagnosis_status == "queued"


def test_public_rate_limit_retries_after_schema_repair(app, monkeypatch):
    calls = []

    def fake_count(client_ip_hash, window_start):
        calls.append((client_ip_hash, window_start))
        if len(calls) == 1:
            raise SQLAlchemyError("missing column")
        return 20

    repairs = []

    monkeypatch.setattr(public_routes, "_count_recent_submissions", fake_count)
    monkeypatch.setattr(public_routes, "ensure_database_schema", lambda app, force=False: repairs.append(force))

    with app.app_context():
        app.config["RATE_LIMIT_MAX_SUBMISSIONS"] = 20

        assert public_routes._check_rate_limit(None) is False
        assert public_routes._check_rate_limit("ip-hash") is True

    assert repairs == [True]
    assert len(calls) == 2


def test_public_persist_submission_explicit_id_mode_uses_next_available_id(app):
    with app.app_context():
        first = public_routes._persist_submission(
            public_routes._build_submission(
                student_name="甲",
                problem_url="http://noi.openjudge.cn/ch0107/01/",
                code_text="int main(){}",
                client_ip_hash="ip-1",
            )
        )
        public_routes._submission_write_state()["explicit_id_mode"] = True
        second = public_routes._persist_submission(
            public_routes._build_submission(
                student_name="乙",
                problem_url="http://noi.openjudge.cn/ch0107/02/",
                code_text="int main(){return 1;}",
                client_ip_hash="ip-2",
            )
        )

        assert first.id == 1
        assert second.id == 2
        assert public_routes._submission_write_state()["explicit_id_mode"] is True
        assert Submission.query.count() == 2


def test_public_sync_problem_snapshot_delegates_to_diagnosis_queue(app, monkeypatch):
    queued = []
    submission = Submission(
        student_name="小明",
        problem_url="http://noi.openjudge.cn/ch0107/01/",
        code_text="int main(){}",
    )

    monkeypatch.setattr(
        public_routes,
        "enqueue_diagnosis_job",
        lambda submission, requested_by: queued.append((submission.public_id, requested_by)),
    )

    with app.app_context():
        db.session.add(submission)
        db.session.commit()
        public_routes._sync_problem_snapshot(submission)

        assert queued == [(submission.public_id, "system")]


def test_auth_load_user_and_current_student_handle_invalid_or_inactive_sessions(app):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"), is_active=False)
        db.session.add_all([admin, student])
        db.session.commit()
        admin_id = admin.id
        student_id = student.id

    with app.test_request_context("/"):
        assert load_user("not-an-id") is None
        assert load_user(str(admin_id)).username == "admin"

    with app.test_request_context("/"):
        from flask import session

        session["student_user_id"] = student_id
        assert current_student() is None
        assert "student_user_id" not in session


def test_exclusive_login_recovers_role_from_legacy_sessions(app, client):
    with client.session_transaction() as session:
        session["_user_id"] = "1"
        session["student_user_id"] = 2

    response = client.get("/")

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session[ACTIVE_ROLE_SESSION_KEY] == ADMIN_ROLE
        assert "student_user_id" not in session

    with client.session_transaction() as session:
        session.clear()
        session["student_user_id"] = 2

    response = client.get("/")

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session[ACTIVE_ROLE_SESSION_KEY] == STUDENT_ROLE


def test_admin_login_failure_and_authenticated_redirect(app, client):
    with app.app_context():
        db.session.add(AdminUser(username="admin", password_hash=hash_password("secret123")))
        db.session.commit()

    bad_login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert bad_login.status_code == 401

    _login_admin(client)
    already_logged_in = client.get("/admin/login", follow_redirects=False)
    logout = client.post("/admin/logout", follow_redirects=False)

    assert already_logged_in.status_code == 302
    assert already_logged_in.headers["Location"].endswith("/admin/submissions")
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/admin/login")


def test_admin_rejects_student_owned_by_another_teacher(app, client):
    with app.app_context():
        owner = AdminUser(username="owner", password_hash=hash_password("secret123"))
        other = AdminUser(username="other", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=other, nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([owner, other, student])
        db.session.commit()

    _login_admin(client, username="owner")
    response = client.post(
        "/admin/students",
        data={"nickname": "stu01", "real_name": "张小明", "password": "pw-2"},
    )

    assert response.status_code == 400
    assert "该学生用户名已被其他老师占用".encode() in response.data


def test_admin_student_forms_reject_missing_inputs(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=admin, nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()
        student_id = student.id

    _login_admin(client)

    create_response = client.post(
        "/admin/students",
        data={"nickname": "", "real_name": "张小明", "password": ""},
    )
    profile_response = client.post(
        f"/admin/students/{student_id}/profile",
        data={"real_name": ""},
        follow_redirects=False,
    )
    reset_response = client.post(
        f"/admin/students/{student_id}/reset-password",
        data={"password": ""},
        follow_redirects=False,
    )

    assert create_response.status_code == 400
    assert profile_response.status_code == 302
    assert profile_response.headers["Location"].endswith("/admin/students")
    assert reset_response.status_code == 302
    assert reset_response.headers["Location"].endswith("/admin/students")


def test_admin_generate_diagnosis_handles_queue_and_database_errors(app, client, monkeypatch):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=admin, nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(student_name="stu01", student_user=student, problem_url="http://noi.openjudge.cn/ch0107/01/", code_text="int main(){}")
        db.session.add_all([admin, student, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    monkeypatch.setattr("src.app.routes.admin.enqueue_diagnosis_job", lambda *args, **kwargs: (_ for _ in ()).throw(JobQueueError("queue down")))
    queue_response = client.post(f"/admin/submissions/{public_id}/diagnose", follow_redirects=True)

    monkeypatch.setattr("src.app.routes.admin.enqueue_diagnosis_job", lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("db down")))
    db_response = client.post(f"/admin/submissions/{public_id}/diagnose", follow_redirects=True)

    assert queue_response.status_code == 200
    assert "queue down".encode() in queue_response.data
    assert db_response.status_code == 200
    assert "提交后台任务失败".encode() in db_response.data


def test_admin_delete_submission_uses_safe_return_targets(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=admin, nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(student_name="stu01", student_user=student, problem_url="http://noi.openjudge.cn/ch0107/01/", code_text="int main(){}")
        db.session.add_all([admin, student, submission])
        db.session.commit()
        student_id = student.id
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        f"/admin/submissions/{public_id}/delete",
        data={"next": "https://evil.test/admin/submissions", "student_id": str(student_id)},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/students/{student_id}/submissions")


def test_admin_mutation_routes_report_database_errors(app, client, monkeypatch):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=admin, nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(student_name="stu01", student_user=student, problem_url="http://noi.openjudge.cn/ch0107/01/", code_text="int main(){}")
        db.session.add_all([admin, student, submission])
        db.session.commit()
        student_id = student.id
        public_id = submission.public_id

    _login_admin(client)

    def fail_commit():
        raise SQLAlchemyError("commit failed")

    monkeypatch.setattr("src.app.routes.admin.db.session.commit", fail_commit)

    delete_submission = client.post(f"/admin/submissions/{public_id}/delete", follow_redirects=False)
    update_profile = client.post(f"/admin/students/{student_id}/profile", data={"real_name": "新名字"}, follow_redirects=True)
    delete_student = client.post(f"/admin/students/{student_id}/delete", follow_redirects=False)

    assert delete_submission.status_code == 302
    assert delete_submission.headers["Location"].endswith(f"/admin/submissions/{public_id}")
    assert update_profile.status_code == 200
    assert "更新真实姓名失败".encode() in update_profile.data
    assert delete_student.status_code == 302
    assert delete_student.headers["Location"].endswith(f"/admin/students/{student_id}")


def test_student_login_failure_redirect_and_logout(app, client):
    with app.app_context():
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add(student)
        db.session.commit()

    bad_login = client.post(
        "/student/login",
        data={"nickname": "stu01", "password": "wrong"},
        follow_redirects=False,
    )
    assert bad_login.status_code == 401

    _login_student(client)
    already_logged_in = client.get("/student/login", follow_redirects=False)
    logout = client.post("/student/logout", follow_redirects=False)

    assert already_logged_in.status_code == 302
    assert already_logged_in.headers["Location"].endswith("/student/submissions")
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/student/login")


def test_student_submission_form_rejects_expired_blank_and_invalid_inputs(app, client):
    with app.app_context():
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add(student)
        db.session.commit()

    _login_student(client)

    expired = client.post(
        "/student/submissions/new/self-check",
        data={"request_token": "", "problem_url": "http://noi.openjudge.cn/ch0107/01/", "code_text": "int main(){}"},
    )
    blank = client.post(
        "/student/submissions/new/self-check",
        data={"request_token": "tok-1", "problem_url": "", "code_text": ""},
    )
    invalid = client.post(
        "/student/submissions/new/self-check",
        data={"request_token": "tok-2", "problem_url": "ftp://example.com/problem", "code_text": "int main(){}"},
    )

    assert expired.status_code == 400
    assert "提交页面已过期".encode() in expired.data
    assert blank.status_code == 400
    assert "请输入题目链接".encode() in blank.data
    assert invalid.status_code == 400
    assert "题目链接必须以 http 或 https 开头".encode() in invalid.data


def test_student_submission_queue_failure_reports_saved_record_problem(app, client, monkeypatch):
    with app.app_context():
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add(student)
        db.session.commit()

    _login_student(client)
    monkeypatch.setattr("src.app.routes.student.enqueue_student_hint_job", lambda *args, **kwargs: (_ for _ in ()).throw(JobQueueError("queue down")))

    response = client.post(
        "/student/submissions/new/self-check",
        data={
            "request_token": "tok-queue-fail",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "int main(){}",
        },
    )

    assert response.status_code == 500
    assert "后台分析排队失败".encode() in response.data


def test_student_submission_duplicate_request_token_opens_existing_record(app, client, monkeypatch):
    with app.app_context():
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        existing = Submission(
            student_name="stu01",
            student_user=student,
            request_token="same-token",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            submission_mode="self_check",
        )
        db.session.add_all([student, existing])
        db.session.commit()
        public_id = existing.public_id

    _login_student(client)
    monkeypatch.setattr("src.app.routes.student.enqueue_student_hint_job", lambda *args, **kwargs: None)

    response = client.post(
        "/student/submissions/new/self-check",
        data={
            "request_token": "same-token",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "int main(){return 1;}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/student/submissions/{public_id}")


def test_internal_job_endpoint_reports_invalid_payload_and_known_job_errors(client, monkeypatch):
    invalid = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-problem"},
        headers={"X-Internal-Job-Token": "test-internal-job-token"},
    )
    assert invalid.status_code == 400
    assert invalid.json == {"ok": False, "error": "invalid_payload"}

    monkeypatch.setattr("src.app.routes.internal.process_job_message", lambda **kwargs: (_ for _ in ()).throw(JobQueueError("unknown")))
    known_error = client.post(
        "/internal/jobs/process",
        json={"job_type": "unknown", "submission_public_id": "sub-1"},
        headers={"X-Internal-Job-Token": "test-internal-job-token"},
    )
    assert known_error.status_code == 400
    assert known_error.json == {"ok": False, "error": "unknown", "retryable": False}


def test_job_queue_inline_invalid_and_vercel_error_branches(app, monkeypatch):
    message = JobMessage(job_type="fetch-problem", submission_public_id="sub-1", requested_by="tester")

    with app.app_context():
        app.config["JOB_QUEUE_BACKEND"] = "unknown"
        app.extensions.pop("job_queue_backend", None)
        with pytest.raises(JobQueueError, match="不支持的队列后端"):
            enqueue_job(message)

        app.config["JOB_QUEUE_BACKEND"] = "vercel"
        app.config["VERCEL_OIDC_TOKEN"] = ""
        app.extensions.pop("job_queue_backend", None)
        with pytest.raises(JobQueueError, match="OIDC"):
            enqueue_job(message)

        app.config["VERCEL_OIDC_TOKEN"] = "token"
        app.config["VERCEL_QUEUE_REGION"] = ""
        app.extensions.pop("job_queue_backend", None)
        with pytest.raises(JobQueueError, match="区域或主题"):
            enqueue_job(message)

    class FailingClient:
        def post(self, url, *, json, headers):
            raise httpx.ReadTimeout("timeout")

    with app.test_request_context("/", headers={"x-vercel-oidc-token": "header-token"}):
        app.config["VERCEL_QUEUE_REGION"] = "iad1"
        app.config["VERCEL_QUEUE_TOPIC"] = "topic"
        app.config["JOB_QUEUE_PUBLISH_MAX_ATTEMPTS"] = 1
        app.extensions.pop("job_queue_backend", None)
        app.extensions["vercel_job_queue_http_client"] = FailingClient()
        with pytest.raises(JobQueueError, match="发送队列消息失败"):
            enqueue_job(message, idempotency_key="idem")


def test_settings_update_existing_rows_touches_timestamp(app):
    from src.app.services.settings import set_active_ai_model, set_ai_prompts

    with app.app_context():
        db.session.add(SystemSetting(key="active_ai_model", value="deepseek-v4-pro"))
        db.session.add(SystemSetting(key="teacher_system_prompt", value="old teacher"))
        db.session.add(SystemSetting(key="student_system_prompt", value="old student"))
        db.session.commit()
        old_updated_at = db.session.get(SystemSetting, "active_ai_model").updated_at

        assert set_active_ai_model(" deepseek-v4-flash ") == "deepseek-v4-flash"
        prompts = set_ai_prompts(teacher_system_prompt=" teacher ", student_system_prompt=" student ")
        db.session.commit()

        assert prompts == {"teacher_system_prompt": "teacher", "student_system_prompt": "student"}
        assert db.session.get(SystemSetting, "active_ai_model").value == "deepseek-v4-flash"
        assert db.session.get(SystemSetting, "active_ai_model").updated_at >= old_updated_at
