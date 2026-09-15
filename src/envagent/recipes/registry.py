"""Loads vetted setup recipes and matches a goal against them by keyword, no LLM call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_RECIPES_DIR = Path(__file__).parent


@dataclass
class IdeChoice:
    message: str
    options: list[str]


@dataclass
class Recipe:
    name: str
    aliases: list[str]
    doc_url: str | dict[str, str]
    """A single doc page (Flutter-style, OS-tab markers within one page), or
    a mapping of os_key -> URL for sites that split OS instructions across
    separate pages (e.g. Docker)."""
    doc_section: str | None = None
    """Optional Markdown heading to narrow a long doc (e.g. a version
    manager's README) down to its install section before grounding."""
    ide_choice: IdeChoice | None = None
    supported_os: list[str] | None = None
    """None = no restriction. Set this when doc_url is a plain string that
    only actually covers some OSes (e.g. nvm/pyenv don't support native
    Windows) — a per-OS doc_url dict doesn't need this, since an absent
    key already expresses "unsupported"."""


def _load_recipe(path: Path) -> Recipe:
    data = yaml.safe_load(path.read_text())
    ide_choice = IdeChoice(**data["ide_choice"]) if data.get("ide_choice") else None
    return Recipe(
        name=data["name"],
        aliases=data.get("aliases") or [data["name"]],
        doc_url=data["doc_url"],
        doc_section=data.get("doc_section"),
        ide_choice=ide_choice,
        supported_os=data.get("supported_os"),
    )


def resolve_doc_url(recipe: Recipe, os_key: str) -> str | None:
    """Pick the right doc URL for this OS. Returns None if the OS isn't
    covered — either a per-OS mapping missing this os_key, or a recipe
    whose supported_os explicitly excludes it."""
    if recipe.supported_os is not None and os_key not in recipe.supported_os:
        return None
    if isinstance(recipe.doc_url, dict):
        return recipe.doc_url.get(os_key)
    return recipe.doc_url


def load_recipes() -> list[Recipe]:
    return [_load_recipe(p) for p in sorted(_RECIPES_DIR.glob("*.yaml"))]


def match_recipe(goal: str) -> Recipe | None:
    goal_lower = goal.lower()
    for recipe in load_recipes():
        if any(alias.lower() in goal_lower for alias in recipe.aliases):
            return recipe
    return None
