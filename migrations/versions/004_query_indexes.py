"""Add query indexes declared by the application models."""
from alembic import op
import sqlalchemy as sa

revision = "004_query_indexes"
down_revision = "003_action_provider_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    expected = (
        ("ix_proposal_status_risk", "action_proposals", ["status", "risk_level"]),
        ("ix_audit_ticket_created", "audit_events", ["ticket_id", "created_at"]),
    )
    for name, table, columns in expected:
        indexes = {index["name"]: index for index in sa.inspect(bind).get_indexes(table)}
        existing = indexes.get(name)
        if existing:
            if existing["column_names"] != columns or existing["unique"]:
                raise RuntimeError(f"Existing index {name} does not match migration 004; resolve it before retrying.")
        else:
            op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_ticket_created", table_name="audit_events")
    op.drop_index("ix_proposal_status_risk", table_name="action_proposals")
