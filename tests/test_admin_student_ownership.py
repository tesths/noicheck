from src.app.extensions import db
from src.app.models import AdminUser, StudentUser, Submission
from src.app.services.auth import hash_password


def _login(client, username: str, password: str) -> None:
    response = client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_teacher_only_sees_own_students(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        owned_by_admin = StudentUser(
            nickname="old_student",
            real_name="旧学生",
            password_hash=hash_password("s1"),
            owner_admin=admin,
        )
        owned_by_pw = StudentUser(
            nickname="pw_student",
            real_name="新学生",
            password_hash=hash_password("s2"),
            owner_admin=teacher,
        )
        db.session.add_all([admin, teacher, owned_by_admin, owned_by_pw])
        db.session.commit()
        admin_student_id = owned_by_admin.id
        pw_student_id = owned_by_pw.id

    _login(client, "pw", "123456")
    response = client.get("/admin/students")
    assert response.status_code == 200
    assert "新学生".encode() in response.data
    assert "pw_student".encode() in response.data
    assert "旧学生".encode() not in response.data
    assert "old_student".encode() not in response.data

    denied = client.get(f"/admin/students/{admin_student_id}")
    assert denied.status_code == 404

    allowed = client.get(f"/admin/students/{pw_student_id}")
    assert allowed.status_code == 200
    assert "新学生".encode() in allowed.data


def test_teacher_only_sees_own_student_submissions(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        owned_by_admin = StudentUser(
            nickname="old_student",
            real_name="旧学生",
            password_hash=hash_password("s1"),
            owner_admin=admin,
        )
        owned_by_pw = StudentUser(
            nickname="pw_student",
            real_name="新学生",
            password_hash=hash_password("s2"),
            owner_admin=teacher,
        )
        submission_admin = Submission(
            student_name="old_student",
            student_user=owned_by_admin,
            problem_url="http://noi.openjudge.cn/ch0107/01/",
            code_text="int main() { return 0; }",
        )
        submission_pw = Submission(
            student_name="pw_student",
            student_user=owned_by_pw,
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main() { return 1; }",
        )
        db.session.add_all([admin, teacher, owned_by_admin, owned_by_pw, submission_admin, submission_pw])
        db.session.commit()
        admin_public_id = submission_admin.public_id
        pw_public_id = submission_pw.public_id

    _login(client, "pw", "123456")
    response = client.get("/admin/submissions")
    assert response.status_code == 200
    assert "新学生".encode() in response.data
    assert "pw_student".encode() in response.data
    assert "旧学生".encode() not in response.data
    assert "old_student".encode() not in response.data

    denied = client.get(f"/admin/submissions/{admin_public_id}")
    assert denied.status_code == 404

    allowed = client.get(f"/admin/submissions/{pw_public_id}")
    assert allowed.status_code == 200
    assert "pw_student".encode() in allowed.data or "新学生".encode() in allowed.data


def test_create_student_assigns_current_teacher(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        db.session.add_all([admin, teacher])
        db.session.commit()
        teacher_id = teacher.id

    _login(client, "pw", "123456")
    response = client.post(
        "/admin/students",
        data={
            "nickname": "fresh_stu",
            "real_name": "新同学",
            "password": "abc123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        student = StudentUser.query.filter_by(nickname="fresh_stu").one()
        assert student.owner_admin_id == teacher_id
        assert student.real_name == "新同学"


def test_teacher_can_bulk_import_students(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        db.session.add_all([admin, teacher])
        db.session.commit()
        teacher_id = teacher.id

    _login(client, "pw", "123456")
    response = client.post(
        "/admin/students/bulk-import",
        data={
            "students_text": "stu01,张小明,pw-001\nstu02,李小红,pw-002",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        students = StudentUser.query.order_by(StudentUser.nickname).all()
        assert [student.nickname for student in students] == ["stu01", "stu02"]
        assert [student.real_name for student in students] == ["张小明", "李小红"]
        assert {student.owner_admin_id for student in students} == {teacher_id}


def test_teacher_bulk_import_rejects_other_teacher_usernames_atomically(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        existing = StudentUser(
            nickname="taken",
            real_name="旧学生",
            password_hash=hash_password("s1"),
            owner_admin=admin,
        )
        db.session.add_all([admin, teacher, existing])
        db.session.commit()

    _login(client, "pw", "123456")
    response = client.post(
        "/admin/students/bulk-import",
        data={
            "students_text": "fresh,新同学,pw-001\ntaken,抢名学生,pw-002",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "taken".encode() in response.data
    assert "其他老师占用".encode() in response.data
    with app.app_context():
        assert StudentUser.query.filter_by(nickname="fresh").first() is None
        student = StudentUser.query.filter_by(nickname="taken").one()
        assert student.real_name == "旧学生"
        assert student.owner_admin.username == "admin"


def test_teacher_cannot_claim_other_teachers_student_username(app, client):
    with app.app_context():
        admin = AdminUser(username="admin", password_hash=hash_password("secret123"))
        teacher = AdminUser(username="pw", password_hash=hash_password("123456"))
        existing = StudentUser(
            nickname="shared_name",
            real_name="旧学生",
            password_hash=hash_password("s1"),
            owner_admin=admin,
        )
        db.session.add_all([admin, teacher, existing])
        db.session.commit()

    _login(client, "pw", "123456")
    response = client.post(
        "/admin/students",
        data={
            "nickname": "shared_name",
            "real_name": "抢名学生",
            "password": "abc123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "其他老师占用".encode() in response.data

    with app.app_context():
        student = StudentUser.query.filter_by(nickname="shared_name").one()
        assert student.real_name == "旧学生"
        assert student.owner_admin.username == "admin"
