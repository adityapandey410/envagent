from __future__ import annotations

import openai

from envagent.providers.base import Provider, ProviderAuthError


class OpenAIProvider(Provider):
    id = "openai"
    display_name = "OpenAI"
    default_model = "gpt-5.1"

    def validate_key(self, api_key: str) -> None:
        client = openai.OpenAI(api_key=api_key)
        try:
            client.models.list()
        except openai.AuthenticationError as exc:
            raise ProviderAuthError(str(exc)) from exc

    def complete(self, api_key: str, system: str, user: str) -> str:
        client = openai.OpenAI(api_key=api_key)
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
