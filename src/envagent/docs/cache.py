"""Local cache for fetched documentation pages — avoids refetching the
same recipe doc on every `setup` run."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from platformdirs import user_cache_dir

APP_NAME = "envagent"
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days — docs don't change hourly


def cache_dir() -> Path:
    path = Path(user_cache_dir(APP_NAME)) / "docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def get(url: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str | None:
    """Cached content for url if present and still fresh, else None."""
    path = cache_dir() / f"{_cache_key(url)}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if time.time() - data["fetched_at"] > ttl_seconds:
        return None
    return data["content"]


def put(url: str, content: str) -> None:
    path = cache_dir() / f"{_cache_key(url)}.json"
    path.write_text(json.dumps({"url": url, "fetched_at": time.time(), "content": content}))
