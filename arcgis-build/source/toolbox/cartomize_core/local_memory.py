"""Mémoire locale JSON, sans service distant."""

from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json


class LocalMemory:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        return read_json(self.path) if self.path.exists() else {}

    def save(self, value: dict[str, Any]) -> Path:
        return write_json(self.path, value)
