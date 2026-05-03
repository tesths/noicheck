from src.app.extensions import db
from src.app.models import AdminUser, Submission, StudentUser
from src.app.services.auth import hash_password


def _login_admin(client) -> None:
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "secret123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _login_student(client, nickname: str, password: str) -> None:
    response = client.post(
        "/student/login",
        data={"nickname": nickname, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _auth_headers() -> dict[str, str]:
    return {"X-Internal-Job-Token": "test-internal-job-token"}


def test_admin_can_filter_submissions_by_student(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student_a = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        student_b = StudentUser(nickname="stu02", real_name="李小红", password_hash=hash_password("pw-2"))
        submission_a = Submission(
            student_name="stu01",
            student_user=student_a,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        submission_b = Submission(
            student_name="stu02",
            student_user=student_b,
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main() { return 0; }",
        )
        db.session.add_all([admin, student_a, student_b, submission_a, submission_b])
        db.session.commit()
        student_a_id = student_a.id

    _login_admin(client)
    response = client.get(f"/admin/submissions?student_user_id={student_a_id}")

    assert response.status_code == 200
    assert "张小明".encode() in response.data
    assert "stu01".encode() in response.data
    assert response.data.count("查看详情".encode()) == 1


def test_admin_can_view_a_single_students_submission_history(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission_a = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        submission_b = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main() { return 1; }",
        )
        db.session.add_all([admin, student, submission_a, submission_b])
        db.session.commit()
        student_id = student.id

    _login_admin(client)
    response = client.get(f"/admin/students/{student_id}/submissions")

    assert response.status_code == 200
    assert "张小明".encode() in response.data
    assert "stu01".encode() in response.data
    assert response.data.count("查看详情".encode()) == 2


def test_admin_can_soft_delete_submission_and_hide_it_from_lists(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    delete_response = client.post(
        f"/admin/submissions/{public_id}/delete",
        data={},
        follow_redirects=False,
    )

    assert delete_response.status_code == 302

    with app.app_context():
        submission = db.session.execute(db.select(Submission).filter_by(public_id=public_id)).scalar_one()
        assert getattr(submission, "deleted_at", None) is not None

    admin_list_response = client.get("/admin/submissions")
    assert admin_list_response.status_code == 200
    assert "查看详情".encode() not in admin_list_response.data

    admin_detail_response = client.get(f"/admin/submissions/{public_id}")
    assert admin_detail_response.status_code == 404

    _login_student(client, "stu01", "pw-1")
    student_list_response = client.get("/student/submissions")
    assert student_list_response.status_code == 200
    assert "查看详情".encode() not in student_list_response.data


def test_deleted_submission_jobs_are_skipped(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            fetch_status="queued",
            diagnosis_status="queued",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    delete_response = client.post(
        f"/admin/submissions/{public_id}/delete",
        data={},
        follow_redirects=False,
    )
    assert delete_response.status_code == 302

    response = client.post(
        "/internal/jobs/process",
        json={"job_type": "fetch-and-diagnose", "submission_public_id": public_id},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json == {"ok": True, "status": "skipped"}
