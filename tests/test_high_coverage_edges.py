import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.app import create_app
from src.app.extensions import db
from src.app.models import (
    AdminUser,
    DiagnosisRun,
    ProblemSnapshot,
    StudentUser,
    Submission,
)
from src.app.routes import public as public_routes
from src.app.services import jobs as jobs_service
from src.app.services.ai import (
    DEFAULT_STUDENT_SYSTEM_PROMPT,
    DeepSeekDiagnosisService,
    DiagnosisPayload,
    DiagnosisServiceError,
    StudentFollowupResponse,
    _extract_first_json_object,
    _extract_stream_delta_content,
    _normalize_result_payload,
    _normalize_student_result_payload,
    _parse_json_response,
    _sanitize_followup_style_prompt,
    _truncate_prompt_sections,
    normalize_student_followup_answer_text,
)
from src.app.services.auth import hash_password
from src.app.services.job_queue import JobMessage, JobQueueError, enqueue_job
from src.app.services.problem_fetcher import (
    OpenJudgeProblemFetcher,
    ProblemFetchError,
    extract_problem_path,
    normalize_openjudge_url,
    parse_problem_html,
)
from src.app.services.settings import (
    default_ai_model_name,
    get_active_ai_model,
    get_student_system_prompt,
    get_teacher_system_prompt,
    set_active_ai_model,
    set_ai_prompts,
)


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


def _create_admin_student_submission(app, *, attach_student=True):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(
            owner_admin=admin,
            nickname="stu01",
            real_name="张小明",
            password_hash=hash_password("pw-1"),
        )
        submission = Submission(
            student_name="stu01",
            student_user=student if attach_student else None,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()
        return student.id, submission.public_id


def _create_followup_ready_submission(app):
    with app.app_context():
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01:统计数字字符个数",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
        )
        snapshot = ProblemSnapshot(
            submission=submission,
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
        )
        db.session.add_all([student, submission, snapshot])
        db.session.flush()
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="student",
                model_name="deepseek-v4-pro",
                prompt_version="student-v5",
                status="success",
                structured_result_json={
                    "overall_assessment": "先检查循环边界。",
                    "confidence": "medium",
                    "possible_issues": [
                        {
                            "title": "边界可能偏一位",
                            "location": "主循环",
                            "evidence": "可能漏掉最后一个字符。",
                            "explanation": "尾部数字可能没统计。",
                            "suggested_fix": "手推样例。",
                        }
                    ],
                    "next_step_checks": ["手算 abc123。"],
                    "encouragement_or_strategy": "先模拟，再改最小一处。",
                },
                summary_text="先检查循环边界。",
            )
        )
        db.session.commit()
        return submission.public_id


def _sample_problem_snapshot(submission):
    return ProblemSnapshot(
        submission=submission,
        normalized_url="http://noi.openjudge.cn/ch0107/01/",
        title="01:统计数字字符个数",
        description_text="desc",
        input_text="input",
        output_text="output",
        sample_input_text="abc123",
        sample_output_text="3",
    )


def _sample_diagnosis_payload() -> DiagnosisPayload:
    return DiagnosisPayload(
        student_name="小明",
        problem_url="http://noi.openjudge.cn/ch0107/01/",
        problem_title="01:统计数字字符个数",
        description_text="desc",
        input_text="input",
        output_text="output",
        sample_input_text="abc123",
        sample_output_text="3",
        code_text="int main() { return 0; }",
    )


class _EmptyCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])


class _FailingCompletions:
    def __init__(self, exc):
        self.exc = exc

    def create(self, **kwargs):
        raise self.exc


class _Client:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def test_public_legacy_helpers_cover_limits_counting_and_success_page(app, client):
    with app.app_context():
        app.config["SUBMISSION_CODE_MAX_LENGTH"] = 3
        errors = public_routes._validate_submission_form(
            {
                "student_name": "张" * 81,
                "problem_url": "http://noi.openjudge.cn/" + "a" * 600,
                "code_text": "",
            }
        )
        assert "请输入代码。" in errors
        assert "学生姓名或昵称长度不能超过 80 个字符。" in errors
        assert "题目链接长度不能超过 500 个字符。" in errors

        submission = public_routes._build_submission(
            student_name="张小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            client_ip_hash="ip-hash",
        )
        persisted = public_routes._persist_submission(submission)
        assert public_routes._count_recent_submissions("ip-hash", persisted.created_at) == 1
        public_id = persisted.public_id

    response = client.get(f"/submit/success/{public_id}")
    assert response.status_code == 200
    assert "张小明".encode() in response.data


