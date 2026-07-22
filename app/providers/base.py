"""Unified AI Provider interface.

All AI model providers implement the same `chat_completion` method,
allowing the system to swap models freely with graceful fallback.
"""

from abc import ABC, abstractmethod
from typing import Optional
import json
import logging
import random

from app.config import settings

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    """Abstract base class for all AI model providers."""

    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model
        self._available: Optional[bool] = None

    @abstractmethod
    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        """Send a chat completion request and return the text response."""
        ...

    def is_available(self) -> bool:
        """Check if this provider has the necessary API key configured."""
        return self._available is not False

    def _mark_unavailable(self):
        self._available = False
        logger.warning(f"Provider {self.name} ({self.model}) marked unavailable")


class MockProvider(AIProvider):
    """Fallback mock provider that returns plausible responses for development."""

    def __init__(self):
        super().__init__("mock", "mock-model")
        self._available = True

    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        logger.info("Using MockProvider for completion")

        # Try to return a context-appropriate mock response
        if "FactorVote" in system_prompt or "FactorVote" in user_prompt:
            votes = ["主胜", "平局", "客胜"]
            return json.dumps({
                "factor_id": "FX",
                "factor_name": "MockFactor",
                "vote": random.choice(votes),
                "confidence": round(random.uniform(0.45, 0.75), 2),
                "reasoning": "[Mock] This is a simulated response for development. "
                             "Configure real API keys to enable actual predictions.",
                "derived_metrics": {
                    "predicted_scores": ["1-1", "2-1"],
                    "predicted_goals": 2,
                    "predicted_half_full": ["平平", "平胜"]
                }
            }, ensure_ascii=False)

        if "VerifiedBriefing" in system_prompt or "VerifiedBriefing" in user_prompt:
            return json.dumps({
                "match_id": "mock",
                "stage": "phase2",
                "data_confidence": "low",
                "content": {
                    "injuries": [],
                    "form": {
                        "home": {"last_3": ["1-0", "1-1", "0-0"], "venue": "home", "confidence": "low"},
                        "away": {"last_3": ["1-0", "0-1", "2-1"], "venue": "away", "confidence": "low"},
                    },
                    "home_away_stats": {},
                    "h2h": [],
                    "motivation": {},
                    "schedule": {}
                },
                "odds_anchor": {"snapshot_time": "2026-01-01T00:00:00+08:00", "h": 2.0, "d": 3.2, "a": 3.5}
            }, ensure_ascii=False)

        return "[Mock] Configure API keys to enable real AI responses."


class OpenAICompatibleProvider(AIProvider):
    """
    Provider for OpenAI-compatible APIs.
    Works with: OpenAI, DeepSeek, Kimi (Moonshot), Qwen (DashScope), Groq.
    """

    def __init__(self, name: str, model: str, api_key: str, base_url: str):
        super().__init__(name, model)
        self.api_key = api_key
        self.base_url = base_url
        self._available = bool(api_key)
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        if not self._available:
            raise RuntimeError(f"Provider {self.name} not available (no API key)")

        client = await self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"{self.name} API call failed: {e}")
            self._mark_unavailable()
            raise


class AnthropicProvider(AIProvider):
    """Provider for Claude / Anthropic models."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        super().__init__("anthropic", model)
        self.api_key = api_key
        self._available = bool(api_key)
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        if not self._available:
            raise RuntimeError("Anthropic not available (no API key)")

        client = await self._get_client()
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            self._mark_unavailable()
            raise


class GeminiProvider(AIProvider):
    """Provider for Google Gemini models."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        super().__init__("gemini", model)
        self.api_key = api_key
        self._available = bool(api_key)

    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        if not self._available:
            raise RuntimeError("Gemini not available (no API key)")

        import google.generativeai as genai
        genai.configure(api_key=self.api_key)

        try:
            model = genai.GenerativeModel(
                self.model,
                system_instruction=system_prompt,
            )
            response = await model.generate_content_async(
                user_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            self._mark_unavailable()
            raise


class ERNIEProvider(AIProvider):
    """Provider for Baidu ERNIE (文心一言) via Qianfan API."""

    def __init__(self, api_key: str, secret_key: str, model: str = "ernie-bot-8k"):
        super().__init__("ernie", model)
        self.api_key = api_key
        self.secret_key = secret_key
        self._available = bool(api_key and secret_key)
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> str:
        import httpx
        if self._access_token:
            return self._access_token

        url = (f"https://aip.baidubce.com/oauth/2.0/token?"
               f"grant_type=client_credentials&client_id={self.api_key}"
               f"&client_secret={self.secret_key}")
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            return self._access_token

    async def chat_completion(self, system_prompt: str, user_prompt: str,
                              temperature: float = 0.3, max_tokens: int = 2000) -> str:
        if not self._available:
            raise RuntimeError("ERNIE not available (no API key)")

        import httpx
        token = await self._get_access_token()

        # Map model name to Qianfan endpoint
        endpoint_map = {
            "ernie-bot": "completions",
            "ernie-bot-8k": "ernie_bot_8k",
            "ernie-4.0-8k": "ernie-4.0-8k",
        }
        ep = endpoint_map.get(self.model, "ernie_bot_8k")
        url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{ep}?access_token={token}"

        payload = {
            "messages": [
                {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
            ],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("result", "")
        except Exception as e:
            logger.error(f"ERNIE API call failed: {e}")
            self._mark_unavailable()
            raise
