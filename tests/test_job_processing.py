from src.app.extensions import db
from src.app.models import AdminUser, Submission
from src.app import create_app
from src.app.services.ai import DiagnosisPayload, DiagnosisResponse
from src.app.services.problem_fetcher import ProblemContent, ProblemFetchError
from src.app.schemas import DiagnosisResult
from src.app.services.auth import hash_password
from src.app.services.job_queue import JobQueueError
import threading


def _clear_problem_snapshot_memory_cache() -> None:
    import src.app.services.jobs as jobs_module

    jobs_module._PROBLEM_SNAPSHOT_MEMORY_CACHE.clear()


def _auth_headers() -> dict[str, str]:
    return {"X-Internal-Job-Token": "test-internal-job-token"}


def _sample_diagnosis_response() -> DiagnosisResponse:
    return DiagnosisResponse(
        result=DiagnosisResult.model_validate(
            {
                "overall_assessment": "更像是字符统计逻辑有遗漏。",
                "confidence": "medium",
                "missing_context": [],
                "possible_issues": [
                    {
                        "title": "没有正确判断数字字符",
                        "location": "主逻辑判断分支",
                        "evidence": "代码中未见 isdigit 或范围判断。",
                        "explanation": "可能把所有字符都累计了。",
                        "suggested_fix": "只在字符位于 '0' 到 '9' 时递增计数。",
                    }
                ],
                "teacher_talking_points": ["先检查判断条件是否只针对数字。"],
                "next_step_checks": ["用 abc123 和 000 做自测。"],
                "correct_program": "#include <iostream>\nusing namespace std;\nint main(){return 0;}",
            }
        ),
        raw_content="{}",
        latency_ms=120,
        model_name="deepseek-v4-pro",
    )


def test_internal_job_endpoint_requires_token(client):
    response = client.post("/internal/jobs/process", json={"job_type": "fetch-problem"})

    assert response.status_code == 403


def test_internal_job_endpoint_processes_fetch_problem_job(app, client, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)

    with app.app_context():
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="pending",
        )
        db.session.add(submission)
        db.session.commit()
        public_id = submission.public_id

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-problem", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        assert submission.fetch_status == "success"
        assert submission.problem_snapshot.title == "01:统计数字字符个数"


