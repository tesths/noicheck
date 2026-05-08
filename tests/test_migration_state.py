from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from src.app.extensions import db
from src.app.services.migration_state import (
    LEGACY_PORTAL_BRANCH_REVISION,
    LEGACY_SUBMISSION_MODE_BRANCH_REVISION,
    prepare_legacy_alembic_version,
)


def test_prepare_legacy_alembic_version_stamps_known_bootstrap_schema(app):
    with app.app_context():
        stamped = prepare_legacy_alembic_version(db.engine)

        assert stamped == [
            LEGACY_PORTAL_BRANCH_REVISION,
            LEGACY_SUBMISSION_MODE_BRANCH_REVISION,
        ]

        versions = db.session.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        ).scalars().all()
        assert versions == sorted(stamped)


def test_prepare_legacy_alembic_version_skips_empty_database(app):
    with app.app_context():
        db.drop_all()

        stamped = prepare_legacy_alembic_version(db.engine)

        assert stamped == []
        assert "alembic_version" not in inspect(db.engine).get_table_names()


def test_prepare_legacy_alembic_version_rejects_unknown_partial_legacy_schema(app):
    with app.app_context():
        db.session.execute(text("DROP TABLE system_settings"))
        db.session.commit()

        try:
            prepare_legacy_alembic_version(db.engine)
        except RuntimeError as exc:
            assert "无法安全推断 Alembic 基线" in str(exc)
        else:
            raise AssertionError("预期应拒绝不完整的历史 schema")


def test_submission_request_token_migration_skips_existing_column(tmp_path):
    database_path = tmp_path / "migration-existing-request-token.db"
    engine = create_engine(f"sqlite:///{database_path}")
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "3f6d9a7c1b20_submission_request_token.py"
    )
    spec = spec_from_file_location("migration_submission_request_token", migration_path)
    assert spec is not None and spec.loader is not None
    migration_module = module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE submissions ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "request_token VARCHAR(64)"
                ")"
            )
        )

        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration_module.op
        migration_module.op = operations
        try:
            migration_module.upgrade()
        finally:
            migration_module.op = original_op

    indexes = {index["name"] for index in inspect(engine).get_indexes("submissions")}
    assert "ix_submissions_request_token" in indexes


def test_submission_followup_migration_skips_existing_tables(tmp_path):
    database_path = tmp_path / "migration-existing-followups.db"
    engine = create_engine(f"sqlite:///{database_path}")
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "6b6f0d3c2a11_submission_followups.py"
    )
    spec = spec_from_file_location("migration_submission_followups", migration_path)
    assert spec is not None and spec.loader is not None
    migration_module = module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE submissions ("
                "id INTEGER NOT NULL PRIMARY KEY"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE submission_followup_sessions ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "submission_id INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ix_submission_followup_sessions_submission_id "
                "ON submission_followup_sessions (submission_id)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE submission_followup_messages ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "session_id INTEGER NOT NULL, "
                "role VARCHAR(16) NOT NULL, "
                "content TEXT NOT NULL, "
                "context_label VARCHAR(80), "
                "context_text TEXT, "
                "model_name VARCHAR(100), "
                "latency_ms INTEGER, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_submission_followup_messages_session_id "
                "ON submission_followup_messages (session_id)"
            )
        )

        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration_module.op
        migration_module.op = operations
        try:
            migration_module.upgrade()
        finally:
            migration_module.op = original_op

    inspector = inspect(engine)
    assert "submission_followup_sessions" in inspector.get_table_names()
    assert "submission_followup_messages" in inspector.get_table_names()
