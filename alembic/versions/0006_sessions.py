"""conversation sessions (threads)

Adds the ``sessions`` table backing named conversation threads for a student,
and a nullable ``messages.session_id`` foreign key so a message can be attached
to a thread. The column is nullable and indexed: existing messages keep
``session_id = NULL`` and remain valid and unthreaded, so the migration is
additive and non-breaking. Mirrors the ``Session`` model and the
``Message.session_id`` link in ``db/models.py``.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``sessions`` table and add the nullable ``messages.session_id`` FK."""
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_student_id"), ["student_id"], unique=False)

    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_messages_session_id"), ["session_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_messages_session_id_sessions"),
            "sessions",
            ["session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop the ``messages.session_id`` FK and the ``sessions`` table."""
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_messages_session_id_sessions"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_messages_session_id"))
        batch_op.drop_column("session_id")

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_student_id"))
    op.drop_table("sessions")
