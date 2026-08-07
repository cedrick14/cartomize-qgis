"""Production cartographique en série à partir de recettes Cartomize."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from itertools import product
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsExpressionContextUtils, QgsProject

from .autopilot import AutomationRecipe, CartomizeAutopilot
from .errors import CartomizeError
from .exporter import NativeLayoutExporter
from .human_validation import HumanValidationService


MAX_BATCH_JOBS = 5_000
SUPPORTED_EXPORTS = {"pdf", "svg", "png", "jpg", "tif", "qpt"}


@dataclass(frozen=True)
class BatchJob:
    job_id: str
    output_name: str
    title: str = ""
    subtitle: str = ""
    sources: str = ""
    variables: dict[str, Any] | None = None
    layer_bindings: dict[str, str] | None = None
    output_formats: tuple[str, ...] = ("pdf",)


@dataclass(frozen=True)
class BatchManifest:
    schema_version: int
    recipe_path: str
    output_directory: str
    jobs: tuple[BatchJob, ...]
    dpi: int = 300
    keep_layouts: bool = False
    require_human_validation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recipe_path": self.recipe_path,
            "output_directory": self.output_directory,
            "dpi": self.dpi,
            "keep_layouts": self.keep_layouts,
            "require_human_validation": self.require_human_validation,
            "jobs": [asdict(item) for item in self.jobs],
        }


@dataclass(frozen=True)
class BatchItemResult:
    job_id: str
    status: str
    layout_name: str
    automatic_score: int
    validation_status: str
    outputs: tuple[str, ...]
    warnings: tuple[str, ...]
    error: str = ""


@dataclass(frozen=True)
class BatchRunReport:
    started_at: str
    finished_at: str
    total: int
    succeeded: int
    failed: int
    canceled: bool
    items: tuple[BatchItemResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "canceled": self.canceled,
            "items": [asdict(item) for item in self.items],
        }


class CartomizeBatchRunner:
    """Exécute des centaines de cartes de façon séquentielle et contrôlable."""

    def __init__(
        self,
        autopilot: CartomizeAutopilot,
        exporter: NativeLayoutExporter | None = None,
        project: QgsProject | None = None,
        version: str = "",
    ):
        self.autopilot = autopilot
        self.exporter = exporter or NativeLayoutExporter()
        self.project = project or QgsProject.instance()
        self.validator = HumanValidationService(self.project, version)

    def run(self, manifest: BatchManifest, feedback=None) -> BatchRunReport:
        if not manifest.jobs:
            raise CartomizeError("Le manifeste de production ne contient aucune carte.")
        if len(manifest.jobs) > MAX_BATCH_JOBS:
            raise CartomizeError(f"Une série ne peut pas dépasser {MAX_BATCH_JOBS} cartes.")
        output_dir = Path(manifest.output_directory).expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.is_symlink():
            raise CartomizeError("Le dossier de sortie ne peut pas être un lien symbolique.")
        recipe = self.autopilot.load_recipe(manifest.recipe_path)
        started = _utc_now()
        items: list[BatchItemResult] = []
        canceled = False

        for index, job in enumerate(manifest.jobs):
            if feedback is not None and getattr(feedback, "isCanceled", lambda: False)():
                canceled = True
                break
            if feedback is not None:
                feedback.setProgress(index * 100.0 / len(manifest.jobs))
                feedback.pushInfo(f"Carte {index + 1}/{len(manifest.jobs)} : {job.output_name}")
                QCoreApplication.processEvents()
            layout = None
            try:
                self._set_variables(job.variables or {})
                job_recipe = self._recipe_for_job(recipe, job)
                result = self.autopilot.replay_recipe(job_recipe)
                layout = result.layout
                validation = self.validator.draft(
                    layout,
                    result.final_score,
                    [warning for warning in result.warnings if "CRS" in warning or "invalide" in warning.casefold()],
                )
                outputs = self._export_job(layout, output_dir, job, manifest.dpi)
                items.append(
                    BatchItemResult(
                        job.job_id,
                        "Réussie",
                        result.layout_name,
                        result.final_score,
                        validation.human_status if manifest.require_human_validation else "Non requise",
                        tuple(outputs),
                        result.warnings,
                    )
                )
            except Exception as exc:
                items.append(
                    BatchItemResult(job.job_id, "Échec", layout.name() if layout else "", 0, "Non validée", (), (), str(exc))
                )
                if feedback is not None:
                    feedback.reportError(f"{job.output_name} : {exc}", fatalError=False)
            finally:
                if layout is not None and not manifest.keep_layouts:
                    try:
                        self.project.layoutManager().removeLayout(layout)
                    except Exception:
                        pass
        if feedback is not None:
            feedback.setProgress(100.0)
            QCoreApplication.processEvents()
        succeeded = sum(item.status == "Réussie" for item in items)
        return BatchRunReport(
            started,
            _utc_now(),
            len(manifest.jobs),
            succeeded,
            sum(item.status == "Échec" for item in items),
            canceled,
            tuple(items),
        )

    def _recipe_for_job(self, recipe: AutomationRecipe, job: BatchJob) -> AutomationRecipe:
        variant = dict(recipe.variant)
        if job.title:
            variant["title"] = job.title[:300]
        if job.subtitle:
            variant["subtitle"] = job.subtitle[:500]
        layer_names = list(recipe.layer_names)
        if job.layer_bindings:
            layer_names = [job.layer_bindings.get(name, name) for name in layer_names]
        return replace(
            recipe,
            layer_names=tuple(layer_names),
            variant=variant,
            sources=job.sources[:2000] if job.sources else recipe.sources,
        )

    def _export_job(self, layout, output_dir: Path, job: BatchJob, dpi: int) -> list[str]:
        stem = _safe_name(job.output_name or job.job_id)
        outputs: list[str] = []
        formats = tuple(dict.fromkeys(fmt.casefold() for fmt in job.output_formats if fmt.casefold() in SUPPORTED_EXPORTS)) or ("pdf",)
        for fmt in formats:
            target = output_dir / f"{stem}.{fmt}"
            if fmt == "qpt":
                exported = self.exporter.save_as_qpt(layout, str(target))
            else:
                exported = self.exporter.export(layout, str(target), fmt, dpi=dpi)
            outputs.append(exported.path)
        return outputs

    def _set_variables(self, variables: dict[str, Any]) -> None:
        for key, value in variables.items():
            safe = re.sub(r"[^A-Za-z0-9_]", "_", str(key))[:80]
            if safe:
                QgsExpressionContextUtils.setProjectVariable(self.project, f"cartomize_{safe}", value)


def load_manifest(path: str | Path) -> BatchManifest:
    source = Path(path).expanduser().resolve(strict=True)
    if source.stat().st_size > 5_000_000:
        raise CartomizeError("Le manifeste de production est trop volumineux.")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise CartomizeError("Le manifeste de production est incompatible.")
    jobs_payload = payload.get("jobs")
    if not isinstance(jobs_payload, list) or not jobs_payload:
        raise CartomizeError("Le manifeste ne contient aucune carte.")
    if len(jobs_payload) > MAX_BATCH_JOBS:
        raise CartomizeError(f"Le manifeste dépasse la limite de {MAX_BATCH_JOBS} cartes.")
    jobs = []
    for index, item in enumerate(jobs_payload):
        if not isinstance(item, dict):
            raise CartomizeError(f"La carte {index + 1} du manifeste est invalide.")
        formats = tuple(str(fmt).casefold() for fmt in item.get("output_formats", ["pdf"]))
        jobs.append(
            BatchJob(
                job_id=str(item.get("job_id") or f"job-{index + 1}")[:100],
                output_name=str(item.get("output_name") or f"carte-{index + 1}")[:180],
                title=str(item.get("title") or "")[:300],
                subtitle=str(item.get("subtitle") or "")[:500],
                sources=str(item.get("sources") or "")[:2000],
                variables=dict(item.get("variables") or {}),
                layer_bindings={str(k): str(v) for k, v in dict(item.get("layer_bindings") or {}).items()},
                output_formats=formats,
            )
        )
    recipe_path = Path(str(payload.get("recipe_path") or ""))
    if not recipe_path.is_absolute():
        recipe_path = (source.parent / recipe_path).resolve(strict=False)
    output_directory = Path(str(payload.get("output_directory") or "outputs"))
    if not output_directory.is_absolute():
        output_directory = (source.parent / output_directory).resolve(strict=False)
    return BatchManifest(
        1,
        str(recipe_path),
        str(output_directory),
        tuple(jobs),
        max(72, min(1200, int(payload.get("dpi", 300)))),
        bool(payload.get("keep_layouts", False)),
        bool(payload.get("require_human_validation", True)),
    )


def create_matrix_manifest(
    recipe_path: str,
    output_directory: str,
    dimensions: dict[str, list[Any]],
    *,
    formats: Iterable[str] = ("pdf",),
    title_pattern: str = "{name}",
) -> BatchManifest:
    keys = list(dimensions)
    values = [list(dimensions[key]) for key in keys]
    count = 1
    for items in values:
        count *= max(1, len(items))
    if count > MAX_BATCH_JOBS:
        raise CartomizeError(f"La matrice générerait {count} cartes, au-delà de la limite de {MAX_BATCH_JOBS}.")
    jobs = []
    for index, combination in enumerate(product(*values), start=1):
        variables = dict(zip(keys, combination))
        context = {**variables, "name": " ".join(str(item) for item in combination), "index": index}
        output_name = _safe_name("-".join(f"{key}-{value}" for key, value in variables.items()))
        try:
            title = title_pattern.format_map(_SafeFormat(context))
        except Exception:
            title = str(context["name"])
        jobs.append(BatchJob(f"job-{index}", output_name, title=title, variables=variables, output_formats=tuple(formats)))
    return BatchManifest(1, recipe_path, output_directory, tuple(jobs))


def save_manifest(manifest: BatchManifest, path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve(strict=False)
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(destination)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return destination


def save_report(report: BatchRunReport, path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve(strict=False)
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(destination)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return destination


class _SafeFormat(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return cleaned[:180] or "carte-cartomize"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
