"""Provider abstraction: one interface, one implementation per LLM vendor."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderAuthError(Exception):
    """Raised when an API key fails validation against the provider."""


class Provider(ABC):
    id: str
    display_name: str
    default_model: str

    @abstractmethod
    def validate_key(self, api_key: str) -> None:
        """Cheap, side-effect-free call; raises ProviderAuthError on failure."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, api_key: str, system: str, user: str) -> str:
        """Single-turn text completion; raises ProviderAuthError on an auth failure."""
        raise NotImplementedError
