"""Provider registry: maps factor IDs to their AI providers with fallback chains.

Priority strategy for free / low-cost operation:
  F1 (Claude)       -> Anthropic -> DeepSeek (fallback) -> Mock
  F2 (Qwen)         -> Qwen DashScope -> DeepSeek (fallback) -> Mock
  F3 (Kimi)         -> Moonshot -> DeepSeek (fallback) -> Mock
  F4 (GPT-4o)       -> OpenAI -> DeepSeek (fallback) -> Mock
  F5 (Gemini)       -> Gemini -> DeepSeek (fallback) -> Mock
  F6 (DeepSeek-R1)  -> DeepSeek -> Qwen (fallback) -> Mock
  F7 (ERNIE)        -> ERNIE/Qianfan -> Qwen (fallback) -> Mock
  F8 (Llama 3.1)    -> Groq -> DeepSeek (fallback) -> Mock
"""

import logging
from typing import Dict, List

from app.providers.base import (
    AIProvider,
    MockProvider,
    OpenAICompatibleProvider,
    AnthropicProvider,
    GeminiProvider,
    ERNIEProvider,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Singleton mock provider for fallback
_mock_provider = MockProvider()


def _build_provider_chain(factor_id: str) -> List[AIProvider]:
    """Build a fallback chain of providers for a given factor."""
    chain: List[AIProvider] = []

    s = settings

    if factor_id == "F1":
        # Claude Opus -> DeepSeek fallback
        if s.anthropic_api_key:
            chain.append(AnthropicProvider(s.anthropic_api_key, "claude-3-5-sonnet-20241022"))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    elif factor_id == "F2":
        # Qwen-Max
        if s.qwen_api_key:
            chain.append(OpenAICompatibleProvider("qwen", "qwen-max",
                                                   s.qwen_api_key, s.qwen_base_url))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    elif factor_id == "F3":
        # Kimi / Moonshot
        if s.kimi_api_key:
            chain.append(OpenAICompatibleProvider("kimi", "moonshot-v1-8k",
                                                   s.kimi_api_key, s.kimi_base_url))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    elif factor_id == "F4":
        # GPT-4o -> DeepSeek fallback
        if s.openai_api_key:
            chain.append(OpenAICompatibleProvider("openai", "gpt-4o",
                                                   s.openai_api_key, "https://api.openai.com/v1"))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    elif factor_id == "F5":
        # Gemini 1.5 Pro
        if s.gemini_api_key:
            chain.append(GeminiProvider(s.gemini_api_key, "gemini-1.5-pro"))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    elif factor_id == "F6":
        # DeepSeek-R1 (reasoner)
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek-reasoner", "deepseek-reasoner",
                                                   s.deepseek_api_key, s.deepseek_base_url))
        if s.qwen_api_key:
            chain.append(OpenAICompatibleProvider("qwen", "qwen-max",
                                                   s.qwen_api_key, s.qwen_base_url))

    elif factor_id == "F7":
        # ERNIE / 文心一言
        if s.ernie_api_key and s.ernie_secret_key:
            chain.append(ERNIEProvider(s.ernie_api_key, s.ernie_secret_key, "ernie-bot-8k"))
        if s.qwen_api_key:
            chain.append(OpenAICompatibleProvider("qwen", "qwen-max",
                                                   s.qwen_api_key, s.qwen_base_url))

    elif factor_id == "F8":
        # Llama 3.1 via Groq
        if s.groq_api_key:
            chain.append(OpenAICompatibleProvider("groq", "llama-3.1-70b-versatile",
                                                   s.groq_api_key, s.groq_base_url))
        if s.deepseek_api_key:
            chain.append(OpenAICompatibleProvider("deepseek", "deepseek-chat",
                                                   s.deepseek_api_key, s.deepseek_base_url))

    # Always add mock as last resort
    chain.append(_mock_provider)

    return chain


# Cache provider chains
_provider_chains: Dict[str, List[AIProvider]] = {}


def get_provider_chain(factor_id: str) -> List[AIProvider]:
    """Get the cached provider chain for a factor."""
    if factor_id not in _provider_chains:
        _provider_chains[factor_id] = _build_provider_chain(factor_id)
    return _provider_chains[factor_id]


def get_primary_provider(factor_id: str) -> AIProvider:
    """Get the primary (first available) provider for a factor."""
    chain = get_provider_chain(factor_id)
    for provider in chain:
        if provider.is_available():
            return provider
    return _mock_provider


async def call_with_fallback(factor_id: str, system_prompt: str, user_prompt: str,
                             temperature: float = 0.3, max_tokens: int = 2000) -> str:
    """
    Call AI completion with automatic fallback.
    Tries each provider in the chain until one succeeds.
    """
    chain = get_provider_chain(factor_id)
    last_error = None

    for provider in chain:
        if not provider.is_available():
            continue
        try:
            result = await provider.chat_completion(
                system_prompt, user_prompt, temperature, max_tokens
            )
            if result:
                return result
        except Exception as e:
            logger.warning(f"Provider {provider.name} failed for {factor_id}: {e}")
            last_error = e
            continue

    logger.error(f"All providers failed for {factor_id}, last error: {last_error}")
    return await _mock_provider.chat_completion(system_prompt, user_prompt, temperature, max_tokens)


def get_provider_status() -> Dict[str, dict]:
    """Get the status of all factor providers for the monitoring dashboard."""
    status = {}
    for factor_id in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]:
        chain = get_provider_chain(factor_id)
        primary = get_primary_provider(factor_id)
        status[factor_id] = {
            "primary_provider": primary.name,
            "model": primary.model,
            "available": primary.is_available(),
            "chain_length": len(chain),
            "chain": [p.name for p in chain],
        }
    return status
