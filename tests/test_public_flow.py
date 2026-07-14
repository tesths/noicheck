from bs4 import BeautifulSoup

from src.app.extensions import db
from src.app.models import AdminUser, ProblemSnapshot, StudentUser, Submission
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


def test_home_page_shows_login_hub(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "学生登录".encode() in response.data
    assert "教师登录".encode() in response.data
    assert "必须登录后使用".encode() in response.data


def test_home_page_uses_simple_layout(client):
    response = client.get("/")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert soup.select_one(".hero-card") is not None
    assert soup.select_one(".showcase-metrics") is None
    assert soup.select_one(".showcase-card-list") is None


def test_submit_page_redirects_to_login_hub(client):
    response = client.get("/submit", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_submit_post_requires_login_and_does_not_write_submission(app, client):
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
    assert "请先登录".encode() in response.data

    with app.app_context():
        assert Submission.query.count() == 0


def test_stylesheet_is_served(client):
    response = client.get("/styles.css")

    assert response.status_code == 200
    assert b":root" in response.data


def test_stylesheet_does_not_use_underlines_for_buttons_or_links(client):
    response = client.get("/styles.css")

    assert response.status_code == 200
    assert b"text-decoration: underline;" not in response.data


def test_home_page_references_stylesheet(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'/styles.css' in response.data


def test_admin_pages_require_login(client):
    response = client.get("/admin/submissions", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_can_login_and_view_submission(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(
            nickname="xiaoming",
            real_name="小明",
            password_hash=hash_password("pw-1"),
            owner_admin=admin,
        )
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            problem_title="01:统计数字字符个数",
            problem_path="ch0107/01",
            fetch_status="success",
            diagnosis_status="failed",
        )
        db.session.add_all([admin, student, submission])
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


def test_admin_submission_list_uses_simple_panel_layout(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(
            nickname="xiaoming",
            real_name="小明",
            password_hash=hash_password("pw-1"),
            owner_admin=admin,
        )
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            problem_title="01:统计数字字符个数",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="failed",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/submissions")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert soup.select_one(".workspace-banner") is None
    assert soup.select_one(".toolbar-grid") is None
    assert soup.select_one(".table-shell") is not None


def test_admin_can_queue_diagnosis_when_fetch_succeeded(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(
            nickname="xiaoming",
            real_name="小明",
            password_hash=hash_password("pw-1"),
            owner_admin=admin,
        )
        submission = Submission(
            student_name="小明",
            student_user=student,
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
        db.session.add_all([admin, student, submission, snapshot])
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
        student = StudentUser(
            nickname="xiaoming",
            real_name="小明",
            password_hash=hash_password("pw-1"),
            owner_admin=admin,
        )
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="failed",
            diagnosis_status="pending",
        )
        db.session.add_all([admin, student, submission])
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
        student = StudentUser(
            nickname="xiaoming",
            real_name="小明",
            password_hash=hash_password("pw-1"),
            owner_admin=admin,
        )
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/20/",
            code_text="int main() { return 0; }",
            fetch_status="success",
            diagnosis_status="queued",
        )
        db.session.add_all([admin, student, submission])
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
