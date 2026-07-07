"""message activity reference id

Adds the nullable ``ref_id`` column to the ``messages`` table. It records the id
of the domain object an activity turn refers to (an exercise id for
``role="exercise"``, a quiz id for ``role="quiz"``) so the history can link back
and fetch the full item for review. The migration is purely additive: the column
is nullable and is not a foreign key, so existing messages stay valid with
``ref_id = NULL`` and remain unaffected. Mirrors the ``Message.ref_id`` field in
``db/models.py``.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``ref_id`` column to ``messages``."""
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ref_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the ``ref_id`` column from ``messages``."""
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_column("ref_id")
