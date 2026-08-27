"""Contrôle qualité public, conforme au module QGIS 10.5.1."""

from .audit import audit_project
from .label_intelligence import audit_labels

__all__ = ["audit_project", "audit_labels"]