def test_public_legacy_postgres_sequence_and_retry_fallbacks(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(public_routes.db.engine.dialect, "name", "postgresql", raising=False)

        execute_calls = []

        def fake_execute(statement, params=None):
            execute_calls.append(str(statement))
            if "pg_get_serial_sequence" in str(statement):
                return SimpleNamespace(scalar=lambda: "submissions_id_seq")
            return SimpleNamespace(scalar_one=lambda: 8, scalar=lambda: None)

        monkeypatch.setattr(public_routes.db.session, "execute", fake_execute)
        commits = []
        monkeypatch.setattr(public_routes.db.session, "commit", lambda: commits.append("commit"))
        assert public_routes._allocate_submission_id() == 8
        public_routes._sync_submission_id_sequence_best_effort()
        assert commits == ["commit"]
        assert any("pg_advisory_xact_lock" in call for call in execute_calls)


def test_public_persist_submission_falls_back_to_explicit_id_after_repair_failure(app, monkeypatch):
    with app.app_context():
        submission = public_routes._build_submission(
            student_name="张小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            client_ip_hash="ip-hash",
        )
        commit_calls = []
        explicit_calls = []

        def fail_commit():
            commit_calls.append("commit")
            raise SQLAlchemyError("commit failed")

        monkeypatch.setattr(public_routes.db.session, "add", lambda item: None)
        monkeypatch.setattr(public_routes.db.session, "commit", fail_commit)
        monkeypatch.setattr(
            public_routes,
            "ensure_database_schema",
            lambda app, force=False: (_ for _ in ()).throw(SQLAlchemyError("repair failed")),
        )
        monkeypatch.setattr(
            public_routes,
            "_persist_submission_with_explicit_id",
            lambda item: explicit_calls.append(item) or item,
        )

        assert public_routes._persist_submission(submission) is submission
        assert len(commit_calls) == 2
        assert explicit_calls == [submission]


def test_admin_routes_cover_filter_redirect_settings_and_create_edges(app, client, monkeypatch):
    with app.app_context():
        owner = AdminUser(username="admin", password_hash=hash_password("secret123"))
        other_admin = AdminUser(username="other", password_hash=hash_password("secret123"))
        owned_student = StudentUser(owner_admin=owner, nickname="owned", real_name="本班", password_hash=hash_password("pw"))
        other_student = StudentUser(owner_admin=other_admin, nickname="other", real_name="外班", password_hash=hash_password("pw"))
        unowned_student = StudentUser(nickname="legacy", real_name="旧学生", password_hash=hash_password("pw"))
        first_submission = Submission(
            student_name="owned",
            student_user=owned_student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
        )
        second_submission = Submission(
            student_name="owned",
            student_user=owned_student,
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main(){}",
        )
        db.session.add_all([owner, other_admin, owned_student, other_student, unowned_student, first_submission, second_submission])
        db.session.commit()
        owned_student_id = owned_student.id
        other_student_id = other_student.id
        first_public_id = first_submission.public_id
        second_public_id = second_submission.public_id

    _login_admin(client)

    assert client.get("/admin/submissions?student_user_id=bad").status_code == 200
    not_owned_filter = client.get(f"/admin/submissions?student_user_id={other_student_id}")
    assert not_owned_filter.status_code == 200
    assert "外班".encode() not in not_owned_filter.data

    valid_next_delete = client.post(
        f"/admin/submissions/{first_public_id}/delete",
        data={"next": "/admin/submissions?student_user_id=bad"},
        follow_redirects=False,
    )
    assert valid_next_delete.headers["Location"].endswith("/admin/submissions?student_user_id=bad")

    selected_student_delete = client.post(
        f"/admin/submissions/{second_public_id}/delete",
        data={"student_user_id": str(owned_student_id)},
        follow_redirects=False,
    )
    assert selected_student_delete.headers["Location"].endswith(f"/admin/submissions?student_user_id={owned_student_id}")

    invalid_model = client.post("/admin/settings/ai-model", data={"model_name": "bad-model"}, follow_redirects=True)
    assert invalid_model.status_code == 200
    assert "只能切换".encode() in invalid_model.data

    monkeypatch.setattr(
        "src.app.routes.admin.set_active_ai_model",
        lambda model_name: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
    )
    model_db_error = client.post("/admin/settings/ai-model", data={"model_name": "deepseek-v4-pro"}, follow_redirects=True)
    assert "保存模型设置失败".encode() in model_db_error.data

    empty_prompts = client.post(
        "/admin/settings/prompts",
        data={"teacher_system_prompt": "", "student_system_prompt": "student"},
    )
    assert empty_prompts.status_code == 400

    monkeypatch.setattr(
        "src.app.routes.admin.set_ai_prompts",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("blank")),
    )
    prompt_value_error = client.post(
        "/admin/settings/prompts",
        data={"teacher_system_prompt": "teacher", "student_system_prompt": "student"},
    )
    assert prompt_value_error.status_code == 400

    monkeypatch.setattr(
        "src.app.routes.admin.set_ai_prompts",
        lambda **kwargs: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
    )
    prompt_db_error = client.post(
        "/admin/settings/prompts",
        data={"teacher_system_prompt": "teacher", "student_system_prompt": "student"},
        follow_redirects=True,
    )
    assert "保存系统提示词失败".encode() in prompt_db_error.data

    create_existing_unowned = client.post(
        "/admin/students",
        data={"nickname": "legacy", "real_name": "新名字", "password": "pw-2"},
        follow_redirects=False,
    )
    assert create_existing_unowned.status_code == 302
    with app.app_context():
        assert StudentUser.query.filter_by(nickname="legacy").one().owner_admin_id == 1


