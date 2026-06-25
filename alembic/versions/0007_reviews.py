"""spaced-repetition reviews

Adds the ``reviews`` table backing per-notion spaced-repetition schedules. One
row exists per ``(student, notion)`` pair (a unique constraint), holding the SM-2
state (``ease``, ``interval_days``, ``repetitions``), the next ``due_at`` and the
optional ``last_reviewed`` timestamp. The migration is purely additive: it only
creates a new table and touches no existing one. Mirrors the ``Review`` model in
``db/models.py``.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``reviews`` table and its student index / uniqueness constraint."""
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("notion", sa.Text(), nullable=False),
        sa.Column("ease", sa.Float(), server_default=sa.text("2.5"), nullable=False),
        sa.Column("interval_days", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("repetitions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_reviewed", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "notion", name="uq_reviews_student_notion"),
    )
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reviews_student_id"), ["student_id"], unique=False)


def downgrade() -> None:
    """Drop the ``reviews`` table and its index."""
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reviews_student_id"))
    op.drop_table("reviews")
