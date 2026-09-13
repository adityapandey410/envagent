from __future__ import annotations

from envagent.providers.anthropic_provider import AnthropicProvider
from envagent.providers.base import Provider
from envagent.providers.gemini_provider import GeminiProvider
from envagent.providers.grok_provider import GrokProvider
from envagent.providers.openai_provider import OpenAIProvider

PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        AnthropicProvider(),
        OpenAIProvider(),
        GeminiProvider(),
        GrokProvider(),
    )
}


def get_provider(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id]
    except KeyError:
        raise ValueError(f"Unknown provider: {provider_id!r}") from None
