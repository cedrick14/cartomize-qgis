"""MapOps local : suivi des changements de données, styles et mises en page."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from .errors import CartomizeError


@dataclass(frozen=True)
class LayerSnapshot:
    layer_id: str
    name: str
    layer_type: str
    source: str
    crs: str
    extent: tuple[float, float, float, float]
    feature_count: int | None
    band_count: int | None
    renderer: str
    file_size: int | None
    file_mtime_ns: int | None
    fingerprint: str


@dataclass(frozen=True)
class MapOpsSnapshot:
    schema_version: int
    created_at: str
    project_file: str
    project_crs: str
    layers: tuple[LayerSnapshot, ...]
    layouts: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "project_file": self.project_file,
            "project_crs": self.project_crs,
            "layers": [asdict(item) for item in self.layers],
            "layouts": list(self.layouts),
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MapOpsSnapshot":
        if int(payload.get("schema_version", 0)) != 1:
            raise CartomizeError("L’instantané MapOps est incompatible.")
        layers = tuple(LayerSnapshot(**item) for item in payload.get("layers", []))
        return cls(
            1,
            str(payload.get("created_at", "")),
            str(payload.get("project_file", "")),
            str(payload.get("project_crs", "")),
            layers,
            tuple(str(item) for item in payload.get("layouts", [])),
            str(payload.get("fingerprint", "")),
        )


@dataclass(frozen=True)
class MapOpsChange:
    kind: str
    severity: str
    layer_id: str
    layer_name: str
    message: str
    impact: str


@dataclass(frozen=True)
class MapOpsReport:
    generated_at: str
    previous_fingerprint: str
    current_fingerprint: str
    changes: tuple[MapOpsChange, ...]
    impacted_layouts: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "previous_fingerprint": self.previous_fingerprint,
            "current_fingerprint": self.current_fingerprint,
            "changes": [asdict(item) for item in self.changes],
            "impacted_layouts": list(self.impacted_layouts),
            "status": self.status,
        }

    def to_text(self) -> str:
        lines = [
            "Suivi MapOps",
            f"Statut : {self.status}",
            f"Changements détectés : {len(self.changes)}",
        ]
        if self.impacted_layouts:
            lines.append(f"Mises en page à vérifier : {', '.join(self.impacted_layouts)}")
        for item in self.changes:
            lines.extend(("", f"{item.severity} | {item.layer_name or 'Projet'}", item.message, f"Impact : {item.impact}"))
        return "\n".join(lines)


class MapOpsService:
    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()

    def capture(self) -> MapOpsSnapshot:
        layers = tuple(self._layer_snapshot(layer) for layer in self.project.mapLayers().values() if layer)
        layouts = tuple(sorted(layout.name() for layout in self.project.layoutManager().printLayouts()))
        core = {
            "project_file": self.project.fileName() or "",
            "project_crs": self.project.crs().authid() or self.project.crs().description() or "",
            "layers": [asdict(item) for item in sorted(layers, key=lambda item: item.layer_id)],
            "layouts": list(layouts),
        }
        fingerprint = _fingerprint(core)
        return MapOpsSnapshot(
            1,
            datetime.now(timezone.utc).isoformat(),
            core["project_file"],
            core["project_crs"],
            layers,
            layouts,
            fingerprint,
        )

    def compare(self, previous: MapOpsSnapshot, current: MapOpsSnapshot | None = None) -> MapOpsReport:
        current = current or self.capture()
        before = {item.layer_id: item for item in previous.layers}
        after = {item.layer_id: item for item in current.layers}
        changes: list[MapOpsChange] = []

        for layer_id in sorted(before.keys() - after.keys()):
            item = before[layer_id]
            changes.append(MapOpsChange("removed", "Élevé", layer_id, item.name, "La couche a été retirée du projet.", "Les cartes et recettes qui utilisent cette couche doivent être reconstruites."))
        for layer_id in sorted(after.keys() - before.keys()):
            item = after[layer_id]
            changes.append(MapOpsChange("added", "Information", layer_id, item.name, "Une nouvelle couche a été ajoutée.", "Cartomize peut proposer de l’intégrer aux compositions concernées."))
        for layer_id in sorted(before.keys() & after.keys()):
            old, new = before[layer_id], after[layer_id]
            if old.source != new.source:
                changes.append(MapOpsChange("source", "Élevé", layer_id, new.name, "La source de données a changé.", "Vérifier la couverture, les attributs, la symbologie et les légendes."))
            if old.crs != new.crs:
                changes.append(MapOpsChange("crs", "Élevé", layer_id, new.name, f"Le CRS est passé de {old.crs or 'non défini'} à {new.crs or 'non défini'}.", "Recalculer les emprises, les échelles et les grilles."))
            if old.extent != new.extent or old.feature_count != new.feature_count or old.file_size != new.file_size or old.file_mtime_ns != new.file_mtime_ns:
                changes.append(MapOpsChange("data", "Moyen", layer_id, new.name, "Le contenu ou l’emprise de la couche a changé.", "Régénérer les cartes et vérifier les statistiques, classes et étiquettes."))
            if old.renderer != new.renderer:
                changes.append(MapOpsChange("style", "Moyen", layer_id, new.name, "La symbologie de la couche a changé.", "Actualiser les légendes et contrôler la hiérarchie visuelle."))
            if old.name != new.name:
                changes.append(MapOpsChange("renamed", "Faible", layer_id, new.name, f"La couche a été renommée depuis « {old.name} ».", "Mettre à jour les recettes qui reposent sur le nom de la couche."))

        layouts_changed = previous.layouts != current.layouts
        if layouts_changed:
            changes.append(MapOpsChange("layouts", "Information", "", "", "La liste des mises en page a changé.", "Vérifier les exports et les recettes de production."))
        impacted = self._impacted_layouts(changes) if changes else ()
        severity = {item.severity for item in changes}
        status = "Action requise" if "Élevé" in severity else "À vérifier" if changes else "À jour"
        return MapOpsReport(
            datetime.now(timezone.utc).isoformat(),
            previous.fingerprint,
            current.fingerprint,
            tuple(changes),
            impacted,
            status,
        )

    def _impacted_layouts(self, changes: list[MapOpsChange]) -> tuple[str, ...]:
        changed_ids = {change.layer_id for change in changes if change.layer_id}
        layout_level_change = any(change.kind == "layouts" for change in changes)
        impacted: list[str] = []
        try:
            layouts = list(self.project.layoutManager().printLayouts())
        except Exception:
            layouts = []
        for layout in layouts:
            if layout_level_change:
                impacted.append(layout.name())
                continue
            raw = layout.customProperty("cartomize/layer_ids", [])
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    raw = parsed if isinstance(parsed, list) else [raw]
                except Exception:
                    raw = [item.strip() for item in raw.split(",") if item.strip()]
            try:
                layout_ids = {str(item) for item in raw}
            except Exception:
                layout_ids = set()
            main_id = str(layout.customProperty("cartomize/main_layer_id", "") or "")
            if main_id:
                layout_ids.add(main_id)
            if not layout_ids or changed_ids.intersection(layout_ids):
                impacted.append(layout.name())
        return tuple(sorted(dict.fromkeys(impacted)))

    def save_snapshot(self, snapshot: MapOpsSnapshot, path: str | Path) -> Path:
        return _atomic_json(path, snapshot.to_dict())

    def load_snapshot(self, path: str | Path) -> MapOpsSnapshot:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return MapOpsSnapshot.from_dict(payload)

    def save_report(self, report: MapOpsReport, path: str | Path) -> Path:
        return _atomic_json(path, report.to_dict())

    def _layer_snapshot(self, layer) -> LayerSnapshot:
        source = str(layer.source() or "")
        file_path = Path(source.split("|", 1)[0]) if source and "://" not in source else None
        size = mtime = None
        if file_path is not None and file_path.is_file():
            try:
                stat = file_path.stat()
                size, mtime = stat.st_size, stat.st_mtime_ns
            except OSError:
                pass
        try:
            extent = layer.extent()
            extent_tuple = (float(extent.xMinimum()), float(extent.yMinimum()), float(extent.xMaximum()), float(extent.yMaximum()))
        except Exception:
            extent_tuple = (0.0, 0.0, 0.0, 0.0)
        feature_count = int(layer.featureCount()) if isinstance(layer, QgsVectorLayer) else None
        band_count = int(layer.bandCount()) if isinstance(layer, QgsRasterLayer) else None
        renderer = ""
        try:
            renderer_obj = layer.renderer()
            renderer = renderer_obj.dump() if hasattr(renderer_obj, "dump") else renderer_obj.type()
        except Exception:
            pass
        core = {
            "id": layer.id(), "name": layer.name(), "source": source,
            "crs": layer.crs().authid() or layer.crs().description() or "",
            "extent": extent_tuple, "feature_count": feature_count,
            "band_count": band_count, "renderer": renderer,
            "file_size": size, "file_mtime_ns": mtime,
        }
        return LayerSnapshot(
            layer.id(), layer.name(),
            "vector" if isinstance(layer, QgsVectorLayer) else "raster" if isinstance(layer, QgsRasterLayer) else "other",
            source, core["crs"], extent_tuple, feature_count, band_count, renderer, size, mtime,
            _fingerprint(core),
        )


class MapOpsMonitor(QObject):
    changesDetected = pyqtSignal(object)

    def __init__(self, service: MapOpsService, parent=None):
        super().__init__(parent)
        self.service = service
        self.baseline = service.capture()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.check_now)
        project = service.project
        self._layer_connections: list[tuple[Any, Any]] = []
        self._project_connections: list[tuple[Any, Any]] = []
        layers_added = getattr(project, "layersAdded", None)
        if layers_added is not None:
            try:
                layers_added.connect(self._layers_added)
                self._project_connections.append((layers_added, self._layers_added))
            except Exception:
                pass
        for signal_name in ("layersRemoved", "readProject", "cleared"):
            signal = getattr(project, signal_name, None)
            if signal is not None:
                try:
                    signal.connect(self.schedule)
                    self._project_connections.append((signal, self.schedule))
                except Exception:
                    pass
        self._connect_layers(project.mapLayers().values())

    def _layers_added(self, layers) -> None:
        self._connect_layers(layers or [])
        self.schedule()

    def _connect_layers(self, layers) -> None:
        for layer in layers:
            for signal_name in ("styleChanged", "dataChanged", "repaintRequested", "nameChanged", "crsChanged"):
                signal = getattr(layer, signal_name, None)
                if signal is None:
                    continue
                try:
                    signal.connect(self.schedule)
                    self._layer_connections.append((signal, self.schedule))
                except Exception:
                    pass

    def schedule(self, *_args) -> None:
        self.timer.start()

    def check_now(self) -> MapOpsReport:
        current = self.service.capture()
        report = self.service.compare(self.baseline, current)
        if report.changes:
            self.changesDetected.emit(report)
        return report

    def accept_current(self) -> None:
        self.baseline = self.service.capture()

    def dispose(self) -> None:
        try:
            self.timer.stop()
        except Exception:
            pass
        for signal, slot in self._layer_connections:
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._layer_connections.clear()
        for signal, slot in self._project_connections:
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._project_connections.clear()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _atomic_json(path: str | Path, payload: dict[str, Any]) -> Path:
    destination = Path(path).expanduser().resolve(strict=False)
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise CartomizeError("La destination MapOps ne peut pas être un lien symbolique.")
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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
