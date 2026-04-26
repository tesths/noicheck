from src.app.extensions import db
from src.app.models import AdminUser, Submission
from src.app.schemas import DiagnosisResult
from src.app.services.ai import DiagnosisResponse
from src.app.services.auth import hash_password
from src.app.services.problem_fetcher import ProblemContent


def test_submit_persists_submission_and_diagnosis(app, client, monkeypatch):
    def fake_fetch(self, url):
        return ProblemContent(
            normalized_url="https://noi.openjudge.cn/ch0107/01/",
            problem_path="ch0107/01",
            title="01:统计数字字符个数",
            description_text="输入一行字符，统计数字字符个数。",
            input_text="一行字符串。",
            output_text="输出数字字符个数。",
            sample_input_text="abc123",
            sample_output_text="3",
            source_text="unit-test",
            raw_excerpt="摘要",
        )

    def fake_diagnose(self, payload):
        return DiagnosisResponse(
            result=DiagnosisResult.model_validate(
                {
                    "overall_assessment": "更像是字符统计逻辑有遗漏。",
                    "confidence": "medium",
                    "missing_context": [],
                    "possible_issues": [
                        {
                            "title": "没有正确判断数字字符",
                            "evidence": "代码中未见 isdigit 或范围判断。",
                            "explanation": "可能把所有字符都累计了。",
                            "suggested_fix": "只在字符位于 '0' 到 '9' 时递增计数。",
                        }
                    ],
                    "teacher_talking_points": ["先检查判断条件是否只针对数字。"],
                    "next_step_checks": ["用 abc123 和 000 做自测。"],
                }
            ),
            raw_content="{}",
            latency_ms=120,
            model_name="deepseek-chat",
        )

    monkeypatch.setattr("src.app.routes.public.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.routes.public.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    response = client.post(
        "/submit",
        data={
            "student_name": "小明",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "#include <iostream>\nint main() { return 0; }",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/submit/success/" in response.headers["Location"]

    with app.app_context():
        submission = Submission.query.one()
        assert submission.problem_title == "01:统计数字字符个数"
        assert submission.fetch_status == "success"
        assert submission.diagnosis_status == "success"
        assert submission.latest_diagnosis_run.structured_result_json["possible_issues"][0]["title"] == "没有正确判断数字字符"


def test_submit_rejects_invalid_url(client):
    response = client.post(
        "/submit",
        data={
            "student_name": "小明",
            "problem_url": "https://example.com/a",
            "code_text": "int main() {}",
        },
    )

    assert response.status_code == 400


def test_admin_pages_require_login(client):
    response = client.get("/admin/submissions", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_can_login_and_view_submission(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="https://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            problem_title="01:统计数字字符个数",
            problem_path="ch0107/01",
            fetch_status="success",
            diagnosis_status="failed",
        )
        db.session.add(admin)
        db.session.add(submission)
        db.session.commit()
        public_id = submission.public_id

    login_response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    list_response = client.get("/admin/submissions")
    assert list_response.status_code == 200
    assert "小明".encode() in list_response.data

    detail_response = client.get(f"/admin/submissions/{public_id}")
    assert detail_response.status_code == 200
    assert "统计数字字符个数".encode() in detail_response.data
