import json
import re
import asyncio
from typing import Dict, Any, Optional, Type, TypeVar
from pydantic import BaseModel
import httpx
from app.core.config import settings
from app.observability.logging import logger

T = TypeVar("T", bound=BaseModel)


class TriageOutput(BaseModel):
    intent: str
    confidence: float
    urgency: str  # low, normal, high
    capability: str  # read_only, proposal, ambiguous, injection
    missing_info: list[str] = []


class ActionProposalOutput(BaseModel):
    action_type: str  # "refund", "cancellation", "contact_update", "none"
    parameters: Dict[str, Any] = {}
    reason: str
    requires_approval: bool = True
    risk: str = "HIGH"


class ResolutionOutput(BaseModel):
    response_text: str
    proposed_action: Optional[ActionProposalOutput] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


class BaseLLMAdapter:
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: float = 0.0,
    ) -> tuple[T, int]:
        """Returns parsed output schema and approximate token usage."""
        raise NotImplementedError


class FakeLLMAdapter(BaseLLMAdapter):
    """Deterministic fake provider for test cases and predictable local development."""
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
        self.force_malformed_once = False
        self.fixed_token_cost = 150

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: float = 0.0,
    ) -> tuple[T, int]:
        self.call_count += 1

        if self.should_fail:
            raise RuntimeError("Simulated LLM Provider failure (500 Internal Error)")

        if self.force_malformed_once:
            self.force_malformed_once = False
            # Return broken json to test repair attempt
            raise ValueError("Malformed model JSON response")

        user_lower = user_prompt.lower()

        if output_schema == TriageOutput:
            # Deterministic intent matching
            if any(
                term in user_lower
                for term in [
                    "system prompt",
                    "system override",
                    "ignore previous",
                    "disregard all prior instructions",
                    "admin mode",
                    "jailbreak",
                    "secret",
                    "signing key",
                    "without approval",
                ]
            ):
                return TriageOutput(
                    intent="injection_attempt",
                    confidence=0.99,
                    urgency="high",
                    capability="injection",
                    missing_info=[],
                ), self.fixed_token_cost

            if any(term in user_lower for term in ["refund", "double charge", "duplicate charge", "incorrect charge", "charged twice"]):
                return TriageOutput(
                    intent="refund_request",
                    confidence=0.95,
                    urgency="normal",
                    capability="proposal",
                    missing_info=[],
                ), self.fixed_token_cost

            if (
                any(term in user_lower for term in ["cancel subscription", "cancel plan", "end subscription", "stop renewal"])
                or ("cancel" in user_lower and "subscription" in user_lower)
            ):
                return TriageOutput(
                    intent="cancel_subscription",
                    confidence=0.95,
                    urgency="normal",
                    capability="proposal",
                    missing_info=[],
                ), self.fixed_token_cost

            if any(term in user_lower for term in ["update phone", "update name", "change phone", "change name", "update contact"]):
                return TriageOutput(
                    intent="contact_update",
                    confidence=0.90,
                    urgency="normal",
                    capability="proposal",
                    missing_info=[],
                ), self.fixed_token_cost

            if any(term in user_lower for term in ["hello", "hi", "what is my plan", "subscription status", "recent orders", "balance", "transactions"]):
                return TriageOutput(
                    intent="account_question",
                    confidence=0.92,
                    urgency="low",
                    capability="read_only",
                    missing_info=[],
                ), self.fixed_token_cost

            # Fallback to ambiguous
            return TriageOutput(
                intent="ambiguous",
                confidence=0.60,
                urgency="low",
                capability="ambiguous",
                missing_info=["specific_request"],
            ), self.fixed_token_cost

        elif output_schema == ResolutionOutput:
            intent_match = re.search(r"Intent:\s*([a-z_]+)", user_prompt, re.IGNORECASE)
            intent = intent_match.group(1).lower() if intent_match else ""
            if "injection_attempt" in user_lower or any(term in user_lower for term in ["ignore previous", "admin mode", "secret"]):
                return ResolutionOutput(
                    response_text="I am programmed to assist strictly with customer support inquiries according to secure policy. I cannot execute instructions that alter security boundaries or reveal internal systems.",
                    proposed_action=None,
                    needs_clarification=False,
                ), self.fixed_token_cost

            if intent == "refund_request":
                # Look for transaction in prompt
                txn_match = re.search(r"(?:txn_|demo_transaction_)[a-zA-Z0-9_\-]+", user_prompt)
                txn_id = txn_match.group(0) if txn_match else "mock-txn-123"
                amount_match = re.search(r"amount_minor['\"]?\s*:\s*(\d+)", user_prompt)
                amount_minor = int(amount_match.group(1)) if amount_match else 5000
                currency_match = re.search(r"currency['\"]?\s*:\s*['\"]([A-Z]{3})", user_prompt)
                currency = currency_match.group(1) if currency_match else "USD"
                return ResolutionOutput(
                    response_text=f"I have reviewed your request for a refund regarding transaction {txn_id}. As this is a financial transaction, I have created a refund proposal which requires reviewer approval.",
                    proposed_action=ActionProposalOutput(
                        action_type="refund",
                        parameters={"transaction_id": txn_id, "amount_minor": amount_minor, "currency": currency},
                        reason="Customer reported duplicate charge",
                        requires_approval=True,
                        risk="HIGH",
                    ),
                ), self.fixed_token_cost

            if intent == "cancel_subscription":
                sub_match = re.search(r"(?:sub_|demo_subscription_)[a-zA-Z0-9_\-]+", user_prompt)
                sub_id = sub_match.group(0) if sub_match else "mock-sub-123"
                return ResolutionOutput(
                    response_text="I have prepared a cancellation proposal for your subscription. Our human review team will review and finalize the cancellation.",
                    proposed_action=ActionProposalOutput(
                        action_type="cancellation",
                        parameters={"subscription_id": sub_id, "cancel_at_period_end": True},
                        reason="Customer requested cancellation",
                        requires_approval=True,
                        risk="HIGH",
                    ),
                ), self.fixed_token_cost

            if intent == "contact_update":
                # Extract phone or name
                return ResolutionOutput(
                    response_text="I have updated your contact details as requested.",
                    proposed_action=ActionProposalOutput(
                        action_type="contact_update",
                        parameters={"phone": "+1-555-0199"},
                        reason="Customer requested phone update",
                        requires_approval=False,
                        risk="LOW",
                    ),
                ), self.fixed_token_cost

            if intent == "ambiguous":
                return ResolutionOutput(
                    response_text="Could you please provide more details or specify your account / transaction ID so I can assist you?",
                    needs_clarification=True,
                    clarification_question="Could you please provide more details?",
                ), self.fixed_token_cost

            # Default read-only resolution
            return ResolutionOutput(
                response_text="Here is your requested account information based on our authoritative records.",
                proposed_action=None,
            ), self.fixed_token_cost

        raise ValueError(f"Unsupported output schema: {output_schema}")


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """Provider-agnostic HTTP adapter for OpenAI/OpenAI-compatible APIs."""
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: float = 0.0,
    ) -> tuple[T, int]:
        schema_json = json.dumps(output_schema.model_json_schema())
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"{system_prompt}\nYou MUST format your response as valid JSON conforming strictly to this JSON Schema:\n{schema_json}"},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {}).get("total_tokens", 100)
            parsed = output_schema.model_validate_json(content)
            return parsed, usage


