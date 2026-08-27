"""Mémoire locale JSON, sans service distant ni donnée SIG."""

from dataclasses import dataclass
import json
import os
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


@dataclass(frozen=True)
class PreferenceSuggestion:
    key: str
    value: str
    confidence: float
    explanation: str


class LocalPreferenceMemory:
    """Contrat QGIS 10.5.1 conservé avec un stockage local ArcGIS Pro."""

    SETTINGS_KEY = "Cartomize/local_learning_v1"
    MAX_CONTEXTS = 80
    MAX_CHOICES_PER_CONTEXT = 40

    def __init__(self, settings=None, path: str | Path | None = None):
        self.settings = settings
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = Path(path) if path else root / "Cartomize" / "local-learning-v1.json"

    def record(self, context: str, **choices: str) -> None:
        context = _clean(context, 120) or "generic"
        payload = self._load()
        contexts = payload.setdefault("contexts", {})
        entry = contexts.setdefault(context, {"uses": 0, "choices": {}})
        entry["uses"] = int(entry.get("uses", 0)) + 1
        store = entry.setdefault("choices", {})
        for key, value in choices.items():
            key, value = _clean(key, 80), _clean(value, 240)
            if not key or not value:
                continue
            values = store.setdefault(key, {})
            values[value] = int(values.get(value, 0)) + 1
            if len(values) > self.MAX_CHOICES_PER_CONTEXT:
                store[key] = dict(sorted(values.items(), key=lambda item: int(item[1]), reverse=True)[: self.MAX_CHOICES_PER_CONTEXT])
        if len(contexts) > self.MAX_CONTEXTS:
            payload["contexts"] = dict(sorted(contexts.items(), key=lambda item: int(item[1].get("uses", 0)), reverse=True)[: self.MAX_CONTEXTS])
        self._save(payload)

    def suggest(self, context: str, key: str) -> PreferenceSuggestion | None:
        values = self._load().get("contexts", {}).get(_clean(context, 120) or "generic", {}).get("choices", {}).get(_clean(key, 80), {})
        if not values:
            return None
        best_value, best_count = max(values.items(), key=lambda item: int(item[1]))
        total = sum(int(count) for count in values.values())
        return PreferenceSuggestion(_clean(key, 80), str(best_value), best_count / max(1, total), f"Cette préférence a été conservée {best_count} fois sur {total}.")

    def clear(self) -> None:
        if self.settings is not None and hasattr(self.settings, "remove"):
            self.settings.remove(self.SETTINGS_KEY)
        else:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def summary(self) -> dict[str, Any]:
        return self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = self.settings.value(self.SETTINGS_KEY, "") if self.settings is not None else self.path.read_text(encoding="utf-8")
            payload = json.loads(str(raw))
            return payload if isinstance(payload, dict) and payload.get("schema") == 1 else {"schema": 1, "contexts": {}}
        except Exception:
            return {"schema": 1, "contexts": {}}

    def _save(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > 128_000:
            payload = {"schema": 1, "contexts": dict(list(payload.get("contexts", {}).items())[:30])}
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if self.settings is not None and hasattr(self.settings, "setValue"):
            self.settings.setValue(self.SETTINGS_KEY, text)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(self.path)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]
