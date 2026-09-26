from datetime import timedelta
import pytest
import jwt
from app.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
from app.schemas.actions import compute_proposal_hash
from app.observability.redaction import redact_data, redact_text


def test_password_hashing():
    pwd = "SuperSecretPassword123!"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_token_claims():
    token = create_access_token(
        user_id="u123",
        email="test@example.com",
        role="reviewer",
        customer_id=None,
    )
    payload = decode_access_token(token)
    assert payload["sub"] == "u123"
    assert payload["role"] == "reviewer"
    assert "approval:decide" in payload["scopes"]
    assert "audit:read" in payload["scopes"]


def test_jwt_expiration():
    token = create_access_token(
        user_id="u123",
        email="test@example.com",
        role="customer",
        expires_delta=timedelta(seconds=-1),  # Expired
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_canonical_proposal_hash():
    payload1 = {"transaction_id": "txn_1", "amount_minor": 5000, "currency": "USD"}
    payload2 = {"currency": "USD", "amount_minor": 5000, "transaction_id": "txn_1"}

    hash1 = compute_proposal_hash("refund", payload1)
    hash2 = compute_proposal_hash("refund", payload2)
    # Canonical ordering produces identical hash
    assert hash1 == hash2
    assert len(hash1) == 64

    # Altering payload alters hash
    payload3 = {"transaction_id": "txn_1", "amount_minor": 5001, "currency": "USD"}
    hash3 = compute_proposal_hash("refund", payload3)
    assert hash1 != hash3


def test_redaction():
    sensitive_dict = {
        "password": "my_secret_password",
        "authorization": "Bearer eyJhbGciOi...",
        "user_email": "test@test.com",
        "nested": {
            "credit_card": "4111-2222-3333-4444",
            "normal_field": "visible",
        },
    }
    redacted = redact_data(sensitive_dict)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["nested"]["credit_card"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == "visible"
