import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional
from app.observability.redaction import redact_data


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": getattr(record, "request_id", None),
            "run_id": getattr(record, "run_id", None),
            "ticket_id": getattr(record, "ticket_id", None),
            "node": getattr(record, "node", None),
            "duration": getattr(record, "duration", None),
            "status": getattr(record, "status", None),
            "error_code": getattr(record, "error_code", None),
        }
        if hasattr(record, "extra_data") and record.extra_data:
            payload["extra"] = redact_data(record.extra_data)

        # Redact entire log payload for security
        safe_payload = redact_data(payload)
        # Drop None keys to keep logs concise
        filtered_payload = {k: v for k, v in safe_payload.items() if v is not None}
        return json.dumps(filtered_payload)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers = [handler]


logger = logging.getLogger("agent_v")
