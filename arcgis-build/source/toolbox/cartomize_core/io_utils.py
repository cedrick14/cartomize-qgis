"""Entrées-sorties bornées et déterministes."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


def write_json(path: str | Path, payload: Any) -> str:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(target)
    return str(target)


def read_json(path: str | Path, *, max_bytes: int = 5_000_000) -> Any:
    source = Path(path).expanduser().resolve()
    if source.stat().st_size > max_bytes:
        raise ValueError(f"Le fichier dépasse la limite de {max_bytes} octets.")
    return json.loads(source.read_text(encoding="utf-8"))


def safe_name(value: object, default: str = "cartomize") -> str:
    text = re.sub(r"[^0-9A-Za-zÀ-ÿ_. -]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._-")
    return text[:120] or default
