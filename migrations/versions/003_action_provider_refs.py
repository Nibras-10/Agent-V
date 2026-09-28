"""Add upstream processor references required for safe live actions."""
from alembic import op
import sqlalchemy as sa

revision = "003_action_provider_refs"
down_revision = "002_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("provider_ref", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_ref", sa.String(length=255), nullable=True))
    op.create_index("ix_transactions_provider_ref", "transactions", ["provider_ref"], unique=True)
    op.create_index("ix_subscriptions_provider_ref", "subscriptions", ["provider_ref"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_subscriptions_provider_ref", table_name="subscriptions")
    op.drop_index("ix_transactions_provider_ref", table_name="transactions")
    op.drop_column("subscriptions", "provider_ref")
    op.drop_column("transactions", "provider_ref")
