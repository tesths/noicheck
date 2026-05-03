from src.app.extensions import db
from src.app.models import AdminUser, DiagnosisRun, Submission, StudentUser
from src.app.schemas import DiagnosisResult, StudentHintResult
from src.app.services.ai import DiagnosisResponse, StudentHintResponse
from src.app.services.auth import hash_password
from src.app.services.problem_fetcher import ProblemContent


def _login_admin(client) -> None:
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "secret123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _auth_headers() -> dict[str, str]:
    return {"X-Internal-Job-Token": "test-internal-job-token"}


def _problem_content() -> ProblemContent:
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


def test_admin_submission_list_shows_ai_model_switcher(app, client):
    with app.app_context():
        app.config["AI_MODEL"] = "deepseek-v4-pro"
        app.config["DEEPSEEK_MODEL"] = "deepseek-v4-pro"
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        db.session.add(admin)
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/submissions")

    assert response.status_code == 200
    assert "deepseek-v4-pro".encode() in response.data
    assert "deepseek-v4-flash".encode() in response.data


def test_admin_switched_model_applies_to_teacher_diagnosis_job(app, client, monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch(self, url):
        return _problem_content()

    def fake_diagnose(self, payload):
        captured["model_name"] = self.model_name
        return DiagnosisResponse(
            result=DiagnosisResult.model_validate(
                {
                    "overall_assessment": "检查字符统计逻辑。",
                    "confidence": "medium",
                    "missing_context": [],
                    "possible_issues": [],
                    "teacher_talking_points": [],
                    "next_step_checks": [],
                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                }
            ),
            raw_content="{}",
            latency_ms=10,
            model_name=self.model_name,
        )

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    with app.app_context():
        app.config["AI_MODEL"] = "deepseek-v4-pro"
        app.config["DEEPSEEK_MODEL"] = "deepseek-v4-pro"
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

    _login_admin(client)
    update_response = client.post(
        "/admin/settings/ai-model",
        data={"model_name": "deepseek-v4-flash"},
        follow_redirects=False,
    )

    assert update_response.status_code == 302

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        teacher_run = DiagnosisRun.query.filter_by(submission_id=submission.id, audience="teacher").one()

        assert captured["model_name"] == "deepseek-v4-flash"
        assert teacher_run.model_name == "deepseek-v4-flash"


def test_admin_switched_model_also_applies_to_student_hint_job(app, client, monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch(self, url):
        return _problem_content()

    def fake_diagnose_student(self, payload):
        captured["model_name"] = self.model_name
        return StudentHintResponse(
            result=StudentHintResult.model_validate(
                {
                    "overall_assessment": "先检查循环边界。",
                    "confidence": "medium",
                    "possible_issues": [],
                    "next_step_checks": [],
                    "encouragement_or_strategy": "先手算样例。",
                }
            ),
            raw_content="{}",
            latency_ms=10,
            model_name=self.model_name,
        )

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.services.jobs.DeepSeekDiagnosisService.diagnose_student", fake_diagnose_student)

    with app.app_context():
        app.config["AI_MODEL"] = "deepseek-v4-pro"
        app.config["DEEPSEEK_MODEL"] = "deepseek-v4-pro"
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            student_hint_status="queued",
            diagnosis_status="pending",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    update_response = client.post(
        "/admin/settings/ai-model",
        data={"model_name": "deepseek-v4-flash"},
        follow_redirects=False,
    )

    assert update_response.status_code == 302

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-student-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        student_run = DiagnosisRun.query.filter_by(submission_id=submission.id, audience="student").one()

        assert captured["model_name"] == "deepseek-v4-flash"
        assert student_run.model_name == "deepseek-v4-flash"