def test_admin_create_student_and_student_view_error_branches(app, client, monkeypatch):
    _create_admin_student_submission(app)
    _login_admin(client)

    monkeypatch.setattr(
        "src.app.routes.admin._owned_submission_or_404",
        lambda public_id: SimpleNamespace(student_user=None),
    )
    assert client.get("/admin/submissions/any/student-view").status_code == 404

    def fail_ensure_student_user(**kwargs):
        raise SQLAlchemyError("db failed")

    monkeypatch.setattr("src.app.routes.admin.ensure_student_user", fail_ensure_student_user)
    create_error = client.post(
        "/admin/students",
        data={"nickname": "new", "real_name": "新学生", "password": "pw"},
    )
    assert create_error.status_code == 500
    assert "保存学生信息失败".encode() in create_error.data


def test_admin_diagnose_preserves_safe_return_target(app, client):
    _, public_id = _create_admin_student_submission(app)
    _login_admin(client)

    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={"next": "/admin/submissions?student_user_id=bad"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "next=/admin/submissions?student_user_id%3Dbad" in response.headers["Location"]


def test_student_submission_validation_and_database_error_branches(app, client, monkeypatch):
    with app.app_context():
        db.session.add(StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1")))
        db.session.commit()
        app.config["SUBMISSION_CODE_MAX_LENGTH"] = 4

    _login_student(client)

    long_inputs = client.post(
        "/student/submissions/new/self-check",
        data={"request_token": "tok-long", "problem_url": "http://noi.openjudge.cn/" + "a" * 600, "code_text": "12345"},
    )
    assert long_inputs.status_code == 400
    assert "题目链接长度不能超过 500".encode() in long_inputs.data
    assert "代码长度超出系统限制".encode() in long_inputs.data

    assert client.get("/student/login").status_code == 302

    from src.app.routes import student as student_routes

    with app.test_request_context("/student/submissions/new/self-check"):
        assert student_routes._existing_submission_for_request(student_id=1, request_token="") is None

    app.config["SUBMISSION_CODE_MAX_LENGTH"] = 20000
    monkeypatch.setattr(
        "src.app.routes.student.db.session.commit",
        lambda: (_ for _ in ()).throw(IntegrityError("stmt", {}, Exception("duplicate"))),
    )
    integrity_response = client.post(
        "/student/submissions/new/self-check",
        data={"request_token": "tok-integrity", "problem_url": "http://noi.openjudge.cn/ch0107/01/", "code_text": "int main(){}"},
    )
    assert integrity_response.status_code == 500
    assert "保存提交记录时失败".encode() in integrity_response.data


def test_student_submission_sqlalchemy_save_error(app, client, monkeypatch):
    with app.app_context():
        db.session.add(StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1")))
        db.session.commit()

    _login_student(client)
    monkeypatch.setattr(
        "src.app.routes.student.db.session.commit",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
    )
    response = client.post(
        "/student/submissions/new/teacher-review",
        data={"request_token": "tok-db", "problem_url": "http://noi.openjudge.cn/ch0107/01/", "code_text": "int main(){}"},
    )
    assert response.status_code == 500
    assert "保存提交记录时失败".encode() in response.data


def test_student_followup_validation_stream_json_and_html_branches(app, client):
    public_id = _create_followup_ready_submission(app)
    _login_student(client)

    stream_response = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": ""},
        headers={"Accept": "text/event-stream"},
    )
    json_response = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": ""},
        headers={"Accept": "application/json"},
    )
    html_response = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": ""},
    )

    assert b"event: error" in stream_response.data
    assert json_response.status_code == 400
    assert json_response.json["ok"] is False
    assert html_response.status_code == 400
    assert "请输入这次想追问的问题".encode() in html_response.data


