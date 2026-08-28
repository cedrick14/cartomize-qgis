"""Optimisation adaptative et autocorrection sûre des mises en page QGIS."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass
from typing import Any

from qgis.core import QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemScaleBar


@dataclass(frozen=True)
class LayoutFinding:
    code: str
    severity: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LayoutOptimizationReport:
    before_score: int
    after_score: int
    passes: int
    corrections: tuple[str, ...]
    findings: tuple[LayoutFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_score": self.before_score,
            "after_score": self.after_score,
            "passes": self.passes,
            "corrections": list(self.corrections),
            "findings": [finding.to_dict() for finding in self.findings],
        }


class AdaptiveLayoutOptimizer:
    """Mesure la composition puis n’applique que des corrections réversibles et sûres."""

    def __init__(self, builder):
        self.builder = builder

    def analyze(self, layout) -> tuple[int, tuple[LayoutFinding, ...]]:
        findings: list[LayoutFinding] = []
        items = list(layout.items())
        maps = [item for item in items if isinstance(item, QgsLayoutItemMap)]
        legends = [item for item in items if isinstance(item, QgsLayoutItemLegend)]
        scales = [item for item in items if isinstance(item, QgsLayoutItemScaleBar)]
        labels = [item for item in items if isinstance(item, QgsLayoutItemLabel)]
        if not maps:
            findings.append(LayoutFinding("NO_MAP", "critical", "Aucun cadre cartographique.", "Ajouter un cadre principal."))
        if maps and not legends:
            findings.append(LayoutFinding("NO_LEGEND", "medium", "Aucune légende n’est présente.", "Ajouter une légende liée au cadre principal."))
        if maps and not scales:
            findings.append(LayoutFinding("NO_SCALE", "medium", "Aucune barre d’échelle n’est présente.", "Ajouter une barre d’échelle liée au cadre principal."))
        page_area = self._page_area(layout)
        if page_area > 0 and maps:
            map_area = sum(self._item_area(item) for item in maps)
            ratio = map_area / page_area
            if ratio < 0.38:
                findings.append(LayoutFinding("MAP_TOO_SMALL", "high", f"Les cadres cartographiques occupent seulement {ratio:.0%} de la page.", "Augmenter la place consacrée à la carte."))
            elif ratio > 0.84:
                findings.append(LayoutFinding("MAP_TOO_LARGE", "low", f"Les cadres occupent {ratio:.0%} de la page.", "Vérifier l’espace disponible pour la légende et les crédits."))
        for legend in legends:
            rows = self._legend_rows(legend)
            if rows >= 15:
                findings.append(LayoutFinding("LEGEND_DENSE", "medium", f"La légende contient environ {rows} entrées.", "Utiliser plusieurs colonnes ou un format de page plus large."))
        for label in labels:
            text = self._label_text(label).strip()
            if len(text) > 120 and self._item_area(label) < 900:
                findings.append(LayoutFinding("TEXT_DENSE", "medium", "Un bloc de texte long dispose de peu d’espace.", "Agrandir le bloc ou raccourcir le texte."))
        overlaps = self._significant_overlaps(items)
        if overlaps:
            findings.append(LayoutFinding("OVERLAP", "high", f"{len(overlaps)} chevauchement(s) significatif(s) entre éléments de mise en page.", "Repositionner les éléments concernés."))
        penalties = {"critical": 35, "high": 18, "medium": 9, "low": 3, "info": 0}
        score = max(0, 100 - sum(penalties.get(item.severity, 5) for item in findings))
        return score, tuple(findings)

    def optimize(self, layout, *, max_passes: int = 3, target_score: int = 92) -> LayoutOptimizationReport:
        before, _ = self.analyze(layout)
        corrections: list[str] = []
        passes = 0
        for _ in range(max(1, max_passes)):
            passes += 1
            try:
                corrections.extend(self.builder.optimize_existing_layout(layout))
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            for item in list(layout.items()):
                if isinstance(item, QgsLayoutItemLegend):
                    rows = self._legend_rows(item)
                    if rows >= 22:
                        try:
                            item.setColumnCount(3)
                            corrections.append("légende sur trois colonnes")
                        except Exception:
                            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
                    elif rows >= 12:
                        try:
                            item.setColumnCount(2)
                            corrections.append("légende sur deux colonnes")
                        except Exception:
                            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
                    try:
                        item.refresh()
                    except Exception:
                        logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            try:
                layout.refresh()
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
            score, findings = self.analyze(layout)
            if score >= target_score:
                return LayoutOptimizationReport(before, score, passes, tuple(dict.fromkeys(corrections)), findings)
        score, findings = self.analyze(layout)
        return LayoutOptimizationReport(before, score, passes, tuple(dict.fromkeys(corrections)), findings)

    @staticmethod
    def _page_area(layout) -> float:
        try:
            page = layout.pageCollection().page(0)
            size = page.pageSize()
            return float(size.width()) * float(size.height())
        except Exception:
            return 0.0

    @staticmethod
    def _item_area(item) -> float:
        try:
            size = item.sizeWithUnits()
            return max(0.0, float(size.width())) * max(0.0, float(size.height()))
        except Exception:
            return 0.0

    @staticmethod
    def _legend_rows(legend) -> int:
        try:
            model = legend.model()
            return max(0, int(model.rowCount()))
        except Exception:
            return 0

    @staticmethod
    def _label_text(label) -> str:
        for attr in ("currentText", "text"):
            method = getattr(label, attr, None)
            if callable(method):
                try:
                    return str(method())
                except Exception:
                    logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        return ""

    def _significant_overlaps(self, items) -> list[tuple[Any, Any]]:
        boxes: list[tuple[Any, tuple[float, float, float, float]]] = []
        for item in items:
            if not isinstance(item, (QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemLabel)):
                continue
            box = self._box(item)
            if box is not None:
                boxes.append((item, box))
        overlaps = []
        for i, (left_item, left) in enumerate(boxes):
            for right_item, right in boxes[i + 1:]:
                # Linked scale bars and labels may intentionally touch map frames; only flag large intersections.
                inter = _intersection_area(left, right)
                if inter <= 0:
                    continue
                smaller = min(_area(left), _area(right))
                if smaller > 0 and inter / smaller > 0.22:
                    overlaps.append((left_item, right_item))
        return overlaps

    @staticmethod
    def _box(item):
        try:
            pos = item.positionWithUnits()
            size = item.sizeWithUnits()
            x, y = float(pos.x()), float(pos.y())
            w, h = float(size.width()), float(size.height())
            return (x, y, x + w, y + h)
        except Exception:
            return None


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection_area(a, b) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, width) * max(0.0, height)
