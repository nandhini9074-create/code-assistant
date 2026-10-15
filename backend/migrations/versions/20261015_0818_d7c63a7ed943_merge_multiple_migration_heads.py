"""merge multiple migration heads

Revision ID: d7c63a7ed943
Revises: 420732333362, 20261015_1000
Create Date: 2026-10-15 08:18:56.853990+00:00
"""

revision = "d7c63a7ed943"
down_revision = (
    "420732333362",
    "20261015_1000",
    "8ab219d3e512",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass


from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "vulnerability_scanner_catalog",
        sa.Column("command_id", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column(
        "vulnerability_scanner_catalog",
        "command_id",
    )