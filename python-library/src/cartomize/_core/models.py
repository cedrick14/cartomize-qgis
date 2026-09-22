"""Modèles sérialisables utilisés par les outils Cartomize."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    layer_id: str = ""
    layer_name: str = ""
    remediation: str = ""


@dataclass
class Report:
    kind: str
    score: int
    status: str
    statistics: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "generated_at": self.generated_at,
            "score": self.score,
            "status": self.status,
            "statistics": self.statistics,
            "findings": [asdict(item) for item in self.findings],
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FieldProfile:
    name: str
    type_name: str
    count: int
    null_count: int
    null_percent: float
    unique_count: int
    unique_ratio: float
    minimum: float | None
    maximum: float | None
    median: float | None
    mean: float | None
    skewness: float | None
    semantic_role: str
    recommended_use: str
    confidence: float


@dataclass(frozen=True)
class TemplateSpec:
    template_id: str
    name: str
    category: str
    description: str
    page_format: str
    background_color: str
    accent_color: str
    elements: tuple[dict[str, Any], ...]

    @property
    def page_size_mm(self) -> tuple[float, float]:
        from .constants import SUPPORTED_PAGE_FORMATS
        return SUPPORTED_PAGE_FORMATS[self.page_format]


@dataclass(frozen=True)
class LayoutResult:
    layout_name: str
    template_id: str
    map_name: str
    element_count: int
    map_frame_count: int
    basemap_legend_items_removed: int
    export_path: str = ""
    pagx_path: str = ""
    grid_added: bool = False
    warnings: tuple[str, ...] = ()
