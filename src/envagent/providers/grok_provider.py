from __future__ import annotations

import openai

from envagent.providers.base import Provider, ProviderAuthError

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider(Provider):
    """xAI's Grok, accessed via its OpenAI-compatible API."""

    id = "grok"
    display_name = "xAI (Grok)"
    default_model = "grok-4"

    def validate_key(self, api_key: str) -> None:
        client = openai.OpenAI(api_key=api_key, base_url=XAI_BASE_URL)
        try:
            client.models.list()
        except openai.AuthenticationError as exc:
            raise ProviderAuthError(str(exc)) from exc

    def complete(self, api_key: str, system: str, user: str) -> str:
        client = openai.OpenAI(api_key=api_key, base_url=XAI_BASE_URL)
        try:
            response = client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except openai.AuthenticationError as exc:
            raise ProviderAuthError(str(exc)) from exc
        return response.choices[0].message.content or ""
