"""Provider abstraction: one interface, one implementation per LLM vendor.

Kept intentionally thin (no chains/frameworks) so each provider's SDK is
called directly and behavior stays auditable.
"""

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
        """Make a cheap, side-effect-free call to confirm the key works.

        Raises ProviderAuthError on failure. Returns None on success.
        """
        raise NotImplementedError

    @abstractmethod
    def complete(self, api_key: str, system: str, user: str) -> str:
        """Single-turn text completion. Raises ProviderAuthError on an
        auth failure so callers can trigger a re-auth flow uniformly.
        """
        raise NotImplementedError
