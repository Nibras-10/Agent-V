from typing import Any, Dict
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.integrations.mock_services import MockPaymentGateway, MockSubscriptionGateway


class HttpActionGateway:
    """Provider adapter contract for live financial actions.

    The upstream system must deduplicate requests by the supplied Idempotency-Key.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def _post(self, path: str, payload: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
            response = await client.post(f"{self.base_url}/{path.lstrip('/')}", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Action provider returned an invalid response")
            return data

    async def execute_refund(
        self, transaction_id: str, amount_minor: int, currency: str, idempotency_key: str,
    ) -> Dict[str, Any]:
        result = await self._post(
            "/refunds",
            {"transaction_ref": transaction_id, "amount_minor": amount_minor, "currency": currency},
            idempotency_key,
        )
        if result.get("status") not in {"succeeded", "refunded"}:
            raise ValueError("Action provider did not confirm a completed refund")
        return result

    async def cancel_subscription(
        self, subscription_id: str, cancel_at_period_end: bool, idempotency_key: str,
    ) -> Dict[str, Any]:
        ref = quote(subscription_id, safe="")
        result = await self._post(
            f"/subscriptions/{ref}/cancel",
            {"cancel_at_period_end": cancel_at_period_end},
            idempotency_key,
        )
        accepted = {"canceled", "cancelled", "scheduled"} if cancel_at_period_end else {"canceled", "cancelled"}
        if result.get("status") not in accepted:
            raise ValueError("Action provider did not confirm the requested cancellation")
        return result


if settings.is_production:
    payment_gateway = HttpActionGateway(settings.ACTION_GATEWAY_URL, settings.ACTION_GATEWAY_API_KEY)
    subscription_gateway = payment_gateway
else:
    payment_gateway = MockPaymentGateway()
    subscription_gateway = MockSubscriptionGateway()
