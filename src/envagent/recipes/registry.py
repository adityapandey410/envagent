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
    doc_url: str
    ide_choice: IdeChoice | None = None


def _load_recipe(path: Path) -> Recipe:
    data = yaml.safe_load(path.read_text())
    ide_choice = IdeChoice(**data["ide_choice"]) if data.get("ide_choice") else None
    return Recipe(
        name=data["name"],
        aliases=data.get("aliases") or [data["name"]],
        doc_url=data["doc_url"],
        ide_choice=ide_choice,
    )


def load_recipes() -> list[Recipe]:
    return [_load_recipe(p) for p in sorted(_RECIPES_DIR.glob("*.yaml"))]


def match_recipe(goal: str) -> Recipe | None:
    goal_lower = goal.lower()
    for recipe in load_recipes():
        if any(alias.lower() in goal_lower for alias in recipe.aliases):
            return recipe
    return None