def test_internal_job_endpoint_processes_combined_job(app, client, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    def fake_diagnose(self, payload: DiagnosisPayload):
        return _sample_diagnosis_response()

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add_all([admin, submission])
        db.session.commit()
        public_id = submission.public_id

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        assert submission.fetch_status == "success"
        assert submission.diagnosis_status == "success"
        assert submission.latest_diagnosis_run.status == "success"
        assert submission.problem_snapshot.title == "01:统计数字字符个数"


def test_internal_job_endpoint_marks_failure_when_fetch_fails(app, client, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    def fake_fetch(self, url):
        raise ProblemFetchError("OpenJudge 暂时无法访问。")

    def fail_if_diagnose_called(self, payload):
        raise AssertionError("抓题失败后不应继续调用 AI")

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose", fail_if_diagnose_called)

    with app.app_context():
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add(submission)
        db.session.commit()
        public_id = submission.public_id

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "failed"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        assert submission.fetch_status == "failed"
        assert submission.diagnosis_status == "failed"
        assert submission.latest_diagnosis_run.status == "failed"
        assert "抓取题面失败" in submission.latest_diagnosis_run.error_message


def test_internal_job_endpoint_returns_controlled_error_for_unexpected_exception(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.app.routes.internal.process_job_message", boom)

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-problem", "submission_public_id": "sub-1"},
        headers=_auth_headers(),
    )

    assert response.status_code == 500
    assert response.json["ok"] is False
    assert response.json["error"] == "internal_error"
    assert response.json["retryable"] is True


def test_process_diagnosis_job_reuses_existing_problem_snapshot(app, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    fetch_calls = []

    def fake_fetch(self, url):
        fetch_calls.append(url)
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    def fake_diagnose(self, payload: DiagnosisPayload):
        return _sample_diagnosis_response()

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    with app.app_context():
        first = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add(first)
        db.session.commit()
        from src.app.services.jobs import process_diagnosis_job

        assert process_diagnosis_job(first.public_id, fetch_before_diagnosis=True) == "success"

        second = Submission(
            student_name="小红",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 1; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add(second)
        db.session.commit()

        assert process_diagnosis_job(second.public_id, fetch_before_diagnosis=True) == "success"
        assert len(fetch_calls) == 1


def test_process_job_message_raises_job_queue_error_for_unknown_job_type():
    from src.app.services.jobs import process_job_message

    try:
        process_job_message(job_type="unknown", submission_public_id="sub-1")
    except JobQueueError as exc:
        assert "未知任务类型" in str(exc)
    else:
        raise AssertionError("expected JobQueueError")


def test_process_student_hint_job_releases_db_session_before_ai_call(app, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    release_calls = []

    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    def fake_release_db_session():
        release_calls.append("released")
        db.session.remove()

    def fake_diagnose_student(self, payload: DiagnosisPayload):
        assert release_calls
        student_result = {
            "overall_assessment": "学生提示完成",
            "confidence": "medium",
            "possible_issues": [],
            "next_step_checks": ["先检查输入"],
            "encouragement_or_strategy": "继续加油",
        }
        return type(
            "StudentHintResponseStub",
            (),
            {
                "result": __import__("src.app.schemas", fromlist=["StudentHintResult"]).StudentHintResult.model_validate(student_result),
                "raw_content": "{}",
                "latency_ms": 120,
                "model_name": "deepseek-v4-pro",
            },
        )()

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose_student", fake_diagnose_student)
    monkeypatch.setattr("src.app.services.jobs._release_db_session", fake_release_db_session)

    with app.app_context():
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            student_hint_status="queued",
        )
        db.session.add(submission)
        db.session.commit()

        from src.app.services.jobs import process_student_hint_job

        assert process_student_hint_job(submission.public_id, fetch_before_diagnosis=True) == "success"


def test_process_diagnosis_job_avoids_duplicate_fetch_under_concurrency(tmp_path, monkeypatch):
    _clear_problem_snapshot_memory_cache()
    fetch_calls = []
    lock = threading.Lock()

    class ConcurrentConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'concurrent.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30, "check_same_thread": False}}
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-chat"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False
        OPENJUDGE_REQUEST_TIMEOUT = 1
        SUBMISSION_CODE_MAX_LENGTH = 20000
        RATE_LIMIT_MAX_SUBMISSIONS = 20
        RATE_LIMIT_WINDOW_SECONDS = 300
        JOB_QUEUE_BACKEND = "inline"
        INTERNAL_JOB_TOKEN = "test-internal-job-token"
        APP_BASE_URL = "http://localhost:5000"
        PROBLEM_SNAPSHOT_CACHE_ENABLED = True
        PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS = 86400

    def fake_fetch(self, url):
        with lock:
            fetch_calls.append(url)
        threading.Event().wait(0.1)
        return ProblemContent(
            normalized_url="http://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="desc",
            input_text="input",
            output_text="output",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="source",
            raw_excerpt="desc\ninput\noutput",
        )

    def fake_diagnose(self, payload: DiagnosisPayload):
        return _sample_diagnosis_response()

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    app = create_app(ConcurrentConfig)
    with app.app_context():
        db.create_all()
        first = Submission(
            student_name="甲",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        second = Submission(
            student_name="乙",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 1; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add_all([first, second])
        db.session.commit()
        public_ids = [first.public_id, second.public_id]

    errors = []

    def worker(public_id: str):
        try:
            with app.app_context():
                from src.app.services.jobs import process_diagnosis_job

                process_diagnosis_job(public_id, fetch_before_diagnosis=True)
        except Exception as exc:  # pragma: no cover - assertion path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(public_id,)) for public_id in public_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(fetch_calls) == 1
