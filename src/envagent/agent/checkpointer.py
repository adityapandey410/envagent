"""SqliteSaver setup for graph checkpointing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from platformdirs import user_data_dir

APP_NAME = "envagent"


def checkpoint_db_path() -> Path:
    data_dir = Path(user_data_dir(APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "checkpoints.sqlite"


def get_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(str(checkpoint_db_path()), check_same_thread=False)
    return SqliteSaver(conn)
