"""Catalogue communautaire et catalogue hors ligne."""

import json
from pathlib import Path


def load_offline_catalog(path: str | Path) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(value.get("templates", value if isinstance(value, list) else []))
