"""submission soft delete

Revision ID: 9de8a1b7c245
Revises: 2c1e5f8a9b34
Create Date: 2026-05-03 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9de8a1b7c245"
down_revision = "2c1e5f8a9b34"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f("ix_submissions_deleted_at"), ["deleted_at"], unique=False)


def downgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_submissions_deleted_at"))
        batch_op.drop_column("deleted_at")
