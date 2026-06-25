"""link students to users (data ownership)

Adds a nullable ``user_id`` foreign key on ``students`` so a student identity
can be owned by a registered ``users`` account. The column is nullable and
indexed: existing anonymous students keep ``user_id = NULL`` and are unaffected,
so the migration is additive and non-breaking. Mirrors the ``Student.user_id``
relationship in ``db/models.py``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``students.user_id`` FK and its index."""
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_students_user_id"), ["user_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_students_user_id_users"),
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop the ``students.user_id`` FK, index and column."""
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_students_user_id_users"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_students_user_id"))
        batch_op.drop_column("user_id")
