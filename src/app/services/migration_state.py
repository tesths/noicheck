from collections.abc import Sequence

from sqlalchemy import Engine, inspect, text

LEGACY_PORTAL_BRANCH_REVISION = "9de8a1b7c245"
LEGACY_SUBMISSION_MODE_BRANCH_REVISION = "7c4f9f0d5e21"

_CORE_TABLES = frozenset({"admin_users", "submissions", "diagnosis_runs", "problem_snapshots"})
_LATEST_LEGACY_TABLES = frozenset({"student_users", "system_settings"})
_LATEST_LEGACY_SUBMISSION_COLUMNS = frozenset(
    {"student_user_id", "submission_mode", "student_hint_status", "deleted_at"}
)
_LATEST_LEGACY_STUDENT_COLUMNS = frozenset({"real_name"})


def prepare_legacy_alembic_version(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "alembic_version" in table_names:
        return []
    if not table_names:
        return []
    if not _CORE_TABLES.issubset(table_names):
        return []

    revisions = _detect_known_legacy_revisions(inspector, table_names)
    if not revisions:
        raise RuntimeError("检测到历史业务表，但无法安全推断 Alembic 基线，请人工处理。")

    _write_alembic_version_rows(engine, revisions)
    return revisions


def _detect_known_legacy_revisions(inspector, table_names: set[str]) -> list[str]:
    if not _LATEST_LEGACY_TABLES.issubset(table_names):
        return []

    submission_columns = _column_names(inspector, "submissions")
    student_columns = _column_names(inspector, "student_users")
    if not _LATEST_LEGACY_SUBMISSION_COLUMNS.issubset(submission_columns):
        return []
    if not _LATEST_LEGACY_STUDENT_COLUMNS.issubset(student_columns):
        return []

    return [
        LEGACY_PORTAL_BRANCH_REVISION,
        LEGACY_SUBMISSION_MODE_BRANCH_REVISION,
    ]


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _write_alembic_version_rows(engine: Engine, revisions: Sequence[str]) -> None:
    unique_revisions = list(dict.fromkeys(revisions))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(text("DELETE FROM alembic_version"))
        for revision in unique_revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
