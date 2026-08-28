"""Suivi MapOps local, compatible avec le contrat QGIS 10.5.1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .errors import CartomizeError


def snapshot(aprx: Any, arcpy: Any | None = None) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    maps: list[dict[str, Any]] = []
    for map_item in aprx.listMaps():
        map_layers: list[str] = []
        for layer in map_item.listLayers():
            record = _layer_snapshot(layer, arcpy)
            layers.append(record)
            map_layers.append(record["layer_id"])
        maps.append({"name": str(map_item.name), "layer_ids": map_layers})
    layouts = tuple(sorted(str(item.name) for item in aprx.listLayouts()))
    project_crs = ""
    active_map = getattr(aprx, "activeMap", None)
    if active_map is not None:
        project_crs = str(getattr(getattr(active_map, "spatialReference", None), "name", "") or "")
    core = {
        "project_file": str(getattr(aprx, "filePath", "") or ""),
        "project_crs": project_crs,
        "maps": maps,
        "layers": sorted(layers, key=lambda item: (item["layer_id"], item["name"])),
        "layouts": list(layouts),
    }
    captured_at = _utc_now()
    return {
        "schema": "cartomize.arcgispro.mapops/v1",
        "schema_version": 1,
        "created_at": captured_at,
        "captured_at": captured_at,
        **core,
        "project": {"maps": maps, "layouts": list(layouts)},
        "fingerprint": _fingerprint(core),
    }


def compare(previous_path: str | Path, current: dict[str, Any]) -> dict[str, Any]:
    previous = read_json(previous_path)
    before = {item["layer_id"]: item for item in previous.get("layers", [])}
    after = {item["layer_id"]: item for item in current.get("layers", [])}
    changes: list[dict[str, Any]] = []
    for layer_id in sorted(before.keys() - after.keys()):
        item = before[layer_id]
        changes.append(_change("removed", "Élevé", item, "La couche a été retirée du projet.", "Reconstruire les cartes et recettes concernées."))
    for layer_id in sorted(after.keys() - before.keys()):
        item = after[layer_id]
        changes.append(_change("added", "Information", item, "Une nouvelle couche a été ajoutée.", "Vérifier si elle doit intégrer les compositions."))
    for layer_id in sorted(before.keys() & after.keys()):
        old, new = before[layer_id], after[layer_id]
        if old.get("source") != new.get("source"):
            changes.append(_change("source", "Élevé", new, "La source de données a changé.", "Vérifier couverture, attributs, symbologie et légendes."))
        if old.get("crs") != new.get("crs"):
            changes.append(_change("crs", "Élevé", new, "Le système de coordonnées a changé.", "Recalculer emprises, échelles et grilles."))
        data_keys = ("extent", "feature_count", "band_count", "file_size", "file_mtime_ns")
        if any(old.get(key) != new.get(key) for key in data_keys):
            changes.append(_change("data", "Moyen", new, "Le contenu ou l’emprise de la couche a changé.", "Régénérer les cartes et vérifier classes et étiquettes."))
        if old.get("renderer") != new.get("renderer"):
            changes.append(_change("style", "Moyen", new, "La symbologie de la couche a changé.", "Vérifier la légende et la cohérence de la charte."))
    previous_layouts = set(previous.get("layouts", []))
    current_layouts = set(current.get("layouts", []))
    if previous_layouts != current_layouts:
        changes.append({
            "kind": "layouts", "severity": "Moyen", "layer_id": "", "layer_name": "",
            "message": "La liste des mises en page a changé.",
            "impact": "Contrôler les exports et les recettes de production.",
        })
    changed = bool(changes) or previous.get("fingerprint") != current.get("fingerprint")
    return {
        "generated_at": _utc_now(),
        "changed": changed,
        "previous_fingerprint": previous.get("fingerprint", ""),
        "current_fingerprint": current.get("fingerprint", ""),
        "previous_captured_at": previous.get("captured_at", previous.get("created_at", "")),
        "current_captured_at": current.get("captured_at", current.get("created_at", "")),
        "changes": changes,
        "impacted_layouts": sorted(current_layouts if changes else ()),
        "status": "Modifications détectées" if changed else "À jour",
    }


def save(path: str | Path, value: dict[str, Any]) -> Path:
    return write_json(path, value)


def _layer_snapshot(layer: Any, arcpy: Any | None) -> dict[str, Any]:
    layer_id = str(getattr(layer, "URI", "") or getattr(layer, "longName", "") or getattr(layer, "name", ""))
    name = str(getattr(layer, "name", ""))
    source = ""
    try:
        source = str(layer.dataSource)
    except Exception:
        pass
    extent = [0.0, 0.0, 0.0, 0.0]
    crs = ""
    feature_count = None
    band_count = None
    if arcpy is not None and not bool(getattr(layer, "isBroken", False)):
        try:
            desc = arcpy.Describe(layer)
            crs = str(getattr(getattr(desc, "spatialReference", None), "name", "") or "")
            item = getattr(desc, "extent", None)
            if item is not None:
                extent = [float(item.XMin), float(item.YMin), float(item.XMax), float(item.YMax)]
            if bool(getattr(layer, "isFeatureLayer", False)):
                feature_count = int(arcpy.management.GetCount(layer)[0])
            if bool(getattr(layer, "isRasterLayer", False)):
                band_count = int(getattr(desc, "bandCount", 0) or 0)
        except Exception:
            pass
    renderer = ""
    try:
        symbology = layer.symbology
        renderer = type(getattr(symbology, "renderer", getattr(symbology, "colorizer", None))).__name__
    except Exception:
        pass
    file_size = file_mtime_ns = None
    try:
        if source and os.path.isfile(source):
            stat = os.stat(source)
            file_size, file_mtime_ns = stat.st_size, stat.st_mtime_ns
    except Exception:
        pass
    core = {
        "layer_id": layer_id,
        "name": name,
        "layer_type": "vector" if bool(getattr(layer, "isFeatureLayer", False)) else "raster" if bool(getattr(layer, "isRasterLayer", False)) else "other",
        "source": source,
        "crs": crs,
        "extent": extent,
        "feature_count": feature_count,
        "band_count": band_count,
        "renderer": renderer,
        "file_size": file_size,
        "file_mtime_ns": file_mtime_ns,
        "visible": bool(getattr(layer, "visible", True)),
        "broken": bool(getattr(layer, "isBroken", False)),
    }
    return {**core, "fingerprint": _fingerprint(core)}


def _change(kind: str, severity: str, item: dict[str, Any], message: str, impact: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "layer_id": item.get("layer_id", ""),
        "layer_name": item.get("name", ""),
        "message": message,
        "impact": impact,
    }


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LayerSnapshot:
    layer_id: str; name: str; layer_type: str; source: str; crs: str; extent: tuple[float, float, float, float]
    feature_count: int | None; band_count: int | None; renderer: str; file_size: int | None; file_mtime_ns: int | None; fingerprint: str


@dataclass(frozen=True)
class MapOpsSnapshot:
    schema_version: int; created_at: str; project_file: str; project_crs: str
    layers: tuple[LayerSnapshot, ...]; layouts: tuple[str, ...]; fingerprint: str
    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "created_at": self.created_at, "project_file": self.project_file, "project_crs": self.project_crs, "layers": [asdict(item) for item in self.layers], "layouts": list(self.layouts), "fingerprint": self.fingerprint}
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MapOpsSnapshot":
        if int(payload.get("schema_version", 0)) != 1: raise CartomizeError("L'instantané MapOps est incompatible.")
        return cls(1, str(payload.get("created_at", payload.get("captured_at", ""))), str(payload.get("project_file", "")), str(payload.get("project_crs", "")), tuple(LayerSnapshot(**{key: item.get(key) for key in LayerSnapshot.__dataclass_fields__}) for item in payload.get("layers", ())), tuple(str(item) for item in payload.get("layouts", ())), str(payload.get("fingerprint", "")))


@dataclass(frozen=True)
class MapOpsChange:
    kind: str; severity: str; layer_id: str; layer_name: str; message: str; impact: str


@dataclass(frozen=True)
class MapOpsReport:
    generated_at: str; previous_fingerprint: str; current_fingerprint: str
    changes: tuple[MapOpsChange, ...]; impacted_layouts: tuple[str, ...]; status: str
    def to_dict(self) -> dict[str, Any]:
        return {"generated_at": self.generated_at, "previous_fingerprint": self.previous_fingerprint, "current_fingerprint": self.current_fingerprint, "changes": [asdict(item) for item in self.changes], "impacted_layouts": list(self.impacted_layouts), "status": self.status}
    def to_text(self) -> str:
        lines = ["Suivi MapOps", f"Statut : {self.status}", f"Changements détectés : {len(self.changes)}"]
        if self.impacted_layouts: lines.append(f"Mises en page à vérifier : {', '.join(self.impacted_layouts)}")
        for item in self.changes: lines.extend(("", f"{item.severity} | {item.layer_name or 'Projet'}", item.message, f"Impact : {item.impact}"))
        return "\n".join(lines)


class MapOpsService:
    def __init__(self, project=None, *, arcpy_module=None):
        self.arcpy = arcpy_module or _import_arcpy(); self.project = project or self.arcpy.mp.ArcGISProject("CURRENT")
    def capture(self) -> MapOpsSnapshot: return MapOpsSnapshot.from_dict(snapshot(self.project, self.arcpy))
    def compare(self, previous: MapOpsSnapshot, current: MapOpsSnapshot | None = None) -> MapOpsReport:
        current = current or self.capture(); before = {item.layer_id: item for item in previous.layers}; after = {item.layer_id: item for item in current.layers}; changes = []
        for layer_id in sorted(before.keys() - after.keys()): changes.append(MapOpsChange("removed", "Élevé", layer_id, before[layer_id].name, "La couche a été retirée du projet.", "Reconstruire les cartes concernées."))
        for layer_id in sorted(after.keys() - before.keys()): changes.append(MapOpsChange("added", "Information", layer_id, after[layer_id].name, "Une nouvelle couche a été ajoutée.", "Vérifier si elle doit intégrer les compositions."))
        for layer_id in sorted(before.keys() & after.keys()):
            old, new = before[layer_id], after[layer_id]
            if old.source != new.source: changes.append(MapOpsChange("source", "Élevé", layer_id, new.name, "La source de données a changé.", "Vérifier couverture, attributs et symbologie."))
            if old.crs != new.crs: changes.append(MapOpsChange("crs", "Élevé", layer_id, new.name, "Le système de coordonnées a changé.", "Recalculer emprises, échelles et grilles."))
            if old.fingerprint != new.fingerprint and old.source == new.source and old.crs == new.crs: changes.append(MapOpsChange("data", "Moyen", layer_id, new.name, "Le contenu ou le style de la couche a changé.", "Régénérer et contrôler les cartes."))
        layouts = tuple(sorted(current.layouts if changes else ()))
        return MapOpsReport(_utc_now(), previous.fingerprint, current.fingerprint, tuple(changes), layouts, "Modifications détectées" if changes else "À jour")
    @staticmethod
    def save_snapshot(snapshot: MapOpsSnapshot, path: str | Path): return write_json(path, snapshot.to_dict())
    @staticmethod
    def load_snapshot(path: str | Path): return MapOpsSnapshot.from_dict(read_json(path))
    @staticmethod
    def save_report(report: MapOpsReport, path: str | Path): return write_json(path, report.to_dict())


class MapOpsMonitor:
    def __init__(self, service: MapOpsService, parent=None): self.service = service; self.baseline = service.capture(); self.last_report = None; self.disposed = False
    def schedule(self, *_args): return None if self.disposed else self.check_now()
    def check_now(self):
        if self.disposed: return None
        self.last_report = self.service.compare(self.baseline); return self.last_report
    def accept_current(self): self.baseline = self.service.capture(); return self.baseline
    def dispose(self): self.disposed = True


def _import_arcpy():
    try:
        import arcpy; return arcpy
    except ImportError as exc: raise RuntimeError("ArcPy est requis pour MapOps.") from exc
