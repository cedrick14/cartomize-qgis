"""Validation humaine traçable, équivalente à Cartomize QGIS 10.5.1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .constants import APP_VERSION
from .errors import CartomizeError
from .io_utils import write_json


MANDATORY_CHECKS: tuple[tuple[str, str], ...] = (
    ("data_sources", "Les sources, dates et limites des données sont vérifiées."),
    ("crs_scale", "Le CRS, l’emprise et l’échelle correspondent à l’objectif de la carte."),
    ("symbology", "La symbologie représente correctement les variables et les classes."),
    ("labels", "Les étiquettes sont lisibles, sans ambiguïté ni collision majeure."),
    ("layout_elements", "Le titre, la légende, l’échelle, le nord et les crédits sont cohérents."),
    ("accessibility", "Le contraste, la taille des textes et les couleurs sont accessibles."),
    ("export", "Le fichier exporté a été ouvert et contrôlé au niveau de zoom requis."),
)


@dataclass(frozen=True)
class ValidationCertificate:
    schema_version: int
    cartomize_version: str
    layout_name: str
    automatic_score: int
    automatic_status: str
    human_status: str
    reviewer: str
    organization: str
    reviewed_at: str
    checks: dict[str, bool]
    notes: str
    blockers: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["blockers"] = list(self.blockers)
        return value


def make_certificate(
    *,
    layout_name: str,
    automatic_score: int,
    reviewer: str = "",
    organization: str = "",
    checks: dict[str, bool] | None = None,
    notes: str = "",
    blockers: tuple[str, ...] = (),
    approve: bool = False,
) -> ValidationCertificate:
    normalized = {key: bool((checks or {}).get(key, False)) for key, _ in MANDATORY_CHECKS}
    reviewer = reviewer.strip()
    blockers = tuple(str(item).strip() for item in blockers if str(item).strip())
    if approve:
        if len(reviewer) < 3:
            raise ValueError("Renseignez le nom du cartographe responsable de la validation.")
        if not all(normalized.values()):
            raise ValueError("La validation est incomplète.")
        if blockers:
            raise ValueError("Les anomalies bloquantes doivent être corrigées avant approbation.")
    score = max(0, min(100, int(automatic_score)))
    core = {
        "schema_version": 1,
        "cartomize_version": APP_VERSION,
        "layout_name": str(layout_name),
        "automatic_score": score,
        "automatic_status": "Fort" if score >= 85 else "À améliorer" if score >= 65 else "Insuffisant",
        "human_status": "Approuvée" if approve else "En attente",
        "reviewer": reviewer,
        "organization": organization.strip()[:200],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "checks": normalized,
        "notes": notes.strip()[:5000],
        "blockers": list(blockers),
    }
    fingerprint = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ValidationCertificate(**{**core, "blockers": blockers, "fingerprint": fingerprint})


def save_certificate(certificate: ValidationCertificate, path: str | Path) -> Path:
    return write_json(path, certificate.to_dict())


class HumanValidationService:
    """Contrat de validation QGIS conservé pour les objets Layout ArcGIS Pro."""

    def __init__(self, project=None, version: str = APP_VERSION):
        self.project = project
        self.version = version or APP_VERSION
        self._certificates: dict[str, ValidationCertificate] = {}

    def draft(self, layout, automatic_score: int, blockers=()) -> ValidationCertificate:
        certificate = self._make(layout, automatic_score, "En attente", "", "", {key: False for key, _ in MANDATORY_CHECKS}, "", tuple(blockers))
        self._store(layout, certificate)
        return certificate

    def approve(self, layout, *, automatic_score: int, reviewer: str, organization: str = "", checks: dict[str, bool], notes: str = "", blockers=()) -> ValidationCertificate:
        reviewer = reviewer.strip()
        normalized = {key: bool(checks.get(key, False)) for key, _ in MANDATORY_CHECKS}
        if len(reviewer) < 3:
            raise CartomizeError("Renseignez le nom du cartographe responsable de la validation.")
        if not all(normalized.values()):
            raise CartomizeError("La validation est incomplète. Vérifiez tous les critères obligatoires.")
        if any(str(item).strip() for item in blockers):
            raise CartomizeError("Les anomalies critiques doivent être corrigées avant approbation.")
        certificate = self._make(layout, automatic_score, "Approuvée", reviewer, organization, normalized, notes, ())
        self._store(layout, certificate)
        return certificate

    def reject(self, layout, *, automatic_score: int, reviewer: str, notes: str, blockers=()) -> ValidationCertificate:
        if len(reviewer.strip()) < 3 or len(notes.strip()) < 5:
            raise CartomizeError("Une décision de rejet exige le nom du réviseur et un motif explicite.")
        certificate = self._make(layout, automatic_score, "Rejetée", reviewer.strip(), "", {key: False for key, _ in MANDATORY_CHECKS}, notes, tuple(blockers))
        self._store(layout, certificate)
        return certificate

    def load(self, layout) -> ValidationCertificate | None:
        return self._certificates.get(_layout_name(layout))

    @staticmethod
    def save(certificate: ValidationCertificate, path: str | Path) -> Path:
        return save_certificate(certificate, path)

    def _make(self, layout, score: int, human_status: str, reviewer: str, organization: str, checks: dict[str, bool], notes: str, blockers: tuple[str, ...]) -> ValidationCertificate:
        normalized = {key: bool(checks.get(key, False)) for key, _ in MANDATORY_CHECKS}
        normalized_blockers = tuple(str(item).strip() for item in blockers if str(item).strip())
        normalized_score = max(0, min(100, int(score)))
        core = {
            "schema_version": 1,
            "cartomize_version": self.version,
            "layout_name": _layout_name(layout),
            "automatic_score": normalized_score,
            "automatic_status": "Fort" if normalized_score >= 85 else "À améliorer" if normalized_score >= 65 else "Insuffisant",
            "human_status": human_status,
            "reviewer": reviewer.strip(),
            "organization": organization.strip()[:200],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "checks": normalized,
            "notes": notes.strip()[:5000],
            "blockers": list(normalized_blockers),
        }
        fingerprint = hashlib.sha256(
            json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ValidationCertificate(**{**core, "blockers": normalized_blockers, "fingerprint": fingerprint})

    def _store(self, layout, certificate: ValidationCertificate) -> None:
        self._certificates[_layout_name(layout)] = certificate


def _layout_name(layout) -> str:
    value = getattr(layout, "name", "")
    if callable(value):
        try:
            value = value()
        except Exception:
            value = ""
    return str(value or "Cartomize — Mise en page")
