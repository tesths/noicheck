"""system settings

Revision ID: 8a3d1b2c4f56
Revises: f4c2d8b1e9aa
Create Date: 2026-05-03 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8a3d1b2c4f56"
down_revision = "f4c2d8b1e9aa"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("system_settings")
