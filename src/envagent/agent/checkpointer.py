"""Local, on-disk checkpointing for graph state — enables pausing on a HITL
interrupt and resuming an interrupted setup later.

Kept local-only (SQLite file under the user's data directory), consistent
with the BYOK/no-backend principle: no external database required.
"""

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
