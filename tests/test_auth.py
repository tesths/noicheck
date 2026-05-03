from pathlib import Path
import sqlite3

import sqlalchemy.exc

from src.app import create_app
from src.app.extensions import db
from src.app.models import AdminUser, Submission
from src.app.services.auth import authenticate_admin, hash_client_ip, hash_password, verify_password


def test_authenticate_admin_returns_user(app):
    with app.app_context():
        admin = AdminUser(username="teacher", password_hash=hash_password("pass123"))
        db.session.add(admin)
        db.session.commit()

        authenticated = authenticate_admin("teacher", "pass123")

        assert authenticated is not None
        assert authenticated.username == "teacher"


def test_hash_client_ip_is_stable():
    assert hash_client_ip("127.0.0.1") == hash_client_ip("127.0.0.1")


def test_bootstrap_creates_tables_and_admin(tmp_path):
    database_path = tmp_path / "bootstrap.db"

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = "bootstrap-admin"
        ADMIN_INIT_PASSWORD = "bootstrap-pass"
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    app = create_app(BootstrapConfig)
    with app.app_context():
        admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(admin.password_hash, "bootstrap-pass")
        assert Path(database_path).exists()
        db.session.remove()


def test_bootstrap_updates_existing_admin_password(tmp_path):
    database_path = tmp_path / "bootstrap-update.db"

    class FirstBootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = "bootstrap-admin"
        ADMIN_INIT_PASSWORD = "first-pass"
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    class SecondBootstrapConfig(FirstBootstrapConfig):
        ADMIN_INIT_PASSWORD = "second-pass"

    first_app = create_app(FirstBootstrapConfig)
    with first_app.app_context():
        first_admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(first_admin.password_hash, "first-pass")
        db.session.remove()

    second_app = create_app(SecondBootstrapConfig)
    with second_app.app_context():
        second_admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(second_admin.password_hash, "second-pass")
        db.session.remove()


def test_bootstrap_db_failure_does_not_crash_app(monkeypatch):
    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = "bootstrap-admin"
        ADMIN_INIT_PASSWORD = "bootstrap-pass"
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    monkeypatch.setattr("src.app.bootstrap.db.create_all", lambda: (_ for _ in ()).throw(sqlalchemy.exc.OperationalError("stmt", {}, Exception("db down"))))

    app = create_app(BootstrapConfig)
    with app.app_context():
        assert "建表或修复旧表失败" in app.config["BOOTSTRAP_LAST_ERROR"]


