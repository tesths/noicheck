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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("submissions")}
    index_names = {index["name"] for index in inspector.get_indexes("submissions")}
    index_names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints("submissions")
        if constraint.get("name")
    )

    needs_column = "request_token" not in column_names
    needs_index = "ix_submissions_request_token" not in index_names
    if not needs_column and not needs_index:
        return

    with op.batch_alter_table("submissions", schema=None) as batch_op:
        if needs_column:
            batch_op.add_column(sa.Column("request_token", sa.String(length=64), nullable=True))
        if needs_index:
            batch_op.create_index("ix_submissions_request_token", ["request_token"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("submissions")}
    index_names = {index["name"] for index in inspector.get_indexes("submissions")}
    index_names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints("submissions")
        if constraint.get("name")
    )

    has_column = "request_token" in column_names
    has_index = "ix_submissions_request_token" in index_names
    if not has_column and not has_index:
        return

    with op.batch_alter_table("submissions", schema=None) as batch_op:
        if has_index:
            batch_op.drop_index("ix_submissions_request_token")
        if has_column:
            batch_op.drop_column("request_token")
