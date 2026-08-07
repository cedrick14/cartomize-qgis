"""Raisonnement cartographique dépendant de l’échelle."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ScaleRecommendation:
    layer_id: str
    role: str
    scale: float
    visible: bool
    detail_level: str
    label_density: float
    symbol_factor: float
    simplify_tolerance_mm: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScaleIntelligenceEngine:
    """Détermine la densité cartographique adaptée à l’échelle de représentation."""

    def analyze_layer(self, layer, role: str, scale: float) -> ScaleRecommendation:
        scale = max(1.0, float(scale or 1.0))
        role = str(role or "contexte")
        tier = self._tier(scale)
        visible = self._is_visible(role, tier)
        label_density = self._label_density(role, tier) if visible else 0.0
        symbol_factor = self._symbol_factor(role, tier)
        tolerance = self._simplification_tolerance(tier)
        return ScaleRecommendation(
            layer_id=str(layer.id()), role=role, scale=scale, visible=visible,
            detail_level=tier, label_density=label_density,
            symbol_factor=symbol_factor, simplify_tolerance_mm=tolerance,
            reason=self._reason(role, tier, visible),
        )

    def analyze_project(self, layers, roles: dict[str, str], scale: float) -> tuple[ScaleRecommendation, ...]:
        return tuple(
            self.analyze_layer(layer, roles.get(layer.id(), "contexte"), scale)
            for layer in layers if layer is not None and layer.isValid()
        )

    @staticmethod
    def _tier(scale: float) -> str:
        if scale >= 3_000_000:
            return "national"
        if scale >= 800_000:
            return "regional"
        if scale >= 150_000:
            return "territorial"
        if scale >= 30_000:
            return "local"
        return "detail"

    @staticmethod
    def _is_visible(role: str, tier: str) -> bool:
        if role == "principal":
            return True
        hidden = {
            "national": {"parcelles", "bâtiments", "contexte", "points_thématiques"},
            "regional": {"parcelles", "bâtiments"},
            "territorial": set(),
            "local": set(),
            "detail": set(),
        }
        return role not in hidden.get(tier, set())

    @staticmethod
    def _label_density(role: str, tier: str) -> float:
        base = {
            "national": 0.18,
            "regional": 0.35,
            "territorial": 0.58,
            "local": 0.80,
            "detail": 1.0,
        }[tier]
        if role in {"localités", "transport"}:
            return min(1.0, base * 0.9)
        if role in {"limites", "hydrographie"}:
            return min(1.0, base * 0.75)
        return base

    @staticmethod
    def _symbol_factor(role: str, tier: str) -> float:
        factor = {
            "national": 1.25,
            "regional": 1.15,
            "territorial": 1.0,
            "local": 0.92,
            "detail": 0.86,
        }[tier]
        if role == "principal":
            factor *= 1.05
        return round(factor, 3)

    @staticmethod
    def _simplification_tolerance(tier: str) -> float:
        return {
            "national": 0.45,
            "regional": 0.30,
            "territorial": 0.18,
            "local": 0.08,
            "detail": 0.0,
        }[tier]

    @staticmethod
    def _reason(role: str, tier: str, visible: bool) -> str:
        if not visible:
            return f"La couche de rôle « {role} » est trop détaillée pour une vue {tier}."
        return f"La densité et la taille des symboles sont adaptées à une vue {tier}."