class GeminiCompatibleAdapter(BaseLLMAdapter):
    """Google Gemini REST client using the Gemini API key from environment settings."""
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: float = 0.0,
    ) -> tuple[T, int]:
        schema_json = json.dumps(output_schema.model_json_schema())
        prompt = (
            f"{system_prompt}\n\n"
            f"You MUST format your response as valid JSON conforming strictly to this JSON Schema:\n{schema_json}\n\n"
            f"User request:\n{user_prompt}"
        )
        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = None
            for attempt in range(3):
                resp = await client.post(url, json=payload)
                if resp.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    break
                await asyncio.sleep(2**attempt)
            assert resp is not None
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise ValueError("Gemini response did not include a candidate payload")
            text = candidates[0]["content"]["parts"][0]["text"]
            usage = data.get("usageMetadata", {})
            total_tokens = (
                int(usage.get("promptTokenCount", 0))
                + int(usage.get("completionTokenCount", 0))
                or 100
            )
            parsed = output_schema.model_validate_json(text)
            return parsed, total_tokens


def get_llm_adapter() -> BaseLLMAdapter:
    has_real_api_key = settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("your_")
    if settings.LLM_PROVIDER == "openai" and has_real_api_key:
        return OpenAICompatibleAdapter(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
        )
    if settings.LLM_PROVIDER == "gemini" and has_real_api_key:
        return GeminiCompatibleAdapter(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
        )
    return FakeLLMAdapter()