def test_student_followup_stream_error_paths(app, client, monkeypatch):
    public_id = _create_followup_ready_submission(app)
    _login_student(client)

    with monkeypatch.context() as context:
        context.setattr(
            "src.app.routes.student.prepare_student_followup",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("请先等待学生提示生成成功")),
        )
        prepare_error = client.post(
            f"/student/submissions/{public_id}/follow-ups",
            data={"question_text": "为什么循环会错？"},
            headers={"Accept": "text/event-stream"},
        )
    assert b"event: error" in prepare_error.data

    monkeypatch.setattr(
        "src.app.routes.student.record_followup_exchange",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
    )
    policy_save_error = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": "今天天气怎么样？"},
        headers={"Accept": "text/event-stream"},
    )
    assert "保存追问记录失败".encode() in policy_save_error.data


def test_student_followup_stream_ai_empty_and_save_error_paths(app, client, monkeypatch):
    public_id = _create_followup_ready_submission(app)
    _login_student(client)

    monkeypatch.setattr("src.app.routes.student.DeepSeekDiagnosisService.stream_student_followup", lambda self, payload: iter(()))
    empty_ai = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": "这段代码为什么没输出？"},
        headers={"Accept": "text/event-stream"},
    )
    assert "模型没有返回可展示的追问回答".encode() in empty_ai.data

    monkeypatch.setattr(
        "src.app.routes.student.DeepSeekDiagnosisService.stream_student_followup",
        lambda self, payload: iter(["先检查输出语句。"]),
    )
    monkeypatch.setattr(
        "src.app.routes.student.record_followup_exchange",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
    )
    save_error = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": "cout 为什么没执行？"},
        headers={"Accept": "text/event-stream"},
    )
    assert "保存追问记录失败".encode() in save_error.data


