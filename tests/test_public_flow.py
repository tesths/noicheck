from bs4 import BeautifulSoup

from src.app.extensions import db
from src.app.models import AdminUser, ProblemSnapshot, Submission
from src.app.services.auth import hash_password


def _login_admin(client) -> None:
    login_page = client.get("/admin/login")
    csrf_token = BeautifulSoup(login_page.data, "html.parser").select_one("input[name=csrf_token]")[
        "value"
    ]
    response = client.post(
        "/admin/login",
        data={"csrf_token": csrf_token, "username": "admin", "password": "secret123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _detail_csrf_token(client, public_id: str) -> str:
    detail_page = client.get(f"/admin/submissions/{public_id}")
    return BeautifulSoup(detail_page.data, "html.parser").select_one("input[name=csrf_token]")["value"]


def test_submit_persists_submission_and_queues_fetch_and_diagnosis(app, client, monkeypatch):
    def fail_if_fetch_called(self, url):
        raise AssertionError("提交接口不应同步抓题")

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fail_if_fetch_called)

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
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.problem_title is None
        assert submission.problem_path is None
        assert submission.fetch_status == "queued"
        assert submission.diagnosis_status == "queued"
        assert submission.problem_snapshot is None
        assert jobs == [
            {
                "job_type": "fetch-and-diagnose",
                "submission_public_id": submission.public_id,
                "requested_by": "system",
            }
        ]


def test_submit_success_page_shows_queued_status(app, client):
    response = client.post(
        "/submit",
        data={
            "student_name": "小明",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "#include <iostream>\nint main() { return 0; }",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "已进入后台排队".encode() in response.data
    assert "自动继续 AI 诊断".encode() in response.data
    assert "queued".encode() in response.data


def test_stylesheet_is_served(client):
    response = client.get("/styles.css")

    assert response.status_code == 200
    assert b":root" in response.data


def test_submit_page_references_stylesheet(client):
    response = client.get("/submit")

    assert response.status_code == 200
    assert b'/styles.css' in response.data


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


def test_admin_can_queue_diagnosis_when_fetch_succeeded(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="success",
            diagnosis_status="pending",
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
        db.session.add_all([admin, submission, snapshot])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={"csrf_token": _detail_csrf_token(client, public_id)},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.fetch_status == "success"
        assert submission.diagnosis_status == "queued"
        assert submission.latest_diagnosis_run is None
        assert jobs == [
            {
                "job_type": "diagnose-submission",
                "submission_public_id": public_id,
                "requested_by": "admin",
            }
        ]


def test_admin_queues_combined_job_when_fetch_not_ready(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="failed",
            diagnosis_status="pending",
        )
        db.session.add_all([admin, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={"csrf_token": _detail_csrf_token(client, public_id)},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.fetch_status == "queued"
        assert submission.diagnosis_status == "queued"
        assert submission.latest_diagnosis_run is None
        assert jobs == [
            {
                "job_type": "fetch-and-diagnose",
                "submission_public_id": public_id,
                "requested_by": "admin",
            }
        ]


def test_admin_does_not_requeue_diagnosis_when_already_processing(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        submission = Submission(
            student_name="小明",
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="success",
            diagnosis_status="queued",
        )
        db.session.add_all([admin, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    response = client.post(
        f"/admin/submissions/{public_id}/diagnose",
        data={},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "已有后台任务正在处理这条提交".encode() in response.data

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        jobs = app.extensions.get("job_queue_stub", {"jobs": []})["jobs"]

        assert submission.diagnosis_status == "queued"
        assert jobs == []
