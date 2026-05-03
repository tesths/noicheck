"""student real name

Revision ID: 2c1e5f8a9b34
Revises: 8a3d1b2c4f56
Create Date: 2026-05-03 21:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2c1e5f8a9b34"
down_revision = "8a3d1b2c4f56"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("real_name", sa.String(length=80), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.drop_column("real_name")
