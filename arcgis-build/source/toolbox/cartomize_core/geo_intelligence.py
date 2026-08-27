"""Analyse combinée du projet et des relations cartographiques."""

from .audit import audit_project
from .project_service import project_summary


def analyze_project(arcpy, aprx) -> dict[str, object]:
    report = audit_project(arcpy, aprx)
    return {"summary": project_summary(aprx), "audit": report.to_dict()}
