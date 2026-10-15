"""Configure generic scanner executor and allow PostgreSQL to control scanner commands.

Revision ID: 20261015_1000
Revises: 20261015_0900
"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_1000"
down_revision = "20261015_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "vulnerability_scanner_catalog" in tables:
        catalog = sa.Table(
            "vulnerability_scanner_catalog",
            sa.MetaData(),
            autoload_with=bind,
        )

        # Make adapter_id nullable
        op.alter_column(
            "vulnerability_scanner_catalog",
            "adapter_id",
            existing_type=sa.String(100),
            nullable=True,
        )

        # Set adapter_id to generic_command_executor
        bind.execute(
            sa.update(catalog)
            .values(adapter_id="generic_command_executor")
        )

        # Ensure npm-audit is configured for generic command execution
        bind.execute(
            sa.update(catalog)
            .where(catalog.c.scanner_id == "npm-audit")
            .values(
                command_id="npm",
                output_format="json",
            )
        )

    if "vulnerability_ecosystem_registry" in tables:
        registry = sa.Table(
            "vulnerability_ecosystem_registry",
            sa.MetaData(),
            autoload_with=bind,
        )

        # Ensure node-npm-sca registry has command_args and timeout
        bind.execute(
            sa.update(registry)
            .where(registry.c.ecosystem_id == "node-npm-sca")
            .values(
                command_args=["audit", "--json"],
                timeout_seconds=30,
            )
        )


def downgrade() -> None:
    pass
