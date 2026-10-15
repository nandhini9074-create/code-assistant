
"""Restore the missing, already-applied vulnerability registry revision.

The database already contains the registry tables created by this revision.
This placeholder restores Alembic's revision graph; it does not recreate them.
"""

revision = "8ab219d3e512"
down_revision = "9fe690579423"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
