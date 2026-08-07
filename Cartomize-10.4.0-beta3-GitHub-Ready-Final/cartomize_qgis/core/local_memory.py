"""Mémoire locale des préférences cartographiques acceptées par l'utilisateur."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from qgis.core import QgsSettings


@dataclass(frozen=True)
class PreferenceSuggestion:
    key: str
    value: str
    confidence: float
    explanation: str


class LocalPreferenceMemory:
    """Mémorise uniquement des préférences de présentation, jamais les données SIG."""

    SETTINGS_KEY = "Cartomize/local_learning_v1"
    MAX_CONTEXTS = 80
    MAX_CHOICES_PER_CONTEXT = 40

    def __init__(self, settings: QgsSettings | None = None):
        self.settings = settings or QgsSettings()

    def record(self, context: str, **choices: str) -> None:
        context = _clean(context, 120) or "generic"
        payload = self._load()
        contexts = payload.setdefault("contexts", {})
        entry = contexts.setdefault(context, {"uses": 0, "choices": {}})
        entry["uses"] = int(entry.get("uses", 0)) + 1
        store = entry.setdefault("choices", {})
        for key, value in choices.items():
            key = _clean(key, 80)
            value = _clean(value, 240)
            if not key or not value:
                continue
            values = store.setdefault(key, {})
            values[value] = int(values.get(value, 0)) + 1
        if len(contexts) > self.MAX_CONTEXTS:
            ordered = sorted(contexts.items(), key=lambda item: int(item[1].get("uses", 0)), reverse=True)
            payload["contexts"] = dict(ordered[: self.MAX_CONTEXTS])
        self._save(payload)

    def suggest(self, context: str, key: str) -> PreferenceSuggestion | None:
        context = _clean(context, 120) or "generic"
        key = _clean(key, 80)
        payload = self._load()
        entry = payload.get("contexts", {}).get(context, {})
        values = entry.get("choices", {}).get(key, {})
        if not values:
            return None
        best_value, best_count = max(values.items(), key=lambda item: int(item[1]))
        total = sum(int(count) for count in values.values())
        confidence = best_count / max(1, total)
        return PreferenceSuggestion(
            key=key,
            value=str(best_value),
            confidence=confidence,
            explanation=(
                f"Cette préférence a été conservée {best_count} fois sur {total} dans des cartes de type « {context} »."
            ),
        )

    def clear(self) -> None:
        self.settings.remove(self.SETTINGS_KEY)

    def summary(self) -> dict[str, Any]:
        return self._load()

    def _load(self) -> dict[str, Any]:
        raw = self.settings.value(self.SETTINGS_KEY, "")
        if not raw:
            return {"schema": 1, "contexts": {}}
        try:
            payload = json.loads(str(raw))
            if not isinstance(payload, dict) or payload.get("schema") != 1:
                return {"schema": 1, "contexts": {}}
            return payload
        except Exception:
            return {"schema": 1, "contexts": {}}

    def _save(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        # Guard against unbounded settings growth.
        if len(text.encode("utf-8")) > 128_000:
            payload = {"schema": 1, "contexts": dict(list(payload.get("contexts", {}).items())[:30])}
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.settings.setValue(self.SETTINGS_KEY, text)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]
