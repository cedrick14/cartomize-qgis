"""Manifestes de production Cartomize, compatibles avec QGIS 10.5.1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import json
import re
from typing import Any

from .autopilot import AutomationRecipe
from .exporter import NativeLayoutExporter


MAX_BATCH_JOBS = 5_000
SUPPORTED_EXPORTS = {"pdf", "svg", "png", "jpg", "tif", "pagx", "qpt"}


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


def load_manifest(path: str | Path) -> BatchManifest:
    source = Path(path).expanduser().resolve(strict=True)
    if source.stat().st_size > 5_000_000:
        raise ValueError("Le manifeste de production est trop volumineux.")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("Le manifeste de production est incompatible.")
    jobs_payload = payload.get("jobs")
    if not isinstance(jobs_payload, list) or not jobs_payload:
        raise ValueError("Le manifeste ne contient aucune carte.")
    if len(jobs_payload) > MAX_BATCH_JOBS:
        raise ValueError(f"Le manifeste dépasse la limite de {MAX_BATCH_JOBS} cartes.")

    jobs: list[BatchJob] = []
    for index, item in enumerate(jobs_payload):
        if not isinstance(item, dict):
            raise ValueError(f"La carte {index + 1} du manifeste est invalide.")
        formats = tuple(
            str(value).casefold() for value in item.get("output_formats", ["pdf"])
            if str(value).casefold() in SUPPORTED_EXPORTS
        ) or ("pdf",)
        jobs.append(BatchJob(
            job_id=str(item.get("job_id") or f"job-{index + 1}")[:100],
            output_name=str(item.get("output_name") or f"carte-{index + 1}")[:180],
            title=str(item.get("title") or "")[:300],
            subtitle=str(item.get("subtitle") or "")[:500],
            sources=str(item.get("sources") or "")[:2000],
            variables=dict(item.get("variables") or {}),
            layer_bindings={
                str(key): str(value)
                for key, value in dict(item.get("layer_bindings") or {}).items()
            },
            output_formats=formats,
        ))

    recipe_path = Path(str(payload.get("recipe_path") or ""))
    if not recipe_path.is_absolute():
        recipe_path = (source.parent / recipe_path).resolve(strict=False)
    output_directory = Path(str(payload.get("output_directory") or "outputs"))
    if not output_directory.is_absolute():
        output_directory = (source.parent / output_directory).resolve(strict=False)
    return BatchManifest(
        schema_version=1,
        recipe_path=str(recipe_path),
        output_directory=str(output_directory),
        jobs=tuple(jobs),
        dpi=max(72, min(1200, int(payload.get("dpi", 300)))),
        keep_layouts=bool(payload.get("keep_layouts", False)),
        require_human_validation=bool(payload.get("require_human_validation", True)),
    )


def safe_output_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip()).strip(".-")
    return cleaned[:180] or "carte-cartomize"


@dataclass(frozen=True)
class BatchItemResult:
    job_id: str; status: str; layout_name: str; automatic_score: int
    validation_status: str; outputs: tuple[str, ...]; warnings: tuple[str, ...]; error: str = ""


@dataclass(frozen=True)
class BatchRunReport:
    started_at: str; finished_at: str; total: int; succeeded: int; failed: int
    canceled: bool; items: tuple[BatchItemResult, ...]
    def to_dict(self) -> dict[str, Any]:
        return {"started_at": self.started_at, "finished_at": self.finished_at, "total": self.total, "succeeded": self.succeeded, "failed": self.failed, "canceled": self.canceled, "items": [asdict(item) for item in self.items]}


class CartomizeBatchRunner:
    def __init__(self, autopilot, exporter: NativeLayoutExporter | None = None, project=None, version: str = ""):
        self.autopilot = autopilot; self.exporter = exporter or NativeLayoutExporter(getattr(autopilot, "arcpy", None)); self.project = project or getattr(autopilot, "project", None); self.version = version

    def run(self, manifest: BatchManifest, feedback=None) -> BatchRunReport:
        started = datetime.now(timezone.utc).isoformat(); items = []; canceled = False
        recipe = self.autopilot.load_recipe(manifest.recipe_path)
        output_dir = Path(manifest.output_directory).expanduser().resolve(); output_dir.mkdir(parents=True, exist_ok=True)
        for job in manifest.jobs:
            if feedback is not None and bool(getattr(feedback, "isCanceled", lambda: False)()): canceled = True; break
            try:
                job_recipe = self._recipe_for_job(recipe, job); built = self.autopilot.replay_recipe(job_recipe); outputs = self._export_job(built.layout, output_dir, job, manifest.dpi)
                items.append(BatchItemResult(job.job_id, "success", built.layout_name, 0, "En attente", outputs, built.warnings))
            except Exception as exc:
                items.append(BatchItemResult(job.job_id, "failed", "", 0, "Non validée", (), (), str(exc)))
        succeeded = sum(item.status == "success" for item in items)
        return BatchRunReport(started, datetime.now(timezone.utc).isoformat(), len(manifest.jobs), succeeded, len(items)-succeeded, canceled, tuple(items))

    @staticmethod
    def _recipe_for_job(recipe: AutomationRecipe, job: BatchJob) -> AutomationRecipe:
        payload = recipe.to_dict(); variant = dict(payload["variant"])
        if job.title: variant["title"] = job.title
        if job.subtitle: variant["subtitle"] = job.subtitle
        payload["variant"] = variant
        if job.sources: payload["sources"] = job.sources
        return AutomationRecipe.from_dict(payload)

    def _export_job(self, layout, output_dir: Path, job: BatchJob, dpi: int) -> tuple[str, ...]:
        outputs = []
        for fmt in job.output_formats:
            if fmt in {"pagx", "qpt"}: result = self.exporter.save_as_qpt(layout, str(output_dir / safe_output_name(job.output_name)))
            else: result = self.exporter.export(layout, str(output_dir / f"{safe_output_name(job.output_name)}.{fmt}"), fmt, dpi=dpi)
            outputs.append(result.path)
        return tuple(outputs)


def create_matrix_manifest(recipe_path: str, output_directory: str, dimensions: dict[str, list[Any]], *, formats=("pdf",), title_pattern: str = "{name}") -> BatchManifest:
    keys = tuple(dimensions)
    values = [list(dimensions[key]) for key in keys]
    combinations = list(product(*values)) if values else [()]
    if len(combinations) > MAX_BATCH_JOBS: raise ValueError(f"Le manifeste dépasse la limite de {MAX_BATCH_JOBS} cartes.")
    jobs = []
    for index, combination in enumerate(combinations, 1):
        variables = dict(zip(keys, combination)); variables.setdefault("name", f"carte-{index}")
        try: title = title_pattern.format(**variables)
        except (KeyError, ValueError): title = str(variables["name"])
        jobs.append(BatchJob(f"job-{index}", safe_output_name(title), title=title, variables=variables, output_formats=tuple(str(item).casefold() for item in formats if str(item).casefold() in SUPPORTED_EXPORTS) or ("pdf",)))
    return BatchManifest(1, recipe_path, output_directory, tuple(jobs))


def save_manifest(manifest: BatchManifest, path: str | Path) -> Path:
    target = Path(path).expanduser().resolve(); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"); return target


def save_report(report: BatchRunReport, path: str | Path) -> Path:
    target = Path(path).expanduser().resolve(); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"); return target
