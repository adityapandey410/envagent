from __future__ import annotations

from google import genai
from google.genai import errors

from envagent.providers.base import Provider, ProviderAuthError


class GeminiProvider(Provider):
    id = "gemini"
    display_name = "Google (Gemini)"
    default_model = "gemini-3-pro"

    def validate_key(self, api_key: str) -> None:
        client = genai.Client(api_key=api_key)
        try:
            next(iter(client.models.list(config={"page_size": 1})))
        except errors.ClientError as exc:
            raise ProviderAuthError(str(exc)) from exc

    def complete(self, api_key: str, system: str, user: str) -> str:
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=self.default_model,
                contents=user,
                config={"system_instruction": system},
            )
        except errors.ClientError as exc:
            raise ProviderAuthError(str(exc)) from exc
        return response.text or ""
