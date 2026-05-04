from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.app.extensions import db
from src.app.models import AdminUser, DiagnosisRun, ProblemSnapshot, Submission, StudentUser
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


def _student_detail_csrf_token(client, public_id: str) -> str:
    page = client.get(f"/student/submissions/{public_id}")
    return BeautifulSoup(page.data, "html.parser").select_one("input[name=csrf_token]")["value"]


def test_student_pages_require_login(client):
    response = client.get("/student/submissions", follow_redirects=False)

    assert response.status_code == 302
    assert "/student/login" in response.headers["Location"]


def test_admin_login_clears_student_session(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()

    _login_student(client, "stu01", "pw-1")
    student_response = client.get("/student/submissions")
    assert student_response.status_code == 200

    _login_admin(client)
    admin_response = client.get("/admin/submissions")
    student_after_admin_login = client.get("/student/submissions", follow_redirects=False)

    assert admin_response.status_code == 200
    assert student_after_admin_login.status_code == 302
    assert "/student/login" in student_after_admin_login.headers["Location"]


def test_student_login_clears_admin_session(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()

    _login_admin(client)
    admin_response = client.get("/admin/submissions")
    assert admin_response.status_code == 200

    _login_student(client, "stu01", "pw-1")
    student_response = client.get("/student/submissions")
    admin_after_student_login = client.get("/admin/submissions", follow_redirects=False)

    assert student_response.status_code == 200
    assert admin_after_student_login.status_code == 302
    assert "/admin/login" in admin_after_student_login.headers["Location"]


def test_admin_can_create_reset_and_disable_student(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        db.session.add(admin)
        db.session.commit()

    _login_admin(client)
    create_response = client.post(
        "/admin/students",
        data={"nickname": "stu01", "real_name": "张小明", "password": "pw-001"},
        follow_redirects=False,
    )

    assert create_response.status_code == 302

    with app.app_context():
        student = StudentUser.query.filter_by(nickname="stu01").one()
        student_id = student.id
        assert getattr(student, "real_name", None) == "张小明"

    _login_student(client, "stu01", "pw-001")
    _login_admin(client)

    student_list_response = client.get("/admin/students")
    assert student_list_response.status_code == 200
    assert "张小明".encode() in student_list_response.data
    assert "stu01".encode() in student_list_response.data
    reset_response = client.post(
        f"/admin/students/{student_id}/reset-password",
        data={"password": "pw-002"},
        follow_redirects=False,
    )
    assert reset_response.status_code == 302

    client.post("/student/logout", data={}, follow_redirects=False)
    relogin_response = client.post(
        "/student/login",
        data={"nickname": "stu01", "password": "pw-001"},
        follow_redirects=False,
    )
    assert relogin_response.status_code == 401

    _login_student(client, "stu01", "pw-002")
    _login_admin(client)
    toggle_response = client.post(
        f"/admin/students/{student_id}/toggle-active",
        data={},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 302

    client.post("/student/logout", data={}, follow_redirects=False)
    disabled_login = client.post(
        "/student/login",
        data={"nickname": "stu01", "password": "pw-002"},
        follow_redirects=False,
    )
    assert disabled_login.status_code == 401


def test_admin_can_update_student_real_name(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()
        student_id = student.id

    _login_admin(client)
    update_response = client.post(
        f"/admin/students/{student_id}/profile",
        data={"real_name": "张老师"},
        follow_redirects=False,
    )

    assert update_response.status_code == 302

    with app.app_context():
        student = StudentUser.query.filter_by(id=student_id).one()
        assert student.real_name == "张老师"


def test_admin_can_delete_student_and_hide_related_submissions(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="pending",
        )
        db.session.add_all([admin, student, submission])
        db.session.commit()
        student_id = student.id
        public_id = submission.public_id

    _login_admin(client)
    delete_response = client.post(
        f"/admin/students/{student_id}/delete",
        data={},
        follow_redirects=False,
    )

    assert delete_response.status_code == 302
    assert delete_response.headers["Location"].endswith("/admin/students")

    with app.app_context():
        assert StudentUser.query.filter_by(id=student_id).first() is None
        hidden_submission = Submission.query.filter_by(public_id=public_id).one()
        assert hidden_submission.student_user_id is None
        assert hidden_submission.deleted_at is not None

    student_list_response = client.get("/admin/students")
    admin_submission_list_response = client.get("/admin/submissions")
    assert student_list_response.status_code == 200
    assert "张小明".encode() not in student_list_response.data
    assert admin_submission_list_response.status_code == 200
    assert public_id.encode() not in admin_submission_list_response.data

    relogin_response = client.post(
        "/student/login",
        data={"nickname": "stu01", "password": "pw-1"},
        follow_redirects=False,
    )
    assert relogin_response.status_code == 401


def test_student_management_actions_use_unified_button_style(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/students")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    detail_link = next(link for link in soup.select("a") if link.get_text(strip=True) == "管理学生")
    assert "ghost-button" in detail_link.get("class", [])
    assert "mini-button" in detail_link.get("class", [])


def test_student_management_page_uses_summary_list_layout(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="mcx", real_name="马晨曦", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()

    _login_admin(client)
    response = client.get("/admin/students")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    table = soup.select_one(".student-overview-table")
    assert table is not None
    assert soup.select_one(".student-name-stack") is None
    assert soup.select_one(".student-actions-stack") is None


def test_admin_can_open_student_detail_page(app, client):
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

    _login_admin(client)
    response = client.get(f"/admin/students/{student_id}")

    assert response.status_code == 200
    assert "张小明（stu01）".encode() in response.data
    assert "账号操作".encode() in response.data
    assert "重置密码".encode() in response.data
    assert "查看这个学生的全部提交".encode() in response.data


def test_student_detail_actions_can_redirect_back_to_detail(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", real_name="张小明", password_hash=hash_password("pw-1"))
        db.session.add_all([admin, student])
        db.session.commit()
        student_id = student.id

    _login_admin(client)
    response = client.post(
        f"/admin/students/{student_id}/profile",
        data={"real_name": "张老师", "return_to": "detail"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/students/{student_id}")


def test_student_submission_list_is_paginated_by_20(app, client):
    with app.app_context():
        student = StudentUser(nickname="小明", real_name="张小明", password_hash=hash_password("pass-123"))
        db.session.add(student)
        db.session.flush()
        submissions = [
            Submission(
                student_name="小明",
                student_user=student,
                problem_url=f"http://noi.openjudge.cn/ch0107/{index:02d}/",
                code_text=f"int main() {{ return {index}; }}",
                created_at=datetime(2026, 5, 3, 0, index % 60, tzinfo=timezone.utc),
            )
            for index in range(21)
        ]
        db.session.add_all(submissions)
        db.session.commit()

    _login_student(client, "小明", "pass-123")
    first_page = client.get("/student/submissions")
    second_page = client.get("/student/submissions?page=2")

    assert first_page.status_code == 200
    assert first_page.data.count("查看详情".encode()) == 20
    assert b"page=2" in first_page.data

    assert second_page.status_code == 200
    assert second_page.data.count("查看详情".encode()) == 1


def test_student_submission_list_uses_centered_table_layout(app, client):
    with app.app_context():
        student = StudentUser(nickname="小明", real_name="张小明", password_hash=hash_password("pass-123"))
        submission = Submission(
            student_name="小明",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            problem_title="01:统计数字字符个数",
            code_text="int main() { return 0; }",
        )
        db.session.add_all([student, submission])
        db.session.commit()

    _login_student(client, "小明", "pass-123")
    response = client.get("/student/submissions")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    table = soup.select_one("table.student-submission-table")
    assert table is not None


def test_student_submission_list_styles_center_table_cells(client):
    response = client.get("/styles.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".student-submission-table td {" in css
    assert "vertical-align: middle;" in css


def test_student_new_page_shows_two_flow_options(app, client):
    with app.app_context():
        student = StudentUser(nickname="小明", password_hash=hash_password("pass-123"))
        db.session.add(student)
        db.session.commit()

    _login_student(client, "小明", "pass-123")
    response = client.get("/student/submissions/new")

    assert response.status_code == 200
    assert "自己提交".encode() in response.data
    assert "提交给老师".encode() in response.data


def test_student_self_check_submission_queues_student_hint_job(app, client, monkeypatch):
    def fail_if_fetch_called(self, url):
        raise AssertionError("学生提交接口不应同步抓题")

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fail_if_fetch_called)

    with app.app_context():
        student = StudentUser(nickname="小明", password_hash=hash_password("pass-123"))
        db.session.add(student)
        db.session.commit()

    _login_student(client, "小明", "pass-123")
    response = client.post(
        "/student/submissions/new/self-check",
        data={
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "#include <iostream>\nint main() { return 0; }",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/student/submissions/" in response.headers["Location"]

    with app.app_context():
        submission = Submission.query.one()
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.student_name == "小明"
        assert submission.student_user.nickname == "小明"
        assert submission.submission_mode == "self_check"
        assert submission.fetch_status == "queued"
        assert submission.student_hint_status == "queued"
        assert submission.diagnosis_status == "pending"
        assert jobs == [
            {
                "job_type": "fetch-and-student-diagnose",
                "submission_public_id": submission.public_id,
                "requested_by": "student",
            }
        ]


def test_student_teacher_review_submission_queues_teacher_diagnosis_job(app, client, monkeypatch):
    def fail_if_fetch_called(self, url):
        raise AssertionError("学生提交接口不应同步抓题")

    monkeypatch.setattr("src.app.services.jobs.OpenJudgeProblemFetcher.fetch", fail_if_fetch_called)

    with app.app_context():
        student = StudentUser(nickname="小红", password_hash=hash_password("pass-456"))
        db.session.add(student)
        db.session.commit()

    _login_student(client, "小红", "pass-456")
    response = client.post(
        "/student/submissions/new/teacher-review",
        data={
            "problem_url": "http://noi.openjudge.cn/ch0107/02/",
            "code_text": "#include <iostream>\nint main() { return 0; }",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/student/submissions/" in response.headers["Location"]

    with app.app_context():
        submission = Submission.query.one()
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.student_name == "小红"
        assert submission.student_user.nickname == "小红"
        assert submission.submission_mode == "teacher_review"
        assert submission.fetch_status == "queued"
        assert submission.student_hint_status == "pending"
        assert submission.diagnosis_status == "queued"
        assert jobs == [
            {
                "job_type": "fetch-and-diagnose",
                "submission_public_id": submission.public_id,
                "requested_by": "student",
            }
        ]


def test_student_list_and_detail_are_scoped_to_owner(app, client):
    with app.app_context():
        owner = StudentUser(nickname="owner", password_hash=hash_password("pw-1"))
        other = StudentUser(nickname="other", password_hash=hash_password("pw-2"))
        owned_submission = Submission(
            student_name="owner",
            student_user=owner,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="pending",
        )
        other_submission = Submission(
            student_name="other",
            student_user=other,
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
            diagnosis_status="pending",
        )
        db.session.add_all([owner, other, owned_submission, other_submission])
        db.session.flush()
        db.session.add(
            DiagnosisRun(
                submission=owned_submission,
                audience="student",
                model_name="deepseek-v4-pro",
                prompt_version="student-v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "循环边界还要再检查。",
                    "confidence": "medium",
                    "possible_issues": [
                        {
                            "title": "边界可能偏一位",
                            "location": "for 循环结束条件",
                            "evidence": "最后一个字符可能没有被处理。",
                            "explanation": "这样会漏掉尾部数字。",
                            "suggested_fix": "重新检查循环终止条件和下标变化。",
                        }
                    ],
                    "next_step_checks": ["手算 abc123 和 0 的结果。"],
                    "encouragement_or_strategy": "先别急着重写，先把样例手推一遍。",
                },
                summary_text="循环边界还要再检查。",
            )
        )
        db.session.add(
            DiagnosisRun(
                submission=owned_submission,
                audience="teacher",
                model_name="deepseek-v4-pro",
                prompt_version="v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "教师版完整诊断",
                    "confidence": "high",
                    "missing_context": [],
                    "possible_issues": [],
                    "teacher_talking_points": [],
                    "next_step_checks": [],
                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                },
                summary_text="教师版完整诊断",
            )
        )
        db.session.commit()
        owned_public_id = owned_submission.public_id
        other_public_id = other_submission.public_id

    _login_student(client, "owner", "pw-1")
    list_response = client.get("/student/submissions")

    assert list_response.status_code == 200
    assert "owner".encode() in list_response.data
    assert "other".encode() not in list_response.data
    assert "自己提交".encode() in list_response.data

    detail_response = client.get(f"/student/submissions/{owned_public_id}")
    assert detail_response.status_code == 200
    assert "循环边界还要再检查".encode() in detail_response.data
    assert "边界可能偏一位".encode() in detail_response.data
    assert "教师版完整诊断".encode() not in detail_response.data
    assert "correct_program".encode() not in detail_response.data
    assert "正确的完整程序".encode() not in detail_response.data

    forbidden_response = client.get(f"/student/submissions/{other_public_id}")
    assert forbidden_response.status_code == 404


def test_teacher_review_detail_hides_teacher_result_from_student(app, client):
    with app.app_context():
        student = StudentUser(nickname="owner", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="owner",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/03/",
            code_text="int main() { return 0; }",
            submission_mode="teacher_review",
            fetch_status="success",
            student_hint_status="pending",
            diagnosis_status="success",
        )
        db.session.add_all([student, submission])
        db.session.flush()
        db.session.add(
            DiagnosisRun(
                submission=submission,
                audience="teacher",
                model_name="deepseek-v4-pro",
                prompt_version="v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "老师版完整诊断",
                    "confidence": "high",
                    "missing_context": [],
                    "possible_issues": [],
                    "teacher_talking_points": ["先看循环边界。"],
                    "next_step_checks": ["手动代样例。"],
                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                },
                summary_text="老师版完整诊断",
            )
        )
        db.session.commit()
        public_id = submission.public_id

    _login_student(client, "owner", "pw-1")
    detail_response = client.get(f"/student/submissions/{public_id}")

    assert detail_response.status_code == 200
    assert "已提交给老师".encode() in detail_response.data
    assert "老师版完整诊断".encode() not in detail_response.data
    assert "正确的完整程序".encode() not in detail_response.data
    assert "correct_program".encode() not in detail_response.data


def test_admin_detail_hides_student_hint_and_shows_teacher_diagnosis_for_self_check_submission(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="owner", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="owner",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/04/",
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
                            "evidence": "可能漏掉最后一个字符。",
                            "explanation": "这样会让尾部数字没被统计。",
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
                prompt_version="v1",
                status="success",
                structured_result_json={
                    "overall_assessment": "核心问题更像是循环结束条件写错了。",
                    "confidence": "high",
                    "missing_context": [],
                    "possible_issues": [
                        {
                            "title": "结束条件少看了一位",
                            "location": "主循环结束条件",
                            "evidence": "最后一个字符可能没有进入判断。",
                            "explanation": "这会让尾部数字漏统计。",
                            "suggested_fix": "检查循环边界是否覆盖到最后一个字符。",
                        }
                    ],
                    "teacher_talking_points": ["先让学生手算最后一个字符会不会被检查到。"],
                    "next_step_checks": ["用 abc123 和 000 再测一次。"],
                    "correct_program": "#include <iostream>\nint main(){return 0;}",
                },
                summary_text="核心问题更像是循环结束条件写错了。",
            )
        )
        db.session.commit()
        public_id = submission.public_id

    _login_admin(client)
    list_response = client.get("/admin/submissions")
    detail_response = client.get(f"/admin/submissions/{public_id}")

    assert list_response.status_code == 200
    assert "自己提交".encode() in list_response.data
    assert "学生提示".encode() in list_response.data
    assert detail_response.status_code == 200
    assert "学生提示".encode() not in detail_response.data
    assert "学生提示状态".encode() not in detail_response.data
    assert "先检查循环边界".encode() not in detail_response.data
    assert "边界可能偏一位".encode() not in detail_response.data
    assert "AI 诊断".encode() in detail_response.data
    assert "核心问题更像是循环结束条件写错了".encode() in detail_response.data
    assert "结束条件少看了一位".encode() in detail_response.data
    assert "参考程序".encode() in detail_response.data
    assert b"&lt;iostream&gt;" in detail_response.data


def test_admin_can_queue_teacher_diagnosis_after_student_hint_succeeds(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        student = StudentUser(nickname="stu01", password_hash=hash_password("pw-1"))
        submission = Submission(
            student_name="stu01",
            student_user=student,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
            submission_mode="self_check",
            fetch_status="success",
            student_hint_status="success",
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
        data={},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        submission = Submission.query.filter_by(public_id=public_id).one()
        jobs = app.extensions["job_queue_stub"]["jobs"]

        assert submission.student_hint_status == "success"
        assert submission.diagnosis_status == "queued"
        assert jobs == [
            {
                "job_type": "diagnose-submission",
                "submission_public_id": public_id,
                "requested_by": "admin",
            }
        ]
