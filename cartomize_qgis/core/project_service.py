"""Accès unique au projet QGIS et aux couches réellement chargées."""
from __future__ import annotations
import logging
import math

from dataclasses import dataclass
from typing import Iterable

from qgis.core import (
    QgsCoordinateTransform,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)

from .extent_policy import extent_factor_for_role, is_remote_basemap
from .layer_stack import LayerDescriptor, LayerStackPlan, plan_layer_stacks


@dataclass(frozen=True)
class ProjectSummary:
    layer_count: int
    visible_count: int
    vector_count: int
    raster_count: int
    invalid_count: int
    project_crs: str
    extent_text: str


@dataclass(frozen=True)
class ContextBasemap:
    """Fond XYZ proposé comme contexte, jamais comme donnée thématique."""

    key: str
    label: str
    url: str
    max_zoom: int
    attribution: str


CONTEXT_BASEMAPS: tuple[ContextBasemap, ...] = (
    ContextBasemap(
        "osm",
        "OpenStreetMap",
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        19,
        "© OpenStreetMap contributors",
    ),
    ContextBasemap(
        "terrain",
        "Terrain (OpenTopoMap)",
        "https://tile.opentopomap.org/{z}/{x}/{y}.png",
        17,
        "© OpenStreetMap contributors, SRTM | OpenTopoMap",
    ),
    ContextBasemap(
        "satellite",
        "Imagerie satellitaire",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        19,
        "Sources: Esri, Maxar, Earthstar Geographics and contributors",
    ),
)


