"""Add account verification, revocable access tokens, and single-use auth links."""
from alembic import op
import sqlalchemy as sa

revision = "002_auth_security"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "is_verified" not in user_columns:
        op.add_column("users", sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "token_version" not in user_columns:
        op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    inspector = sa.inspect(bind)
    if not inspector.has_table("auth_tokens"):
        op.create_table(
            "auth_tokens",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    else:
        required = {"id", "user_id", "purpose", "token_hash", "expires_at", "consumed_at", "created_at"}
        existing = {column["name"] for column in inspector.get_columns("auth_tokens")}
        missing = sorted(required - existing)
        if missing:
            raise RuntimeError(
                "Existing auth_tokens table is incompatible with migration 002; "
                f"missing columns: {', '.join(missing)}. Resolve the schema before retrying."
            )

    indexes = {index["name"]: index for index in sa.inspect(bind).get_indexes("auth_tokens")}
    expected_indexes = {
        "ix_auth_tokens_user_id": (["user_id"], False),
        "ix_auth_tokens_token_hash": (["token_hash"], True),
        "ix_auth_tokens_purpose_expires": (["purpose", "expires_at"], False),
    }
    for name, (columns, unique) in expected_indexes.items():
        existing = indexes.get(name)
        if existing:
            if existing["column_names"] != columns or bool(existing["unique"]) != unique:
                raise RuntimeError(f"Existing index {name} does not match migration 002; resolve it before retrying.")
            continue
        op.create_index(name, "auth_tokens", columns, unique=unique)


def downgrade() -> None:
    raise RuntimeError(
        "Migration 002 may adopt auth_tokens created before Alembic tracked the schema. "
        "Automatic downgrade is disabled to avoid deleting existing authentication data."
    )