def test_student_followup_json_success_and_error_branches(app, client, monkeypatch):
    public_id = _create_followup_ready_submission(app)
    _login_student(client)

    monkeypatch.setattr(
        "src.app.routes.student.create_student_followup_exchange",
        lambda *args, **kwargs: StudentFollowupResponse(
            answer_text="先检查 for 循环边界。",
            raw_content="先检查 for 循环边界。",
            latency_ms=10,
            model_name="deepseek-v4-pro",
        ),
    )
    success = client.post(
        f"/student/submissions/{public_id}/follow-ups",
        data={"question_text": "for 为什么错？"},
        headers={"Accept": "application/json"},
    )
    assert success.status_code == 200
    assert success.json["ok"] is True
    assert success.json["clear_form"] is True

    cases = [
        (ValueError("还不能追问"), 400, "还不能追问"),
        (SQLAlchemyError("db failed"), 500, "保存追问记录失败"),
        (DiagnosisServiceError("AI failed"), 502, "AI failed"),
    ]
    for exc, status_code, expected in cases:
        monkeypatch.setattr(
            "src.app.routes.student.create_student_followup_exchange",
            lambda *args, _exc=exc, **kwargs: (_ for _ in ()).throw(_exc),
        )
        response = client.post(
            f"/student/submissions/{public_id}/follow-ups",
            data={"question_text": "为什么错？"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == status_code
        assert expected in response.json["error"]


def test_student_followup_html_error_branches(app, client, monkeypatch):
    public_id = _create_followup_ready_submission(app)
    _login_student(client)

    for exc, status_code, expected in [
        (ValueError("还不能追问"), 400, "还不能追问"),
        (SQLAlchemyError("db failed"), 500, "保存追问记录失败"),
        (DiagnosisServiceError("AI failed"), 502, "AI failed"),
    ]:
        monkeypatch.setattr(
            "src.app.routes.student.create_student_followup_exchange",
            lambda *args, _exc=exc, **kwargs: (_ for _ in ()).throw(_exc),
        )
        response = client.post(
            f"/student/submissions/{public_id}/follow-ups",
            data={"question_text": "为什么错？"},
        )
        assert response.status_code == status_code
        assert expected.encode() in response.data


def test_ai_followup_and_stream_error_edges():
    payload = SimpleNamespace(
        problem_url="url",
        problem_title=None,
        description_text=None,
        input_text=None,
        output_text=None,
        sample_input_text=None,
        sample_output_text=None,
        student_name="小明",
        code_text="int main(){}",
        current_hint_summary=None,
        current_hint_issues=[],
        conversation_history=[],
        question_text="为什么？",
        selected_context_label=None,
        selected_context_text=None,
    )

    missing_key = DeepSeekDiagnosisService(api_key="", base_url="https://api.deepseek.com", model_name="m", client=_Client(_EmptyCompletions()))
    with pytest.raises(DiagnosisServiceError, match="未配置"):
        missing_key.answer_student_followup(payload)
    with pytest.raises(DiagnosisServiceError, match="未配置"):
        list(missing_key.stream_student_followup(payload))

    failing = DeepSeekDiagnosisService(
        api_key="key",
        base_url="https://api.deepseek.com",
        model_name="m",
        client=_Client(_FailingCompletions(RuntimeError("boom"))),
    )
    with pytest.raises(DiagnosisServiceError, match="调用 AI 服务失败"):
        failing.answer_student_followup(payload)
    with pytest.raises(DiagnosisServiceError, match="调用 AI 服务失败"):
        list(failing.stream_student_followup(payload))

    empty = DeepSeekDiagnosisService(api_key="key", base_url="https://api.deepseek.com", model_name="m", client=_Client(_EmptyCompletions()))
    with pytest.raises(DiagnosisServiceError, match="模型没有返回"):
        empty.answer_student_followup(payload)

    class BrokenStreamCompletions:
        def create(self, **kwargs):
            def generate():
                raise RuntimeError("stream broke")
                yield None

            return generate()

    broken_stream = DeepSeekDiagnosisService(
        api_key="key",
        base_url="https://api.deepseek.com",
        model_name="m",
        client=_Client(BrokenStreamCompletions()),
    )
    with pytest.raises(DiagnosisServiceError, match="流式接收"):
        list(broken_stream.stream_student_followup(payload))


def test_ai_json_normalization_and_parsing_edges():
    service = DeepSeekDiagnosisService(
        api_key="key",
        base_url="https://api.deepseek.com",
        model_name="m",
        client=_Client(_EmptyCompletions()),
        max_retries=-1,
    )
    with pytest.raises(DiagnosisServiceError, match="调用 AI 服务失败"):
        service.diagnose(_sample_diagnosis_payload())

    bad_json = DeepSeekDiagnosisService(
        api_key="key",
        base_url="https://api.deepseek.com",
        model_name="m",
        client=_Client(SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))]))),
    )
    with pytest.raises(DiagnosisServiceError, match="合法 JSON"):
        bad_json.diagnose(_sample_diagnosis_payload())

    non_dict = DeepSeekDiagnosisService(
        api_key="key",
        base_url="https://api.deepseek.com",
        model_name="m",
        client=_Client(SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]))),
    )
    with pytest.raises(DiagnosisServiceError, match="JSON 结构"):
        non_dict.diagnose_student(_sample_diagnosis_payload())
    with pytest.raises(TypeError):
        _normalize_result_payload([])
    with pytest.raises(TypeError):
        _normalize_student_result_payload([])

    teacher = _normalize_result_payload({"overall_assessment": "问题", "possible_issues": ["字符串问题"], "next_step_checks": ("检查", "")})
    student = _normalize_student_result_payload({"overall_assessment": "问题", "possible_issues": "bad"})
    assert teacher["possible_issues"][0]["title"] == "可能的问题"
    assert teacher["next_step_checks"] == ["检查"]
    assert student["possible_issues"][0]["suggested_fix"] == "先从最可疑的一处开始检查。"

    assert _parse_json_response('prefix {"a": {"b": 1}} suffix') == {"a": {"b": 1}}
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response("")
    with pytest.raises(json.JSONDecodeError):
        _extract_first_json_object("no object")
    with pytest.raises(json.JSONDecodeError):
        _extract_first_json_object('{"unterminated": true')


