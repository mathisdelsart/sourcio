"""quiz tables

Adds the ``quizzes`` and ``quiz_questions`` tables backing the quiz feature, and
extends ``grades`` so a graded answer can link to either an exercise or a single
quiz question. The ``grades.exercise_id`` column becomes nullable: a quiz-answer
grade sets ``quiz_question_id`` instead. This mirrors the SQLAlchemy models in
``db/models.py``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the quiz tables and link grades to quiz questions."""
    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("notion", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quizzes_student_id"), ["student_id"], unique=False)

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("reference_solution", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quiz_questions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quiz_questions_quiz_id"), ["quiz_id"], unique=False)

    # A quiz-answer grade links to a quiz question instead of an exercise, so the
    # exercise link becomes optional and a new optional question link is added.
    with op.batch_alter_table("grades", schema=None) as batch_op:
        batch_op.alter_column("exercise_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("quiz_question_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_grades_quiz_question_id"), ["quiz_question_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_grades_quiz_question_id_quiz_questions",
            "quiz_questions",
            ["quiz_question_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Drop the quiz tables and the grades link, restoring the prior schema."""
    with op.batch_alter_table("grades", schema=None) as batch_op:
        batch_op.drop_constraint("fk_grades_quiz_question_id_quiz_questions", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_grades_quiz_question_id"))
        batch_op.drop_column("quiz_question_id")
        batch_op.alter_column("exercise_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("quiz_questions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quiz_questions_quiz_id"))
    op.drop_table("quiz_questions")

    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quizzes_student_id"))
    op.drop_table("quizzes")
