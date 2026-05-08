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
    op.create_table(
        "submission_followup_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("submission_followup_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_submission_followup_sessions_submission_id"),
            ["submission_id"],
            unique=True,
        )

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
    with op.batch_alter_table("submission_followup_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_submission_followup_messages_session_id"),
            ["session_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("submission_followup_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_submission_followup_messages_session_id"))

    op.drop_table("submission_followup_messages")

    with op.batch_alter_table("submission_followup_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_submission_followup_sessions_submission_id"))

    op.drop_table("submission_followup_sessions")
