from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver


_checkpointer: Optional[BaseCheckpointSaver] = None


def set_checkpointer(checkpointer: Optional[BaseCheckpointSaver]) -> None:
    global _checkpointer
    _checkpointer = checkpointer


def get_checkpointer() -> Optional[BaseCheckpointSaver]:
    return _checkpointer