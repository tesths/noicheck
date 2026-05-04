"""expand system settings value for prompt storage

Revision ID: b5f7a2c1d9e0
Revises: 9de8a1b7c245
Create Date: 2026-05-04 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b5f7a2c1d9e0"
down_revision = "9de8a1b7c245"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("system_settings", schema=None) as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("system_settings", schema=None) as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=False,
        )
