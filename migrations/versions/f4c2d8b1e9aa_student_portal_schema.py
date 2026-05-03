"""student portal schema

Revision ID: f4c2d8b1e9aa
Revises: d7b9e6c904e4
Create Date: 2026-05-03 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f4c2d8b1e9aa"
down_revision = "d7b9e6c904e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_student_users_nickname"), ["nickname"], unique=True)

    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("student_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("student_hint_status", sa.String(length=16), nullable=False, server_default="pending"))
        batch_op.create_index(batch_op.f("ix_submissions_student_user_id"), ["student_user_id"], unique=False)
        batch_op.create_foreign_key("fk_submissions_student_user_id", "student_users", ["student_user_id"], ["id"])

    with op.batch_alter_table("diagnosis_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("audience", sa.String(length=16), nullable=False, server_default="teacher"))


def downgrade():
    with op.batch_alter_table("diagnosis_runs", schema=None) as batch_op:
        batch_op.drop_column("audience")

    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_submissions_student_user_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_submissions_student_user_id"))
        batch_op.drop_column("student_hint_status")
        batch_op.drop_column("student_user_id")

    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_student_users_nickname"))

    op.drop_table("student_users")
