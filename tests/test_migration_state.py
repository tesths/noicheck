from sqlalchemy import inspect, text

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
