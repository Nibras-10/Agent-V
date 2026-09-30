"""Add upstream processor references required for safe live actions."""
from alembic import op
import sqlalchemy as sa

revision = "003_action_provider_refs"
down_revision = "002_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("transactions", "subscriptions"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "provider_ref" not in columns:
            op.add_column(table, sa.Column("provider_ref", sa.String(length=255), nullable=True))

    for table in ("transactions", "subscriptions"):
        name = f"ix_{table}_provider_ref"
        indexes = {index["name"]: index for index in sa.inspect(bind).get_indexes(table)}
        existing = indexes.get(name)
        if existing:
            if existing["column_names"] != ["provider_ref"] or not existing["unique"]:
                raise RuntimeError(f"Existing index {name} does not match migration 003; resolve it before retrying.")
        else:
            op.create_index(name, table, ["provider_ref"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_subscriptions_provider_ref", table_name="subscriptions")
    op.drop_index("ix_transactions_provider_ref", table_name="transactions")
    op.drop_column("subscriptions", "provider_ref")
    op.drop_column("transactions", "provider_ref")
