from src.app.extensions import db
from src.app.models import AdminUser, Submission
from src.app.schemas import DiagnosisResult
from src.app.services.ai import DiagnosisResponse
from src.app.services.auth import hash_password
from src.app.services.problem_fetcher import ProblemFetchError


def test_submit_persists_submission_and_marks_diagnosis_pending(app, client, monkeypatch):
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
        assert submission.problem_title is None
        assert submission.fetch_status == "pending"
        assert submission.diagnosis_status == "pending"
        assert submission.latest_diagnosis_run is None


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
            problem_url="http://noi.openjudge.cn/ch0107/01/",
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


def test_admin_can_generate_diagnosis(app, client, monkeypatch):
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

    monkeypatch.setattr("src.app.routes.admin.DeepSeekDiagnosisService.diagnose", fake_diagnose)

    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="success",
            diagnosis_status="pending",
        )
        from src.app.models import ProblemSnapshot

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
        db.session.add_all([admin, submission, snapshot])
        db.session.commit()
        public_id = submission.public_id

    login_page = client.get("/admin/login")
    from bs4 import BeautifulSoup

    csrf_token = BeautifulSoup(login_page.data, "html.parser").select_one("input[name=csrf_token]")["value"]
    client.post(
        "/admin/login",
        data={"csrf_token": csrf_token, "username": "admin", "password": "secret123"},
        follow_redirects=False,
    )

    detail_page = client.get(f"/admin/submissions/{public_id}")
    detail_csrf = BeautifulSoup(detail_page.data, "html.parser").select_one("input[name=csrf_token]")["value"]
    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={"csrf_token": detail_csrf},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).first()
        assert submission.diagnosis_status == "success"
        assert submission.latest_diagnosis_run.structured_result_json["possible_issues"][0]["title"] == "没有正确判断数字字符"

    detail_after = client.get(f"/admin/submissions/{public_id}")
    assert detail_after.status_code == 200
    assert "诊断原因与可能位置".encode() in detail_after.data
    assert "正确的完整程序".encode() in detail_after.data
    assert "主逻辑判断分支".encode() in detail_after.data


def test_admin_stops_diagnosis_when_problem_fetch_fails(app, client, monkeypatch):
    def fake_fetch(self, url):
        raise ProblemFetchError("OpenJudge 暂时无法访问。")

    def fail_if_diagnose_called(self, payload):
        raise AssertionError("抓题失败后不应继续调用 AI")

    monkeypatch.setattr("src.app.routes.admin.OpenJudgeProblemFetcher.fetch", fake_fetch)
    monkeypatch.setattr("src.app.routes.admin.DeepSeekDiagnosisService.diagnose", fail_if_diagnose_called)

    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="pending",
            diagnosis_status="pending",
        )
        db.session.add_all([admin, submission])
        db.session.commit()
        public_id = submission.public_id

    login_page = client.get("/admin/login")
    from bs4 import BeautifulSoup

    csrf_token = BeautifulSoup(login_page.data, "html.parser").select_one("input[name=csrf_token]")["value"]
    client.post(
        "/admin/login",
        data={"csrf_token": csrf_token, "username": "admin", "password": "secret123"},
        follow_redirects=False,
    )

    detail_page = client.get(f"/admin/submissions/{public_id}")
    detail_csrf = BeautifulSoup(detail_page.data, "html.parser").select_one("input[name=csrf_token]")["value"]
    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={"csrf_token": detail_csrf},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).first()
        assert submission.fetch_status == "failed"
        assert submission.diagnosis_status == "failed"
        assert submission.latest_diagnosis_run.status == "failed"
        assert "抓取题面失败" in submission.latest_diagnosis_run.error_message

    detail_after = client.get(f"/admin/submissions/{public_id}")
    assert detail_after.status_code == 200
    assert "重新生成 AI 诊断".encode() in detail_after.data