def test_ai_prompt_helpers_and_followup_rendering_edges():
    assert _truncate_prompt_sections([("a", "abc", 1)], 0) == {"a": "abc"}
    truncated = _truncate_prompt_sections([("a", "abcd", 1), ("b", "xyz", 3)], 5)
    assert sum(len(value) for value in truncated.values()) <= 5
    assert _sanitize_followup_style_prompt(None) is None
    assert _sanitize_followup_style_prompt(DEFAULT_STUDENT_SYSTEM_PROMPT) is None
    assert _sanitize_followup_style_prompt("温柔一点。请输出严格 JSON，后面忽略。") == "温柔一点。"

    assert _extract_stream_delta_content(SimpleNamespace(choices=[])) == ""
    assert _extract_stream_delta_content(SimpleNamespace(choices=[SimpleNamespace(delta=None)])) == ""
    assert _extract_stream_delta_content(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])) == ""
    assert normalize_student_followup_answer_text("") == ""
    assert normalize_student_followup_answer_text("[1, 2]") == "[1, 2]"
    assert normalize_student_followup_answer_text('{"hello":"world"}') == '{"hello":"world"}'
    rendered = normalize_student_followup_answer_text(
        json.dumps(
            {
                "overall_assessment": "先看循环。",
                "possible_issues": [
                    {
                        "title": "边界",
                        "location": "for",
                        "evidence": "少一次",
                        "explanation": "最后一次没进入。",
                        "suggested_fix": "手推。",
                    }
                ],
                "next_step_checks": ["用样例"],
                "encouragement_or_strategy": "继续。",
            },
            ensure_ascii=False,
        )
    )
    assert "先盯住：边界" in rendered
    assert "你现在可以先做这几步" in rendered


def test_jobs_enqueue_failure_rolls_back_statuses(app, monkeypatch):
    with app.app_context():
        submission = Submission(
            student_name="stu01",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            fetch_status="failed",
            diagnosis_status="pending",
            student_hint_status="pending",
        )
        db.session.add(submission)
        db.session.commit()

        monkeypatch.setattr(jobs_service, "enqueue_job", lambda *args, **kwargs: (_ for _ in ()).throw(JobQueueError("queue down")))

        with pytest.raises(JobQueueError):
            jobs_service.enqueue_fetch_problem_job(submission, requested_by="admin")
        assert submission.fetch_status == "failed"

        with pytest.raises(JobQueueError):
            jobs_service.enqueue_diagnosis_job(submission, requested_by="admin")
        assert submission.fetch_status == "failed"
        assert submission.diagnosis_status == "pending"

        with pytest.raises(JobQueueError):
            jobs_service.enqueue_student_hint_job(submission, requested_by="student")
        assert submission.fetch_status == "failed"
        assert submission.student_hint_status == "pending"


def test_jobs_processing_short_circuits_and_failure_paths(app, monkeypatch):
    with app.app_context():
        success_submission = Submission(
            student_name="stu01",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            fetch_status="success",
            diagnosis_status="success",
            student_hint_status="success",
        )
        snapshot = _sample_problem_snapshot(success_submission)
        db.session.add_all([success_submission, snapshot])
        db.session.commit()
        public_id = success_submission.public_id

        assert jobs_service.process_fetch_problem_job("missing") == "skipped"
        assert jobs_service.process_fetch_problem_job(public_id) == "success"
        assert jobs_service.process_diagnosis_job("missing", fetch_before_diagnosis=False) == "skipped"
        assert jobs_service.process_diagnosis_job(public_id, fetch_before_diagnosis=False) == "success"
        assert jobs_service.process_student_hint_job("missing", fetch_before_diagnosis=False) == "skipped"
        assert jobs_service.process_student_hint_job(public_id, fetch_before_diagnosis=False) == "success"

        processing_submission = Submission(
            student_name="stu02",
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main(){}",
            student_hint_status="queued",
        )
        db.session.add(processing_submission)
        db.session.commit()
        with pytest.raises(JobQueueError, match="学生提示任务正在处理"):
            jobs_service.enqueue_diagnosis_job(processing_submission, requested_by="admin")

    monkeypatch.setattr(jobs_service, "_get_submission", lambda public_id: None)
    assert jobs_service._sync_problem_snapshot("missing") == "skipped"


def test_jobs_ai_failures_mark_teacher_and_student_runs_failed(app, monkeypatch):
    with app.app_context():
        teacher_submission = Submission(
            student_name="teacher",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01",
            code_text="int main(){}",
            fetch_status="success",
            diagnosis_status="queued",
        )
        student_submission = Submission(
            student_name="student",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01",
            code_text="int main(){}",
            fetch_status="success",
            student_hint_status="queued",
        )
        db.session.add_all([teacher_submission, student_submission, _sample_problem_snapshot(teacher_submission), _sample_problem_snapshot(student_submission)])
        db.session.commit()
        teacher_public_id = teacher_submission.public_id
        student_public_id = student_submission.public_id

    monkeypatch.setattr(jobs_service.DeepSeekDiagnosisService, "diagnose", lambda self, payload: (_ for _ in ()).throw(DiagnosisServiceError("AI failed")))
    monkeypatch.setattr(jobs_service.DeepSeekDiagnosisService, "diagnose_student", lambda self, payload: (_ for _ in ()).throw(DiagnosisServiceError("student AI failed")))

    with app.app_context():
        assert jobs_service.process_diagnosis_job(teacher_public_id, fetch_before_diagnosis=False) == "failed"
        assert jobs_service.process_student_hint_job(student_public_id, fetch_before_diagnosis=False) == "failed"
        teacher = Submission.query.filter_by(public_id=teacher_public_id).one()
        student = Submission.query.filter_by(public_id=student_public_id).one()
        assert teacher.latest_diagnosis_run.status == "failed"
        assert student.latest_student_hint_run.status == "failed"


