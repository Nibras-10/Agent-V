import re
from typing import Any, Dict, List, Union

REDACTED_STRING = "[REDACTED]"

SENSITIVE_KEYS = {
    "authorization",
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "jwt_signing_key",
    "llm_api_key",
    "api_key",
    "cvv",
    "pan",
    "card_number",
    "credit_card",
}

# Regex to detect potential credit card numbers (13-19 digits with optional hyphens/spaces)
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
# Email regex for redaction in public logs if needed
BEARER_TOKEN_REGEX = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


def redact_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = BEARER_TOKEN_REGEX.sub("Bearer [REDACTED]", text)
    text = CREDIT_CARD_REGEX.sub("[CARD REDACTED]", text)
    return text


def redact_data(data: Any) -> Any:
    """Recursively redact sensitive keys and pattern matches in dicts, lists, and primitives."""
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = REDACTED_STRING
            else:
                redacted[key] = redact_data(value)
        return redacted
    elif isinstance(data, list):
        return [redact_data(item) for item in data]
    elif isinstance(data, str):
        return redact_text(data)
    return data
