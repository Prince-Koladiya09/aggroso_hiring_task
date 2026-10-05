import json
import re
import time
from typing import Any, Dict, Optional
from app.core.config import settings
from app.agent.mock_llm import MockLLMClient
from app.agent.prompts import load_prompt


class LLMUnavailableError(RuntimeError):
    pass


class LLMResult:
    def __init__(self, data: Dict[str, Any], model: str, tokens_in: int = 0, tokens_out: int = 0):
        self.data, self.model, self.tokens_in, self.tokens_out = data, model, tokens_in, tokens_out


class BaseLLMClient:
    model_name = "unknown"
    is_mock = False

    def generate_json(self, system_prompt: str, prompt: str, stage: str,
                      payload: Optional[Dict[str, Any]] = None) -> LLMResult:
        raise NotImplementedError


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            text = text[s:e + 1]
    return json.loads(text)


class AnthropicLLMClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=0)
        self.model_name = model

    def generate_json(self, system_prompt, prompt, stage, payload=None) -> LLMResult:
        if settings.SIMULATE_LLM_OUTAGE:
            raise LLMUnavailableError("Simulated LLM outage (SIMULATE_LLM_OUTAGE=true)")
        resp = self.client.messages.create(
            model=self.model_name, max_tokens=settings.LLM_MAX_TOKENS, system=system_prompt,
            messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        usage = getattr(resp, "usage", None)
        return LLMResult(extract_json(text), self.model_name, getattr(usage, "input_tokens", 0),
                         getattr(usage, "output_tokens", 0))


def get_llm_client() -> BaseLLMClient:
    if settings.FORCE_MOCK_LLM or settings.LLM_PROVIDER.lower() == "mock" or not settings.LLM_API_KEY:
        return MockLLMClient()
    try:
        return AnthropicLLMClient(settings.LLM_API_KEY, settings.LLM_MODEL)
    except Exception:
        return MockLLMClient()