class ProjectService:
    """Maintient une seule vérité : les objets du QgsProject courant."""

    def __init__(self, iface, project: QgsProject | None = None):
        self.iface = iface
        self.project = project or QgsProject.instance()

    def ordered_layers(self, visible_only: bool = False) -> list[QgsMapLayer]:
        layers: list[QgsMapLayer] = []
        root = self.project.layerTreeRoot()
        for node in root.findLayers():
            layer = node.layer()
            if layer is None:
                continue
            if visible_only and not node.isVisible():
                continue
            layers.append(layer)
        return layers

    def visible_layers(self) -> list[QgsMapLayer]:
        """Retourne l'état visible courant, sans conserver le cache du canevas.

        Sous QGIS, le canevas peut encore exposer pendant un court instant la
        pile précédente après une activation, une désactivation ou l'ajout
        d'un fond XYZ. L'arbre des couches est donc l'autorité de visibilité ;
        le canevas ne sert qu'à préserver son ordre de rendu courant.
        """

        tree_layers = [
            layer for layer in self.ordered_layers(True)
            if layer is not None and layer.isValid()
        ]
        visible_ids = {layer.id() for layer in tree_layers}
        try:
            canvas_layers = [
                layer for layer in self.iface.mapCanvas().layers()
                if layer is not None
                and layer.isValid()
                and layer.id() in visible_ids
            ]
        except Exception:
            canvas_layers = []
        result: list[QgsMapLayer] = []
        seen: set[str] = set()
        for layer in (*canvas_layers, *tree_layers):
            if layer.id() in seen:
                continue
            seen.add(layer.id())
            result.append(layer)
        return result

    def layout_ordered_layers(self) -> list[QgsMapLayer]:
        """Retourne l'ordre de rendu réel, complété par les couches masquées.

        ``QgsMapCanvas.layers()`` reflète notamment un thème cartographique
        actif. Les couches non visibles sont ensuite ajoutées dans l'ordre de
        l'arbre afin qu'une sélection explicite reste résoluble.
        """

        result: list[QgsMapLayer] = []
        seen: set[str] = set()
        try:
            candidates = list(self.iface.mapCanvas().layers())
        except Exception:
            candidates = []
        candidates.extend(self.ordered_layers())
        for layer in candidates:
            if layer is None or not layer.isValid() or layer.id() in seen:
                continue
            seen.add(layer.id())
            result.append(layer)
        return result

    def layout_layer_plan(
        self,
        *,
        selected_ids: Iterable[str] = (),
        focus_id: str = "",
        include_visible_context: bool = True,
        background_mode: str = "automatic",
        background_layer_id: str = "",
        locator_mode: str = "automatic",
    ) -> LayerStackPlan:
        """Planifie les piles de couches principale et de situation."""

        ordered = self.layout_ordered_layers()
        visible_ids = tuple(layer.id() for layer in self.visible_layers())
        descriptors = tuple(
            LayerDescriptor(
                layer_id=layer.id(),
                kind=(
                    "vector"
                    if isinstance(layer, QgsVectorLayer)
                    else "raster"
                    if isinstance(layer, QgsRasterLayer)
                    else "other"
                ),
                basemap=self.is_basemap_layer(layer),
            )
            for layer in ordered
        )
        return plan_layer_stacks(
            descriptors,
            selected_ids=selected_ids,
            visible_ids=visible_ids,
            focus_id=focus_id,
            include_visible_context=include_visible_context,
            background_mode=background_mode,
            background_layer_id=background_layer_id,
            locator_mode=locator_mode,
        )

    def layers_from_ids(self, layer_ids: Iterable[str]) -> list[QgsMapLayer]:
        """Résout des identifiants tout en conservant l'ordre demandé."""

        result: list[QgsMapLayer] = []
        for layer_id in layer_ids:
            layer = self.project.mapLayer(layer_id)
            if layer is not None and layer.isValid():
                result.append(layer)
        return result

    def background_candidates(self) -> list[QgsMapLayer]:
        """Couches pouvant être choisies explicitement comme arrière-plan."""

        layers = self.layout_ordered_layers()
        remote = [layer for layer in layers if self.is_basemap_layer(layer)]
        local_rasters = [
            layer
            for layer in layers
            if isinstance(layer, QgsRasterLayer) and not self.is_basemap_layer(layer)
        ]
        return remote + local_rasters

    @staticmethod
    def context_basemap_definitions() -> tuple[ContextBasemap, ...]:
        return CONTEXT_BASEMAPS

    def active_context_basemap_key(self) -> str:
        value, _ok = self.project.readEntry(
            "Cartomize", "context_basemap_key", ""
        )
        return str(value or "")

    def active_context_opacity_percent(self) -> int:
        value, _ok = self.project.readEntry(
            "Cartomize", "context_basemap_opacity", "1.0"
        )
        try:
            return round(max(0.0, min(1.0, float(value))) * 100)
        except (TypeError, ValueError):
            return 100

    def activate_context_basemap(self, key: str) -> QgsMapLayer:
        """Ajoute ou remplace le fond Cartomize et l'affiche sous les données.

        Le remplacement est transactionnel : un fond existant n'est retiré
        qu'après validation et ajout du nouveau fournisseur XYZ.
        """

        definition = next(
            (item for item in CONTEXT_BASEMAPS if item.key == str(key or "")),
            None,
        )
        if definition is None:
            raise ValueError("Le contexte cartographique demandé est inconnu.")

        managed = self._managed_context_layers()
        existing = next(
            (
                layer for layer in managed
                if str(
                    layer.customProperty("cartomize/context_basemap_key", "")
                ) == definition.key
            ),
            None,
        )
        if existing is None:
            source = (
                "type=xyz"
                f"&url={definition.url}"
                "&zmin=0"
                f"&zmax={definition.max_zoom}"
            )
            existing = QgsRasterLayer(source, definition.label, "wms")
            if not existing.isValid():
                raise ValueError(
                    f"QGIS n'a pas pu charger {definition.label}."
                )
            existing.setCustomProperty(
                "cartomize/context_basemap_key", definition.key
            )
            existing.setCustomProperty(
                "cartomize/context_role", "background"
            )
            existing.setCustomProperty(
                "cartomize/context_attribution", definition.attribution
            )
            # Ajout sans insertion automatique : addLayer l'ajoute à la fin du
            # groupe racine, donc sous les couches thématiques dans QGIS.
            self.project.addMapLayer(existing, False)
            self.project.layerTreeRoot().addLayer(existing)

        # Ne retirer les anciens contextes qu'une fois le fond demandé valide et
        # enregistré. Une panne réseau/provider ne peut ainsi plus vider le
        # contexte cartographique courant.
        for layer in managed:
            if layer.id() != existing.id():
                self.project.removeMapLayer(layer.id())

        node = self.project.layerTreeRoot().findLayer(existing.id())
        if node is None:
            # Répare aussi les projets touchés par l'ancien nettoyage de
            # légende : la couche pouvait rester enregistrée sans nœud visible.
            node = self.project.layerTreeRoot().addLayer(existing)
        if node is not None:
            node.setItemVisibilityChecked(True)
        self.project.writeEntry(
            "Cartomize", "context_basemap_key", definition.key
        )
        self.project.writeEntry(
            "Cartomize", "context_basemap_layer_id", existing.id()
        )
        self.project.setDirty(True)
        try:
            self.iface.mapCanvas().refresh()
        except Exception:
            logging.getLogger(__name__).debug(
                "Rafraîchissement du canevas indisponible", exc_info=True
            )
        return existing

    def clear_managed_context_basemap(self) -> None:
        """Retire uniquement le fond créé par Cartomize."""

        for layer in self._managed_context_layers():
            self.project.removeMapLayer(layer.id())
        self.project.writeEntry("Cartomize", "context_basemap_key", "")
        self.project.writeEntry("Cartomize", "context_basemap_layer_id", "")
        self.project.setDirty(True)
        try:
            self.iface.mapCanvas().refresh()
        except Exception:
            logging.getLogger(__name__).debug(
                "Rafraîchissement du canevas indisponible", exc_info=True
            )

    def set_context_layer_opacity(
        self,
        layer_id: str,
        percent: int | float,
    ) -> None:
        """Applique une opacité au contexte sans toucher aux données métier."""

        layer = self.project.mapLayer(str(layer_id or ""))
        if layer is None or not layer.isValid():
            return
        opacity = max(0.0, min(1.0, float(percent) / 100.0))
        applied = False
        setter = getattr(layer, "setOpacity", None)
        if callable(setter):
            try:
                setter(opacity)
                applied = True
            except (TypeError, RuntimeError):
                pass
        if not applied:
            renderer = getattr(layer, "renderer", lambda: None)()
            setter = getattr(renderer, "setOpacity", None)
            if callable(setter):
                setter(opacity)
        layer.setCustomProperty("cartomize/context_opacity", opacity)
        self.project.writeEntry(
            "Cartomize", "context_basemap_opacity", str(opacity)
        )
        try:
            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
        except Exception:
            logging.getLogger(__name__).debug(
                "Rafraîchissement du contexte indisponible", exc_info=True
            )
        self.project.setDirty(True)

    def _managed_context_layers(self) -> list[QgsMapLayer]:
        return [
            layer for layer in self.project.mapLayers().values()
            if layer is not None
            and str(
                layer.customProperty("cartomize/context_role", "")
            ) == "background"
        ]

    def canvas_style_overrides(
        self,
        layers: Iterable[QgsMapLayer],
    ) -> dict[str, str]:
        """Copie les variantes de style du canevas ou du thème courant."""

        try:
            raw = dict(self.iface.mapCanvas().layerStyleOverrides())
        except Exception:
            return {}
        allowed = {layer.id() for layer in layers if layer is not None}
        return {
            str(layer_id): str(style)
            for layer_id, style in raw.items()
            if layer_id in allowed and style
        }

    def active_layer(self) -> QgsMapLayer | None:
        layer = self.iface.activeLayer()
        return layer if layer and layer.isValid() else None

    @staticmethod
    def is_basemap_layer(layer: QgsMapLayer | None) -> bool:
        """Identifie un fond web sans dépendre de son emprise mondiale."""

        if layer is None:
            return False
        try:
            return is_remote_basemap(layer.providerType(), layer.source(), layer.name())
        except Exception:
            logging.getLogger(__name__).debug(
                "Impossible d'identifier le rôle de la couche", exc_info=True
            )
            return False

    def focus_layer(
        self,
        layers: Iterable[QgsMapLayer],
        main_layer_id: str = "",
    ) -> QgsMapLayer | None:
        """Choisit la couche qui décide du cadrage, jamais le fond web par défaut."""

        layer_list = [layer for layer in layers if layer and layer.isValid()]
        thematic_layers = [
            layer for layer in layer_list if not self.is_basemap_layer(layer)
        ]
        if main_layer_id:
            explicit = next(
                (layer for layer in layer_list if layer.id() == main_layer_id),
                None,
            )
            if explicit is not None and (
                not self.is_basemap_layer(explicit) or not thematic_layers
            ):
                return explicit
        active = self.active_layer()
        if (
            active is not None
            and any(active.id() == layer.id() for layer in layer_list)
            and (not self.is_basemap_layer(active) or not thematic_layers)
        ):
            return active
        return thematic_layers[0] if thematic_layers else (
            layer_list[0] if layer_list else None
        )

    def active_vector_layer(self) -> QgsVectorLayer | None:
        active = self.active_layer()
        if isinstance(active, QgsVectorLayer):
            return active
        return next((layer for layer in self.visible_layers() if isinstance(layer, QgsVectorLayer)), None)

    def layer_by_id(self, layer_id: str) -> QgsMapLayer | None:
        return self.project.mapLayer(layer_id)

    def display_crs(self, layers: Iterable[QgsMapLayer] | None = None):
        """Retourne un CRS de rendu valide sans mélanger des emprises incompatibles."""
        project_crs = self.project.crs()
        if project_crs.isValid():
            return project_crs
        try:
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            if canvas_crs.isValid():
                return canvas_crs
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        for layer in list(layers or self.ordered_layers()):
            if layer and layer.isValid() and layer.crs().isValid():
                return layer.crs()
        return project_crs

    def combined_extent(
        self,
        layers: Iterable[QgsMapLayer],
        *,
        target_crs=None,
        margin_ratio: float = 0.0,
    ) -> QgsRectangle | None:
        layer_list = list(layers)
        target_crs = target_crs or self.display_crs(layer_list)
        result: QgsRectangle | None = None
        for layer in layer_list:
            if not layer or not layer.isValid():
                continue
            candidate = QgsRectangle(layer.extent())
            if candidate.isNull() or candidate.isEmpty():
                continue
            try:
                if layer.crs().isValid() and target_crs.isValid() and layer.crs() != target_crs:
                    transform = QgsCoordinateTransform(layer.crs(), target_crs, self.project)
                    candidate = transform.transformBoundingBox(candidate)
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
                continue
            if result is None:
                result = QgsRectangle(candidate)
            else:
                result.combineExtentWith(candidate)
        if result and not result.isEmpty() and margin_ratio > 0:
            result = _expanded(result, margin_ratio)
        return result

    def layer_extent(
        self,
        layer: QgsMapLayer | None,
        *,
        target_crs=None,
        margin_ratio: float = 0.0,
    ) -> QgsRectangle | None:
        """Emprise d'une couche transformée dans le CRS de rendu du projet."""

        if layer is None or not layer.isValid():
            return None
        target_crs = target_crs or self.display_crs([layer])
        candidate = QgsRectangle(layer.extent())
        if candidate.isNull() or candidate.isEmpty():
            return None
        if not layer.crs().isValid():
            return None
        try:
            if target_crs.isValid() and layer.crs() != target_crs:
                transform = QgsCoordinateTransform(layer.crs(), target_crs, self.project)
                candidate = transform.transformBoundingBox(candidate)
        except Exception:
            logging.getLogger(__name__).warning(
                "Transformation d'emprise impossible pour %s",
                layer.name(),
                exc_info=True,
            )
            return None
        if candidate.isNull() or candidate.isEmpty() or not _finite_rectangle(candidate):
            return None
        return _expanded(candidate, margin_ratio) if margin_ratio > 0 else candidate

    def map_extent(
        self,
        layers: Iterable[QgsMapLayer],
        *,
        main_layer_id: str = "",
        target_crs=None,
        margin_ratio: float = 0.03,
    ) -> tuple[QgsRectangle, QgsMapLayer | None]:
        """Calcule l'emprise thématique sans laisser un fond mondial l'écraser."""

        layer_list = [layer for layer in layers if layer and layer.isValid()]
        target_crs = target_crs or self.display_crs(layer_list)
        focus = self.focus_layer(layer_list, main_layer_id)
        if focus is not None and not self.is_basemap_layer(focus):
            extent = self.layer_extent(
                focus,
                target_crs=target_crs,
                margin_ratio=margin_ratio,
            )
            if extent is not None:
                return extent, focus

        # Si le projet ne contient qu'un fond web, le cadrage courant du canevas
        # est la seule emprise locale pertinente.
        canvas_extent = self._canvas_extent(target_crs)
        if canvas_extent is not None:
            return _expanded(canvas_extent, margin_ratio), focus

        operational = [layer for layer in layer_list if not self.is_basemap_layer(layer)]
        combined = self.combined_extent(
            operational,
            target_crs=target_crs,
            margin_ratio=margin_ratio,
        )
        if combined is not None and not combined.isEmpty():
            return combined, focus
        return self.preferred_extent(
            operational or layer_list,
            margin_ratio,
            target_crs=target_crs,
        ), focus

    def extent_for_role(
        self,
        main_extent: QgsRectangle,
        role: str,
        *,
        target_crs=None,
    ) -> QgsRectangle:
        """Déduit les cartes de situation de l'emprise principale, pas du fond OSM."""

        factor = extent_factor_for_role(role)
        if factor <= 1.0:
            return QgsRectangle(main_extent)
        result = _scaled(main_extent, factor)
        if target_crs is not None and target_crs.isValid() and target_crs.isGeographic():
            result = QgsRectangle(
                max(-180.0, result.xMinimum()),
                max(-90.0, result.yMinimum()),
                min(180.0, result.xMaximum()),
                min(90.0, result.yMaximum()),
            )
        return result

    def _canvas_extent(self, target_crs) -> QgsRectangle | None:
        try:
            canvas = self.iface.mapCanvas()
            extent = QgsRectangle(canvas.extent())
            if extent.isNull() or extent.isEmpty():
                return None
            canvas_crs = canvas.mapSettings().destinationCrs()
            if canvas_crs.isValid() and target_crs.isValid() and canvas_crs != target_crs:
                transform = QgsCoordinateTransform(canvas_crs, target_crs, self.project)
                extent = transform.transformBoundingBox(extent)
            return extent if _finite_rectangle(extent) else None
        except Exception:
            logging.getLogger(__name__).debug(
                "Emprise du canevas indisponible", exc_info=True
            )
            return None

    def preferred_extent(
        self,
        layers: Iterable[QgsMapLayer],
        margin_ratio: float = 0.03,
        *,
        target_crs=None,
    ) -> QgsRectangle:
        layer_list = list(layers)
        target_crs = target_crs or self.display_crs(layer_list)
        canvas = self.iface.mapCanvas()
        canvas_extent = QgsRectangle(canvas.extent())
        if not canvas_extent.isNull() and not canvas_extent.isEmpty():
            try:
                canvas_crs = canvas.mapSettings().destinationCrs()
                if canvas_crs.isValid() and target_crs.isValid() and canvas_crs != target_crs:
                    transform = QgsCoordinateTransform(canvas_crs, target_crs, self.project)
                    canvas_extent = transform.transformBoundingBox(canvas_extent)
                return _expanded(canvas_extent, margin_ratio)
            except Exception:
                logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        combined = self.combined_extent(layer_list, target_crs=target_crs, margin_ratio=margin_ratio)
        if combined and not combined.isEmpty():
            return combined
        if target_crs.isValid() and target_crs.isGeographic():
            return QgsRectangle(-180.0, -90.0, 180.0, 90.0)
        return QgsRectangle(0.0, 0.0, 1_000_000.0, 1_000_000.0)

    def project_extent(self, margin_ratio: float = 0.08, *, target_crs=None) -> QgsRectangle:
        layers = self.ordered_layers()
        target_crs = target_crs or self.display_crs(layers)
        combined = self.combined_extent(layers, target_crs=target_crs, margin_ratio=margin_ratio)
        if combined and not combined.isEmpty():
            return combined
        return self.preferred_extent(self.visible_layers(), margin_ratio, target_crs=target_crs)

    def zoom_to_layer(self, layer: QgsMapLayer) -> None:
        if not layer or not layer.isValid():
            return
        canvas = self.iface.mapCanvas()
        extent = self.combined_extent([layer], target_crs=canvas.mapSettings().destinationCrs(), margin_ratio=0.03)
        if extent and not extent.isEmpty():
            canvas.setExtent(extent)
            canvas.refresh()

    def summary(self) -> ProjectSummary:
        layers = self.ordered_layers()
        visible = self.visible_layers()
        vectors = sum(isinstance(layer, QgsVectorLayer) for layer in layers)
        rasters = sum(isinstance(layer, QgsRasterLayer) for layer in layers)
        invalid = sum(not layer.isValid() for layer in layers)
        extent = self.combined_extent(layers)
        extent_text = "Non disponible"
        if extent and not extent.isEmpty():
            extent_text = (
                f"{extent.xMinimum():.3f}, {extent.yMinimum():.3f} à "
                f"{extent.xMaximum():.3f}, {extent.yMaximum():.3f}"
            )
        crs = self.project.crs()
        return ProjectSummary(
            layer_count=len(layers),
            visible_count=len(visible),
            vector_count=vectors,
            raster_count=rasters,
            invalid_count=invalid,
            project_crs=crs.authid() or crs.description() or "Non défini",
            extent_text=extent_text,
        )


def _expanded(rect: QgsRectangle, ratio: float) -> QgsRectangle:
    result = QgsRectangle(rect)
    dx = max(abs(result.width()) * ratio, 1e-9)
    dy = max(abs(result.height()) * ratio, 1e-9)
    result.grow(max(dx, dy))
    return result


def _scaled(rect: QgsRectangle, factor: float) -> QgsRectangle:
    result = QgsRectangle(rect)
    center = result.center()
    half_width = max(abs(result.width()) * float(factor) / 2.0, 1e-9)
    half_height = max(abs(result.height()) * float(factor) / 2.0, 1e-9)
    return QgsRectangle(
        center.x() - half_width,
        center.y() - half_height,
        center.x() + half_width,
        center.y() + half_height,
    )


def _finite_rectangle(rect: QgsRectangle) -> bool:
    return all(
        math.isfinite(float(value))
        for value in (
            rect.xMinimum(),
            rect.yMinimum(),
            rect.xMaximum(),
            rect.yMaximum(),
        )
    )
