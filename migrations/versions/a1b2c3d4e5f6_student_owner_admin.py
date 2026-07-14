"""student owner admin

Revision ID: a1b2c3d4e5f6
Revises: 6b6f0d3c2a11
Create Date: 2026-07-14 08:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "6b6f0d3c2a11"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_admin_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_student_users_owner_admin_id"), ["owner_admin_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_student_users_owner_admin_id",
            "admin_users",
            ["owner_admin_id"],
            ["id"],
        )

    connection = op.get_bind()
    admin_id = connection.execute(
        sa.text("SELECT id FROM admin_users WHERE username = :username ORDER BY id ASC LIMIT 1"),
        {"username": "admin"},
    ).scalar()
    if admin_id is not None:
        connection.execute(
            sa.text(
                "UPDATE student_users "
                "SET owner_admin_id = :admin_id "
                "WHERE owner_admin_id IS NULL"
            ),
            {"admin_id": admin_id},
        )


def downgrade():
    with op.batch_alter_table("student_users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_student_users_owner_admin_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_student_users_owner_admin_id"))
        batch_op.drop_column("owner_admin_id")
