"""user username (username-only auth)

Switches authentication from email to a unique username (a pseudonym used both as
the login identifier and the display name). Adds the ``users.username`` column
with a unique index and makes ``users.email`` nullable, since no email is
collected any more.

The column is added as nullable so the migration is safe on a database that
already holds rows (they get ``username = NULL``, which the unique index treats
as distinct); the application layer always sets a username on registration. This
mirrors the ``User`` model in ``db/models.py``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``users.username`` (unique) and relax ``users.email`` to nullable."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_users_username"), ["username"], unique=True)
        batch_op.alter_column("email", existing_type=sa.String(length=320), nullable=True)


def downgrade() -> None:
    """Drop ``users.username`` and restore ``users.email`` to NOT NULL."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("email", existing_type=sa.String(length=320), nullable=False)
        batch_op.drop_index(batch_op.f("ix_users_username"))
        batch_op.drop_column("username")
