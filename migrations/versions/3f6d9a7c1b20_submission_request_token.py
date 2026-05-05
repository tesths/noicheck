"""submission request token

Revision ID: 3f6d9a7c1b20
Revises: c8f4a1d7e2b3
Create Date: 2026-05-05 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3f6d9a7c1b20"
down_revision = "c8f4a1d7e2b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("request_token", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_submissions_request_token"), ["request_token"], unique=True)


def downgrade():
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_submissions_request_token"))
        batch_op.drop_column("request_token")
