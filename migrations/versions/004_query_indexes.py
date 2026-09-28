"""Add query indexes declared by the application models."""
from alembic import op

revision = "004_query_indexes"
down_revision = "003_action_provider_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_proposal_status_risk", "action_proposals", ["status", "risk_level"], unique=False)
    op.create_index("ix_audit_ticket_created", "audit_events", ["ticket_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_ticket_created", table_name="audit_events")
    op.drop_index("ix_proposal_status_risk", table_name="action_proposals")
