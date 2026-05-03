import sqlite3

from sqlalchemy import inspect

from src.app import create_app
from src.app.extensions import db
from src.app.models import DiagnosisRun, StudentUser, Submission


def test_bootstrap_repairs_student_schema_for_legacy_database(tmp_path):
    database_path = tmp_path / "legacy-student-schema.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            public_id VARCHAR(32) NOT NULL,
            student_name VARCHAR(80) NOT NULL,
            problem_url VARCHAR(500) NOT NULL,
            problem_source VARCHAR(32) NOT NULL,
            problem_title VARCHAR(255),
            problem_path VARCHAR(120),
            language VARCHAR(16) NOT NULL,
            code_text TEXT NOT NULL,
            client_ip_hash VARCHAR(64),
            fetch_status VARCHAR(16) NOT NULL,
            diagnosis_status VARCHAR(16) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE diagnosis_runs (
            id INTEGER PRIMARY KEY,
            submission_id INTEGER NOT NULL,
            model_name VARCHAR(100) NOT NULL,
            prompt_version VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL,
            structured_result_json JSON,
            summary_text TEXT,
            error_message TEXT,
            latency_ms INTEGER,
            created_at DATETIME NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO submissions (
            id, public_id, student_name, problem_url, problem_source, problem_title, problem_path,
            language, code_text, client_ip_hash, fetch_status, diagnosis_status, created_at
        ) VALUES (
            1, 'legacy-student-submission', '旧学生',
            'http://noi.openjudge.cn/ch0107/01/', 'openjudge', '旧题目', 'ch0107/01',
            'cpp', 'int main() { return 0; }', NULL, 'success', 'success', '2026-04-27 08:00:00'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO diagnosis_runs (
            id, submission_id, model_name, prompt_version, status,
            structured_result_json, summary_text, error_message, latency_ms, created_at
        ) VALUES (
            1, 1, 'deepseek-v4-pro', 'v1', 'success', '{}', '旧诊断', NULL, 123, '2026-04-27 08:01:00'
        )
        """
    )
    connection.commit()
    connection.close()

    class LegacyStudentConfig:
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

    app = create_app(LegacyStudentConfig)
    with app.app_context():
        table_names = set(inspect(db.engine).get_table_names())
        assert StudentUser.__tablename__ in table_names

        submission = Submission.query.filter_by(public_id="legacy-student-submission").one()
        diagnosis_run = DiagnosisRun.query.one()

        assert submission.student_user_id is None
        assert submission.student_hint_status == "pending"
        assert diagnosis_run.audience == "teacher"

