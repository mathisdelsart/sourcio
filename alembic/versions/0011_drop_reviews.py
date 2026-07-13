"""drop the spaced-repetition reviews table

The SM-2 spaced-repetition feature is removed: the scheduler, its endpoints and
its model are gone, so the ``reviews`` table has no writer and no reader left.

``0007_reviews.py`` is deliberately left in place. Migrations are an append-only
ledger -- deleting 0007 would orphan 0008, whose ``down_revision`` points at it,
and would rewrite history that other databases have already applied. The table is
dropped forward instead.

``downgrade`` recreates the table exactly as 0007 built it, so the chain stays
reversible even though the application code that used it is gone.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the ``reviews`` table.

    Dropping the table takes its index with it on both backends, so the index is
    not dropped separately -- 0007 created it inside a ``batch_alter_table`` (a
    SQLite requirement), and naming it again here would only risk a mismatch.
    """
    op.drop_table("reviews")


def downgrade() -> None:
    """Recreate ``reviews`` as 0007 defined it."""
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
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_reviewed", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "notion", name="uq_reviews_student_notion"),
    )
    op.create_index("ix_reviews_student_id", "reviews", ["student_id"], unique=False)
