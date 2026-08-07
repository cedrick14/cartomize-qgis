"""Validation cartographique humaine, traçable et distincte du score automatique."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from qgis.core import QgsProject

from .errors import CartomizeError


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
        data = asdict(self)
        data["blockers"] = list(self.blockers)
        return data


class HumanValidationService:
    """Impose une décision humaine explicite avant le statut « validé »."""

    def __init__(self, project: QgsProject | None = None, version: str = ""):
        self.project = project or QgsProject.instance()
        self.version = version

    def draft(
        self,
        layout,
        automatic_score: int,
        blockers: list[str] | tuple[str, ...] = (),
    ) -> ValidationCertificate:
        certificate = self._make(
            layout=layout,
            automatic_score=automatic_score,
            automatic_status=self._automatic_status(automatic_score),
            human_status="En attente",
            reviewer="",
            organization="",
            checks={key: False for key, _label in MANDATORY_CHECKS},
            notes="",
            blockers=tuple(blockers),
        )
        self._store(layout, certificate)
        return certificate

    def approve(
        self,
        layout,
        *,
        automatic_score: int,
        reviewer: str,
        organization: str = "",
        checks: dict[str, bool],
        notes: str = "",
        blockers: list[str] | tuple[str, ...] = (),
    ) -> ValidationCertificate:
        reviewer = reviewer.strip()
        if len(reviewer) < 3:
            raise CartomizeError("Renseignez le nom du cartographe responsable de la validation.")
        normalized = {key: bool(checks.get(key, False)) for key, _label in MANDATORY_CHECKS}
        missing = [label for key, label in MANDATORY_CHECKS if not normalized[key]]
        if missing:
            raise CartomizeError("La validation est incomplète. Vérifiez tous les critères obligatoires.")
        blockers = tuple(str(item).strip() for item in blockers if str(item).strip())
        if blockers:
            raise CartomizeError("La carte ne peut pas être approuvée tant que les anomalies critiques ne sont pas corrigées.")
        certificate = self._make(
            layout=layout,
            automatic_score=automatic_score,
            automatic_status=self._automatic_status(automatic_score),
            human_status="Approuvée",
            reviewer=reviewer,
            organization=organization.strip()[:200],
            checks=normalized,
            notes=notes.strip()[:5000],
            blockers=(),
        )
        self._store(layout, certificate)
        self.project.setDirty(True)
        return certificate

    def reject(
        self,
        layout,
        *,
        automatic_score: int,
        reviewer: str,
        notes: str,
        blockers: list[str] | tuple[str, ...] = (),
    ) -> ValidationCertificate:
        if len(reviewer.strip()) < 3 or len(notes.strip()) < 5:
            raise CartomizeError("Une décision de rejet exige le nom du réviseur et un motif explicite.")
        certificate = self._make(
            layout=layout,
            automatic_score=automatic_score,
            automatic_status=self._automatic_status(automatic_score),
            human_status="Rejetée",
            reviewer=reviewer.strip(),
            organization="",
            checks={key: False for key, _label in MANDATORY_CHECKS},
            notes=notes.strip()[:5000],
            blockers=tuple(blockers),
        )
        self._store(layout, certificate)
        self.project.setDirty(True)
        return certificate

    def load(self, layout) -> ValidationCertificate | None:
        raw = layout.customProperty("cartomize/validation_certificate", "")
        if not raw:
            return None
        try:
            payload = json.loads(str(raw))
            return ValidationCertificate(
                schema_version=int(payload.get("schema_version", 1)),
                cartomize_version=str(payload.get("cartomize_version", "")),
                layout_name=str(payload.get("layout_name", layout.name())),
                automatic_score=int(payload.get("automatic_score", 0)),
                automatic_status=str(payload.get("automatic_status", "")),
                human_status=str(payload.get("human_status", "En attente")),
                reviewer=str(payload.get("reviewer", "")),
                organization=str(payload.get("organization", "")),
                reviewed_at=str(payload.get("reviewed_at", "")),
                checks={str(k): bool(v) for k, v in dict(payload.get("checks", {})).items()},
                notes=str(payload.get("notes", "")),
                blockers=tuple(str(item) for item in payload.get("blockers", [])),
                fingerprint=str(payload.get("fingerprint", "")),
            )
        except Exception:
            return None

    @staticmethod
    def save(certificate: ValidationCertificate, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve(strict=False)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or destination.parent.is_symlink():
            raise CartomizeError("Le certificat ne peut pas être écrit dans un lien symbolique.")
        payload = json.dumps(certificate.to_dict(), ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp", dir=str(destination.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(destination)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return destination

    def _make(
        self,
        *,
        layout,
        automatic_score: int,
        automatic_status: str,
        human_status: str,
        reviewer: str,
        organization: str,
        checks: dict[str, bool],
        notes: str,
        blockers: tuple[str, ...],
    ) -> ValidationCertificate:
        reviewed_at = datetime.now(timezone.utc).isoformat()
        core = {
            "schema_version": 1,
            "cartomize_version": self.version,
            "layout_name": layout.name(),
            "automatic_score": max(0, min(100, int(automatic_score))),
            "automatic_status": automatic_status,
            "human_status": human_status,
            "reviewer": reviewer,
            "organization": organization,
            "reviewed_at": reviewed_at,
            "checks": checks,
            "notes": notes,
            "blockers": list(blockers),
        }
        fingerprint = hashlib.sha256(
            json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ValidationCertificate(
            schema_version=core["schema_version"],
            cartomize_version=core["cartomize_version"],
            layout_name=core["layout_name"],
            automatic_score=core["automatic_score"],
            automatic_status=core["automatic_status"],
            human_status=core["human_status"],
            reviewer=core["reviewer"],
            organization=core["organization"],
            reviewed_at=core["reviewed_at"],
            checks=dict(core["checks"]),
            notes=core["notes"],
            blockers=blockers,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _automatic_status(score: int) -> str:
        return "Fort" if score >= 85 else "À améliorer" if score >= 65 else "Insuffisant"

    def _store(self, layout, certificate: ValidationCertificate) -> None:
        encoded = json.dumps(certificate.to_dict(), ensure_ascii=False, separators=(",", ":"))
        layout.setCustomProperty("cartomize/validation_status", certificate.human_status)
        layout.setCustomProperty("cartomize/validation_reviewer", certificate.reviewer)
        layout.setCustomProperty("cartomize/validation_fingerprint", certificate.fingerprint)
        layout.setCustomProperty("cartomize/validation_certificate", encoded)
