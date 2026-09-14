"""Non-secret configuration, stored as TOML: chosen provider, model, recipe cache location."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_config_dir

APP_NAME = "envagent"


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Settings:
    provider: str | None = None
    model: str | None = None
    extra: dict = field(default_factory=dict)


def load_settings() -> Settings:
    path = config_file()
    if not path.exists():
        return Settings()
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Settings(
        provider=data.get("provider"),
        model=data.get("model"),
        extra=data.get("extra", {}),
    )


def save_settings(settings: Settings) -> None:
    data = {key: value for key, value in asdict(settings).items() if value is not None}
    with config_file().open("wb") as f:
        tomli_w.dump(data, f)
