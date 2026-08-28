"""Contrôle qualité public, conforme au module QGIS 10.5.1."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json

from .audit import audit_project
from .label_intelligence import audit_labels


def severity_label(value: str) -> str:
    return {"critical": "Critique", "high": "Élevé", "medium": "Moyen", "low": "Faible", "info": "Information"}.get(str(value).casefold(), str(value))


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    message: str
    layer_id: str = ""
    layer_name: str = ""
    remediation: str = ""


@dataclass
class AuditReport:
    generated_at: str
    score: int
    status: str
    findings: list[AuditFinding]
    statistics: dict

    def to_dict(self) -> dict:
        return {"generated_at": self.generated_at, "score": self.score, "status": self.status, "statistics": self.statistics, "findings": [asdict(item) for item in self.findings]}

    def to_json(self) -> str: return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = ["Audit Cartomize", f"Score : {self.score}/100", f"Statut : {self.status}", f"Date de génération : {self.generated_at}", ""]
        if not self.findings: return "\n".join((*lines, "Aucune anomalie détectée par les contrôles automatiques."))
        for item in self.findings:
            lines.extend((f"Niveau : {severity_label(item.severity)}", f"Code : {item.code}"))
            if item.layer_name: lines.append(f"Couche : {item.layer_name}")
            lines.append(f"Observation : {item.message}")
            if item.remediation: lines.append(f"Action recommandée : {item.remediation}")
            lines.append("")
        return "\n".join(lines).rstrip()


class ProjectQualityAuditor:
    def __init__(self, project=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy()
        self.project = project or self.arcpy.mp.ArcGISProject("CURRENT")

    def run(self, layers=None) -> AuditReport:
        report = audit_project(self.arcpy, self.project)
        findings = [AuditFinding(item.severity, item.code, item.message, item.layer_id, item.layer_name, item.remediation) for item in report.findings]
        return AuditReport(datetime.now(timezone.utc).isoformat(), report.score, report.status, findings, dict(report.statistics))


def _import_arcpy():
    try:
        import arcpy
        return arcpy
    except ImportError as exc:
        raise RuntimeError("ArcPy est requis pour le contrôle qualité.") from exc


__all__ = ["severity_label", "AuditFinding", "AuditReport", "ProjectQualityAuditor", "audit_project", "audit_labels"]