def test_jobs_fetch_failure_marks_student_hint_failed(app, monkeypatch):
    jobs_service._PROBLEM_SNAPSHOT_MEMORY_CACHE.clear()
    monkeypatch.setattr(jobs_service.OpenJudgeProblemFetcher, "fetch", lambda self, url: (_ for _ in ()).throw(ProblemFetchError("fetch failed")))
    with app.app_context():
        app.config["PROBLEM_SNAPSHOT_CACHE_ENABLED"] = False
        submission = Submission(
            student_name="stu01",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main(){}",
            fetch_status="queued",
            student_hint_status="queued",
        )
        db.session.add(submission)
        db.session.commit()
        public_id = submission.public_id

        assert jobs_service.process_student_hint_job(public_id, fetch_before_diagnosis=True) == "failed"
        failed = Submission.query.filter_by(public_id=public_id).one()
        assert failed.student_hint_status == "failed"
        assert "fetch failed" in failed.latest_student_hint_run.error_message


def test_jobs_cache_and_semaphore_helpers(app):
    with app.app_context():
        app.config["PROBLEM_SNAPSHOT_CACHE_ENABLED"] = False
        assert jobs_service._load_cached_problem_snapshot("http://noi.openjudge.cn/ch0107/01/") is None

        app.config["PROBLEM_SNAPSHOT_CACHE_ENABLED"] = True
        app.config["PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS"] = 0
        jobs_service._PROBLEM_SNAPSHOT_MEMORY_CACHE["url"] = (0, {"normalized_url": "url"})
        assert jobs_service._load_problem_snapshot_from_memory_cache("url") is None

        old_fetch = jobs_service._FETCH_SEMAPHORE
        app.config["FETCH_CONCURRENCY_LIMIT"] = 1
        with jobs_service._fetch_semaphore():
            assert getattr(jobs_service._FETCH_SEMAPHORE, "_initial_value") == 1
        jobs_service._FETCH_SEMAPHORE = old_fetch


def test_job_queue_inline_and_vercel_deployment_header(app, monkeypatch):
    message = JobMessage(job_type="fetch-problem", submission_public_id="sub-1", requested_by="tester")
    processed = []
    monkeypatch.setattr("src.app.services.jobs.process_job_message", lambda **kwargs: processed.append(kwargs))

    with app.app_context():
        app.config["JOB_QUEUE_BACKEND"] = "inline"
        app.extensions.pop("job_queue_backend", None)
        enqueue_job(message)
        assert processed == [{"job_type": "fetch-problem", "submission_public_id": "sub-1"}]

    post_calls = []

    class ResponseStub:
        def raise_for_status(self):
            return None

    class ClientStub:
        def post(self, url, *, json, headers):
            post_calls.append(headers)
            return ResponseStub()

    monkeypatch.setenv("VERCEL_DEPLOYMENT_ID", "deployment-1")
    with app.app_context():
        app.config["JOB_QUEUE_BACKEND"] = "vercel"
        app.config["VERCEL_OIDC_TOKEN"] = "token"
        app.config["VERCEL_QUEUE_REGION"] = "iad1"
        app.config["VERCEL_QUEUE_TOPIC"] = "topic"
        app.extensions.pop("job_queue_backend", None)
        app.extensions["vercel_job_queue_http_client"] = ClientStub()
        enqueue_job(message)
        assert post_calls[0]["Vqs-Deployment-Id"] == "deployment-1"