def test_bootstrap_repairs_legacy_submissions_schema(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            student_name VARCHAR(80) NOT NULL,
            problem_url VARCHAR(500) NOT NULL,
            code_text TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO submissions (student_name, problem_url, code_text)
        VALUES ('旧数据学生', 'http://noi.openjudge.cn/ch0107/01/', 'int main() { return 0; }')
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    app = create_app(BootstrapConfig)
    with app.app_context():
        legacy_submission = Submission.query.filter_by(student_name="旧数据学生").one()
        assert legacy_submission.public_id
        assert legacy_submission.problem_source == "openjudge"
        assert legacy_submission.language == "cpp"
        assert legacy_submission.submission_mode == "teacher_review"
        assert legacy_submission.fetch_status == "pending"
        assert legacy_submission.diagnosis_status == "pending"

        new_submission = Submission(
            student_name="新学生",
            problem_url="http://noi.openjudge.cn/ch0107/02/",
            code_text="int main() { return 0; }",
            language="cpp",
            fetch_status="pending",
            diagnosis_status="pending",
        )
        db.session.add(new_submission)
        db.session.commit()
        assert new_submission.public_id


def test_bootstrap_repairs_duplicate_public_ids_before_creating_unique_index(tmp_path):
    database_path = tmp_path / "legacy-duplicate-public-id.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            public_id VARCHAR(32),
            student_name VARCHAR(80) NOT NULL,
            problem_url VARCHAR(500) NOT NULL,
            code_text TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO submissions (id, public_id, student_name, problem_url, code_text)
        VALUES
            (1, 'dup-public-id', '学生甲', 'http://noi.openjudge.cn/ch0107/01/', 'int main() { return 0; }'),
            (2, 'dup-public-id', '学生乙', 'http://noi.openjudge.cn/ch0107/02/', 'int main() { return 0; }')
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    app = create_app(BootstrapConfig)
    with app.app_context():
        submissions = Submission.query.order_by(Submission.id.asc()).all()
        assert len(submissions) == 2
        assert submissions[0].public_id
        assert submissions[1].public_id
        assert submissions[0].public_id != submissions[1].public_id


def test_legacy_schema_is_repaired_even_when_admin_bootstrap_is_disabled(tmp_path):
    database_path = tmp_path / "legacy-no-admin.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            student_name VARCHAR(80) NOT NULL,
            problem_url VARCHAR(500) NOT NULL,
            code_text TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    app = create_app(BootstrapConfig)
    with app.app_context():
        repaired_submission = Submission(
            student_name="补列后学生",
            problem_url="http://noi.openjudge.cn/ch0107/03/",
            code_text="int main() { return 0; }",
            language="cpp",
            fetch_status="pending",
            diagnosis_status="pending",
        )
        db.session.add(repaired_submission)
        db.session.commit()
        assert repaired_submission.public_id
        assert AdminUser.query.count() == 0


def test_request_path_repairs_legacy_schema_when_startup_repair_was_skipped(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-request.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            student_name VARCHAR(80) NOT NULL,
            problem_url VARCHAR(500) NOT NULL,
            code_text TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    monkeypatch.setattr("src.app.bootstrap.bootstrap_app", lambda app: None)

    app = create_app(BootstrapConfig)
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200

    with app.app_context():
        repaired_submission = Submission(
            student_name="请求后学生",
            problem_url="http://noi.openjudge.cn/ch0107/04/",
            code_text="int main() { return 0; }",
            language="cpp",
            fetch_status="pending",
            diagnosis_status="pending",
        )
        db.session.add(repaired_submission)
        db.session.commit()
        assert repaired_submission.public_id


def test_request_path_repairs_schema_missing_core_submission_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-core-missing.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            client_ip_hash VARCHAR(64)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO submissions (id, client_ip_hash)
        VALUES (1, 'legacy-ip-hash')
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    monkeypatch.setattr("src.app.bootstrap.bootstrap_app", lambda app: None)

    app = create_app(BootstrapConfig)
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200

    with app.app_context():
        assert Submission.query.count() == 1
        repaired_row = Submission.query.first()
        assert repaired_row.public_id
        assert repaired_row.student_name == ""
        assert repaired_row.problem_url == ""
        assert repaired_row.code_text == ""


def test_submit_request_repairs_legacy_schema_and_redirects_to_login_hub(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-submit.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            client_ip_hash VARCHAR(64)
        )
        """
    )
    connection.commit()
    connection.close()

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        SUBMISSION_CODE_MAX_LENGTH = 20000
        RATE_LIMIT_MAX_SUBMISSIONS = 20
        RATE_LIMIT_WINDOW_SECONDS = 300

    monkeypatch.setattr("src.app.bootstrap.bootstrap_app", lambda app: None)

    app = create_app(BootstrapConfig)
    client = app.test_client()
    response = client.post(
        "/submit",
        data={
            "student_name": "旧库学生",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "int main() { return 0; }",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")

    with app.app_context():
        assert Submission.query.count() == 0


def test_submit_post_does_not_attempt_persistence_or_queueing_when_login_is_required(app, client, monkeypatch):
    monkeypatch.setattr(
        "src.app.routes.public._persist_submission",
        lambda submission: (_ for _ in ()).throw(AssertionError("不应再走匿名保存链路")),
    )
    monkeypatch.setattr(
        "src.app.routes.public._sync_problem_snapshot",
        lambda submission: (_ for _ in ()).throw(AssertionError("不应再走匿名后台链路")),
    )

    response = client.post(
        "/submit",
        data={
            "student_name": "重试学生",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "int main() { return 0; }",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")

    with app.app_context():
        assert Submission.query.count() == 0


def test_submit_post_follow_redirects_shows_login_required_message(client):
    
    response = client.post(
        "/submit",
        data={
            "student_name": "显式主键学生",
            "problem_url": "http://noi.openjudge.cn/ch0107/01/",
            "code_text": "int main() { return 0; }",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "请先登录后再使用提交功能".encode() in response.data
