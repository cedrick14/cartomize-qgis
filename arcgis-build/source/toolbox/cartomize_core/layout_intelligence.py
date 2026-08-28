"""Actualisation et optimisation non destructive des mises en page."""

from dataclasses import asdict, dataclass
from typing import Any

from .layout import optimize_layout, synchronize_layout


@dataclass(frozen=True)
class LayoutFinding:
    code: str
    severity: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class LayoutOptimizationReport:
    before_score: int
    after_score: int
    passes: int
    corrections: tuple[str, ...]
    findings: tuple[LayoutFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"before_score": self.before_score, "after_score": self.after_score, "passes": self.passes, "corrections": list(self.corrections), "findings": [item.to_dict() for item in self.findings]}


class AdaptiveLayoutOptimizer:
    def __init__(self, builder=None): self.builder = builder

    def analyze(self, layout) -> tuple[int, tuple[LayoutFinding, ...]]:
        maps = list(layout.listElements("MAPFRAME_ELEMENT"))
        legends = list(layout.listElements("LEGEND_ELEMENT"))
        scales = list(layout.listElements("MAPSURROUND_ELEMENT"))
        texts = list(layout.listElements("TEXT_ELEMENT"))
        findings: list[LayoutFinding] = []
        if not maps: findings.append(LayoutFinding("NO_MAP", "critical", "Aucun cadre cartographique.", "Ajouter un cadre principal."))
        if maps and not legends: findings.append(LayoutFinding("NO_LEGEND", "medium", "Aucune légende n'est présente.", "Ajouter une légende liée au cadre principal."))
        if maps and not scales: findings.append(LayoutFinding("NO_SCALE", "medium", "Aucune barre d'échelle n'est présente.", "Ajouter une barre d'échelle."))
        page_area = max(0.0, float(getattr(layout, "pageWidth", 0) or 0) * float(getattr(layout, "pageHeight", 0) or 0))
        if page_area and maps:
            ratio = sum(_item_area(item) for item in maps) / page_area
            if ratio < .38: findings.append(LayoutFinding("MAP_TOO_SMALL", "high", f"Les cadres occupent seulement {ratio:.0%} de la page.", "Augmenter la place consacrée à la carte."))
            elif ratio > .84: findings.append(LayoutFinding("MAP_TOO_LARGE", "low", f"Les cadres occupent {ratio:.0%} de la page.", "Vérifier l'espace de la légende et des crédits."))
        for text in texts:
            if len(str(getattr(text, "text", "") or "")) > 120 and _item_area(text) < 900:
                findings.append(LayoutFinding("TEXT_DENSE", "medium", "Un bloc de texte long dispose de peu d'espace.", "Agrandir le bloc ou raccourcir le texte."))
        if _overlaps([*maps, *legends, *scales, *texts]):
            findings.append(LayoutFinding("OVERLAP", "high", "Des éléments se chevauchent de manière significative.", "Repositionner les éléments concernés."))
        penalties = {"critical": 35, "high": 18, "medium": 9, "low": 3}
        return max(0, 100 - sum(penalties.get(item.severity, 5) for item in findings)), tuple(findings)

    def optimize(self, layout, *, max_passes: int = 3, target_score: int = 92) -> LayoutOptimizationReport:
        before, _ = self.analyze(layout)
        corrections: list[str] = []
        passes = 0
        for _ in range(max(1, max_passes)):
            passes += 1
            if self.builder is not None:
                corrections.extend(self.builder.optimize_existing_layout(layout))
            else:
                result = optimize_layout(layout)
                corrections.extend(f"{value} {key}" for key, value in result.items() if value)
            score, findings = self.analyze(layout)
            if score >= target_score: break
        return LayoutOptimizationReport(before, score, passes, tuple(dict.fromkeys(corrections)), findings)


def _item_area(item) -> float:
    return max(0.0, float(getattr(item, "elementWidth", 0) or 0)) * max(0.0, float(getattr(item, "elementHeight", 0) or 0))


def _overlaps(items) -> bool:
    boxes = []
    for item in items:
        x, y = float(getattr(item, "elementPositionX", 0) or 0), float(getattr(item, "elementPositionY", 0) or 0)
        w, h = float(getattr(item, "elementWidth", 0) or 0), float(getattr(item, "elementHeight", 0) or 0)
        if w > 0 and h > 0: boxes.append((x, y, x + w, y + h))
    for index, left in enumerate(boxes):
        for right in boxes[index + 1:]:
            inter = max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(0, min(left[3], right[3]) - max(left[1], right[1]))
            if inter > .22 * min((left[2]-left[0])*(left[3]-left[1]), (right[2]-right[0])*(right[3]-right[1])): return True
    return False


__all__ = ["LayoutFinding", "LayoutOptimizationReport", "AdaptiveLayoutOptimizer", "optimize_layout", "synchronize_layout"]