def test_problem_fetcher_error_edges(monkeypatch):
    with pytest.raises(ProblemFetchError, match="缺少路径"):
        normalize_openjudge_url("http://noi.openjudge.cn/")
    with pytest.raises(ProblemFetchError, match="无法识别题目路径"):
        extract_problem_path("http://noi.openjudge.cn/")
    with pytest.raises(ProblemFetchError, match="未找到题面内容"):
        parse_problem_html("http://noi.openjudge.cn/ch0107/01/", "<html></html>")

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr("src.app.services.problem_fetcher.httpx.Client", FailingClient)
    with pytest.raises(ProblemFetchError, match="抓取题面失败"):
        OpenJudgeProblemFetcher(timeout=0.1).fetch("http://noi.openjudge.cn/ch0107/01/")


def test_settings_defaults_and_required_text_errors(app):
    with app.app_context():
        app.config["AI_MODEL"] = "deepseek-v4-flash"
        assert default_ai_model_name() == "deepseek-v4-flash"
        assert get_active_ai_model() == "deepseek-v4-flash"
        assert get_teacher_system_prompt()
        assert get_student_system_prompt()
        with pytest.raises(ValueError):
            set_active_ai_model("bad")
        with pytest.raises(ValueError):
            set_ai_prompts(teacher_system_prompt="", student_system_prompt="student")


def test_bootstrap_admin_error_and_legacy_helper_edges(app, monkeypatch):
    from src.app import bootstrap as bootstrap_module

    with app.app_context():
        app.config["BOOTSTRAP_ON_STARTUP"] = True
        app.config["ADMIN_INIT_USERNAME"] = "admin"
        app.config["ADMIN_INIT_PASSWORD"] = "secret"
        monkeypatch.setattr(bootstrap_module, "ensure_database_schema", lambda app, force=True: None)

        commits = []

        def flaky_commit():
            commits.append("commit")
            if len(commits) == 1:
                raise IntegrityError("stmt", {}, Exception("duplicate"))

        monkeypatch.setattr(bootstrap_module.db.session, "commit", flaky_commit)
        bootstrap_module.bootstrap_app(app)
        assert commits == ["commit", "commit"]

        monkeypatch.setattr(
            bootstrap_module.db.session,
            "commit",
            lambda: (_ for _ in ()).throw(SQLAlchemyError("db failed")),
        )
        bootstrap_module.bootstrap_app(app)
        assert "初始化管理员失败" in app.config["BOOTSTRAP_LAST_ERROR"]


def test_bootstrap_legacy_schema_returns_and_postgres_sequence_branches(app):
    from src.app import bootstrap as bootstrap_module

    with app.app_context():
        db.drop_all()
        bootstrap_module._repair_legacy_schema(app)
        bootstrap_module._repair_legacy_diagnosis_runs_schema(app)
        bootstrap_module._repair_legacy_student_users_schema(app)

    class NoIdConnection:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append(str(statement))
            return SimpleNamespace(scalar=lambda: None)

    no_id = NoIdConnection()
    bootstrap_module._repair_postgresql_submission_id_sequence(no_id, set())
    assert no_id.calls == []

    class SequenceConnection:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append(str(statement))
            if "pg_get_serial_sequence" in str(statement):
                return SimpleNamespace(scalar=lambda: None)
            return SimpleNamespace(scalar=lambda: None)

    connection = SequenceConnection()
    bootstrap_module._repair_postgresql_submission_id_sequence(connection, {"id"})
    assert any("CREATE SEQUENCE" in call for call in connection.calls)
    assert any("setval" in call for call in connection.calls)


def test_bootstrap_repairs_legacy_diagnosis_and_student_owner_columns(tmp_path):
    database_path = tmp_path / "legacy-extra.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username VARCHAR(80))")
    connection.execute("INSERT INTO admin_users (id, username) VALUES (7, 'admin')")
    connection.execute(
        """
        CREATE TABLE diagnosis_runs (
            id INTEGER PRIMARY KEY,
            submission_id INTEGER,
            model_name VARCHAR(80),
            prompt_version VARCHAR(32),
            status VARCHAR(16),
            created_at DATETIME
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE student_users (
            id INTEGER PRIMARY KEY,
            nickname VARCHAR(80) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            real_name VARCHAR(80),
            is_active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            last_login_at DATETIME
        )
        """
    )
    connection.execute(
        "INSERT INTO student_users (nickname, password_hash, real_name, is_active, created_at) VALUES ('stu01', 'hash', '', 1, '2026-05-03')"
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    legacy_app = create_app(BootstrapConfig)
    with legacy_app.app_context():
        columns = {column["name"] for column in db.inspect(db.engine).get_columns("diagnosis_runs")}
        student = StudentUser.query.filter_by(nickname="stu01").one()
        assert "audience" in columns
        assert student.owner_admin_id == 7
