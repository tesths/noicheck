"""add submission mode

Revision ID: 7c4f9f0d5e21
Revises: f4c2d8b1e9aa
Create Date: 2026-05-03 12:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c4f9f0d5e21"
down_revision = "f4c2d8b1e9aa"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("submission_mode", sa.String(length=32), nullable=False, server_default="teacher_review")
        )


def downgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_column("submission_mode")
