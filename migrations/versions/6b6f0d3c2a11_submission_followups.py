"""submission followup chat

Revision ID: 6b6f0d3c2a11
Revises: 3f6d9a7c1b20
Create Date: 2026-05-08 09:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b6f0d3c2a11"
down_revision = "3f6d9a7c1b20"
branch_labels = None
depends_on = None


def upgrade():
    table_names = _table_names()
    if "submission_followup_sessions" not in table_names:
        op.create_table(
            "submission_followup_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("submission_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_submission_followup_sessions_submission_id" not in _index_names(
        "submission_followup_sessions"
    ):
        with op.batch_alter_table("submission_followup_sessions", schema=None) as batch_op:
            batch_op.create_index(
                "ix_submission_followup_sessions_submission_id",
                ["submission_id"],
                unique=True,
            )

    table_names = _table_names()
    if "submission_followup_messages" not in table_names:
        op.create_table(
            "submission_followup_messages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("context_label", sa.String(length=80), nullable=True),
            sa.Column("context_text", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=100), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["submission_followup_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_submission_followup_messages_session_id" not in _index_names(
        "submission_followup_messages"
    ):
        with op.batch_alter_table("submission_followup_messages", schema=None) as batch_op:
            batch_op.create_index(
                "ix_submission_followup_messages_session_id",
                ["session_id"],
                unique=False,
            )


def downgrade():
    table_names = _table_names()
    if "submission_followup_messages" in table_names:
        if "ix_submission_followup_messages_session_id" in _index_names(
            "submission_followup_messages"
        ):
            with op.batch_alter_table("submission_followup_messages", schema=None) as batch_op:
                batch_op.drop_index("ix_submission_followup_messages_session_id")
        op.drop_table("submission_followup_messages")

    table_names = _table_names()
    if "submission_followup_sessions" in table_names:
        if "ix_submission_followup_sessions_submission_id" in _index_names(
            "submission_followup_sessions"
        ):
            with op.batch_alter_table("submission_followup_sessions", schema=None) as batch_op:
                batch_op.drop_index("ix_submission_followup_sessions_submission_id")
        op.drop_table("submission_followup_sessions")


def _table_names():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name):
    inspector = sa.inspect(op.get_bind())
    names = {index["name"] for index in inspector.get_indexes(table_name)}
    names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    )
    return names
