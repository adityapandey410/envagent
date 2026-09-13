from __future__ import annotations

import anthropic

from envagent.providers.base import Provider, ProviderAuthError


class AnthropicProvider(Provider):
    id = "anthropic"
    display_name = "Anthropic (Claude)"
    default_model = "claude-sonnet-5"

    def validate_key(self, api_key: str) -> None:
        client = anthropic.Anthropic(api_key=api_key)
        try:
            client.models.list(limit=1)
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError(str(exc)) from exc

    def complete(self, api_key: str, system: str, user: str) -> str:
        client = anthropic.Anthropic(api_key=api_key)
        try:
            response = client.messages.create(
                model=self.default_model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError(str(exc)) from exc
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
