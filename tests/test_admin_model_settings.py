from src.app.extensions import db
from src.app.models import AdminUser, DiagnosisRun, Submission, StudentUser, SystemSetting
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


def test_admin_system_settings_page_shows_ai_model_switcher(app, client):
    with app.app_context():
        app.config["AI_MODEL"] = "deepseek-v4-pro"
        app.config["DEEPSEEK_MODEL"] = "deepseek-v4-pro"
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        db.session.add(admin)
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/settings")

    assert response.status_code == 200
    assert "系统设置".encode() in response.data
    assert "deepseek-v4-pro".encode() in response.data
    assert "deepseek-v4-flash".encode() in response.data
    assert b'name="teacher_system_prompt"' in response.data
    assert b'name="student_system_prompt"' in response.data
    assert "完整正确程序".encode() in response.data
    assert "不要提供正确答案".encode() in response.data


def test_admin_can_save_custom_ai_prompts(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        db.session.add(admin)
        db.session.commit()

    _login_admin(client)
    response = client.post(
        "/admin/settings/prompts",
        data={
            "teacher_system_prompt": "老师自定义系统提示词",
            "student_system_prompt": "学生自定义系统提示词",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        teacher_prompt = db.session.get(SystemSetting, "teacher_system_prompt")
        student_prompt = db.session.get(SystemSetting, "student_system_prompt")

        assert teacher_prompt is not None
        assert teacher_prompt.value == "老师自定义系统提示词"
        assert student_prompt is not None
        assert student_prompt.value == "学生自定义系统提示词"


def test_admin_rejects_blank_custom_ai_prompts(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        db.session.add_all(
            [
                admin,
                SystemSetting(key="teacher_system_prompt", value="旧老师提示词"),
                SystemSetting(key="student_system_prompt", value="旧学生提示词"),
            ]
        )
        db.session.commit()

    _login_admin(client)
    response = client.post(
        "/admin/settings/prompts",
        data={
            "teacher_system_prompt": "   ",
            "student_system_prompt": "学生新提示词",
        },
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "请填写老师和学生的系统提示词。".encode() in response.data

    with app.app_context():
        teacher_prompt = db.session.get(SystemSetting, "teacher_system_prompt")
        student_prompt = db.session.get(SystemSetting, "student_system_prompt")

        assert teacher_prompt.value == "旧老师提示词"
        assert student_prompt.value == "旧学生提示词"


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
        student = StudentUser(owner_admin=admin, nickname="stu01", password_hash=hash_password("pw-1"))
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


def test_admin_custom_teacher_prompt_applies_to_teacher_diagnosis_job(app, client, monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch(self, url):
        return _problem_content()

    def fake_diagnose(self, payload):
        captured["teacher_system_prompt"] = self.teacher_system_prompt
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
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add_all(
            [
                admin,
                submission,
                SystemSetting(key="teacher_system_prompt", value="老师自定义系统提示"),
            ]
        )
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}
    assert captured["teacher_system_prompt"] == "老师自定义系统提示"


def test_admin_custom_student_prompt_applies_to_student_hint_job(app, client, monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch(self, url):
        return _problem_content()

    def fake_diagnose_student(self, payload):
        captured["student_system_prompt"] = self.student_system_prompt
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
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(owner_admin=admin, nickname="stu01", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            student_hint_status="queued",
            diagnosis_status="pending",
        )
        db.session.add_all(
            [
                admin,
                student,
                submission,
                SystemSetting(key="student_system_prompt", value="学生自定义系统提示"),
            ]
        )
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-student-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "success"}
    assert captured["student_system_prompt"] == "学生自定义系统提示"
