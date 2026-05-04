from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.app.extensions import db
from src.app.models import AdminUser, DiagnosisRun, Submission, StudentUser
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


def test_admin_submission_detail_back_link_preserves_student_filter(app, client):
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
        student_id = student.id
        public_id = submission.public_id

    _login_admin(client)
    list_response = client.get(f"/admin/submissions?student_user_id={student_id}")
    list_soup = BeautifulSoup(list_response.data, "html.parser")

    assert list_response.status_code == 200
    detail_link = next(link for link in list_soup.select("a") if link.get_text(strip=True) == "查看详情")
    assert detail_link.get("href", "").startswith(f"/admin/submissions/{public_id}?next=")

    detail_response = client.get(detail_link.get("href"))
    detail_soup = BeautifulSoup(detail_response.data, "html.parser")

    assert detail_response.status_code == 200
    back_link = next(link for link in detail_soup.select("a") if link.get_text(strip=True) == "返回列表")
    assert back_link.get("href") == f"/admin/submissions?student_user_id={student_id}"


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
    assert "张小明（stu01）".encode() in response.data
    assert "stu01".encode() in response.data
    assert response.data.count("查看详情".encode()) == 2


def test_admin_submission_list_is_paginated_by_20(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.flush()

        submissions = [
            Submission(
                student_name="stu01",
                student_user=student,
                problem_url=f"http://noi.openjudge.cn/ch0107/{index:02d}/",
                code_text=f"int main() {{ return {index}; }}",
                created_at=datetime(2026, 5, 3, 0, index % 60, tzinfo=timezone.utc),
            )
            for index in range(21)
        ]
        db.session.add_all(submissions)
        db.session.commit()
        student_id = student.id

    _login_admin(client)
    first_page = client.get(f"/admin/students/{student_id}/submissions")
    second_page = client.get(f"/admin/students/{student_id}/submissions?page=2")

    assert first_page.status_code == 200
    assert "张小明（stu01）".encode() in first_page.data
    assert first_page.data.count("查看详情".encode()) == 20
    assert b"page=2" in first_page.data

    assert second_page.status_code == 200
    assert second_page.data.count("查看详情".encode()) == 1


def test_admin_submission_list_renders_beijing_time(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            created_at=datetime(2026, 5, 3, 0, 5, tzinfo=timezone.utc),
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/submissions")

    assert response.status_code == 200
    assert "2026-05-03 08:05".encode() in response.data


def test_admin_submission_list_student_label_uses_no_wrap_container(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="mcx", real_name="马晨曦", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="mcx",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/submissions")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    label = soup.select_one(".student-label")
    assert label is not None
    assert "马晨曦（mcx）" in label.get_text(strip=True)


def test_admin_submission_list_provides_student_view_link(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="owner", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="owner",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01:统计数字字符个数",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="success",
        )
        db.session.add_all([admin, student, submission])
        db.session.flush()
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="student",
                model_name="deepseek-v4-pro",
                prompt_version="student-v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "先检查循环边界。",
                    "confidence": "medium",
                    "possible_issues": [
                        {
                            "title": "边界可能偏一位",
                            "location": "主循环结束条件",
                            "evidence": "最后一个字符可能没被处理。",
                            "explanation": "这会让尾部数字漏统计。",
                            "suggested_fix": "先手推一遍样例。",
                        }
                    ],
                    "next_step_checks": ["手算 abc123。"],
                    "encouragement_or_strategy": "先模拟，再改最小一处。",
                },
                summary_text="先检查循环边界。",
            )
        )
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="teacher",
                model_name="deepseek-v4-pro",
                prompt_version="teacher-v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "老师版完整诊断",
                    "confidence": "high",
                    "missing_context": [],
                    "possible_issues": [],
                    "teacher_talking_points": [],
                    "next_step_checks": [],
                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                },
                summary_text="老师版完整诊断",
            )
        )
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    list_response = client.get("/admin/submissions")
    list_soup = BeautifulSoup(list_response.data, "html.parser")

    assert list_response.status_code == 200
    student_view_link = next(link for link in list_soup.select("a") if link.get_text(strip=True) == "学生界面")
    assert student_view_link.get("href", "").startswith(f"/admin/submissions/{public_id}/student-view")

    detail_response = client.get(student_view_link.get("href"))
    detail_soup = BeautifulSoup(detail_response.data, "html.parser")

    assert detail_response.status_code == 200
    assert "学生端".encode() in detail_response.data
    assert "先检查循环边界".encode() in detail_response.data
    assert "边界可能偏一位".encode() in detail_response.data
    assert "老师版完整诊断".encode() not in detail_response.data
    back_link = next(link for link in detail_soup.select("a") if link.get_text(strip=True) == "返回后台")
    assert back_link.get("href") == "/admin/submissions"


def test_admin_submission_list_uses_compact_single_page_layout(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01:统计数字字符个数",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            created_at=datetime(2026, 5, 3, 0, 5, tzinfo=timezone.utc),
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/submissions")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    headers = [item.get_text(" ", strip=True) for item in soup.select("thead th")]
    assert headers[:2] == ["提交信息", "状态与操作"]
    row = soup.select_one("tbody tr")
    assert row is not None
    assert "2026-05-03 08:05" in row.select_one(".submission-meta-line").get_text(" ", strip=True)
    assert "张小明（stu01）" in row.select_one(".submission-meta-line").get_text(" ", strip=True)
    assert "自己提交" in row.select_one(".submission-meta-line").get_text(" ", strip=True)
    assert "01:统计数字字符个数" in row.select_one(".submission-title-line").get_text(" ", strip=True)
    status_text = row.select_one(".submission-status-cell").get_text(" ", strip=True)
    assert "抓题" in status_text
    assert "学生提示" in status_text
    assert "老师诊断" in status_text
    assert "查看详情" in status_text
    assert "删除记录" in status_text


def test_admin_submission_list_styles_keep_full_title_and_compact_actions(client):
    response = client.get("/styles.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".submission-primary-cell {" in css
    assert "vertical-align: middle;" in css
    assert ".submission-meta-line {" in css
    assert ".submission-title-line {" in css
    assert "display: block;" in css
    assert "text-overflow: ellipsis;" not in css
    assert ".submission-ops-line {" in css
    assert "display: flex;" in css
    assert ".submission-ops-line .ghost-button," in css
    assert "width: auto;" in css
    assert ".submission-ops-line .mini-button {" in css
    assert "padding: 6px 10px;" in css
    assert "font-size: 12px;" in css
    assert ".submission-status-panel {" in css
    assert ".submission-ops-line {" in css


def test_admin_submission_actions_use_unified_button_style(app, client):
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

    _login_admin(client)
    response = client.get("/admin/submissions")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    detail_link = next(link for link in soup.select("a") if link.get_text(strip=True) == "查看详情")
    assert "ghost-button" in detail_link.get("class", [])
    assert "mini-button" in detail_link.get("class", [])


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
