"""Planification pure des piles de couches des cadres cartographiques.

Le module ne dépend pas de PyQGIS afin que les règles de superposition puissent
être testées dans l'intégration continue et hors d'une session QGIS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LayerDescriptor:
    """Description minimale d'une couche, dans l'ordre de rendu QGIS."""

    layer_id: str
    kind: str
    basemap: bool = False


@dataclass(frozen=True)
class LayerStackPlan:
    """Listes ordonnées, de la couche supérieure vers la couche inférieure."""

    main_ids: tuple[str, ...]
    locator_ids: tuple[str, ...]
    background_ids: tuple[str, ...]


def plan_layer_stacks(
    ordered_layers: Iterable[LayerDescriptor],
    *,
    selected_ids: Iterable[str] = (),
    visible_ids: Iterable[str] = (),
    focus_id: str = "",
    include_visible_context: bool = True,
    background_mode: str = "automatic",
    background_layer_id: str = "",
    locator_mode: str = "automatic",
) -> LayerStackPlan:
    """Construit les piles principale et de situation.

    ``ordered_layers`` suit l'ordre de rendu de QGIS : l'index 0 est au-dessus.
    Une sélection issue d'un ancien plan d'automatisation est complétée par les
    couches actuellement visibles. Ainsi, un fond ajouté après l'analyse n'est
    pas perdu au moment de créer la mise en page.
    """

    descriptors = _unique_descriptors(ordered_layers)
    by_id = {item.layer_id: item for item in descriptors}
    ordered_ids = tuple(item.layer_id for item in descriptors)
    selected = {layer_id for layer_id in selected_ids if layer_id in by_id}
    visible = {layer_id for layer_id in visible_ids if layer_id in by_id}

    if selected:
        included = set(selected)
        if include_visible_context:
            included.update(visible)
    elif visible:
        included = set(visible)
    else:
        included = set(ordered_ids)

    if focus_id in by_id:
        included.add(focus_id)

    background_mode = _choice(
        background_mode,
        allowed={"automatic", "none", "layer"},
        fallback="automatic",
    )
    explicit_background = (
        background_layer_id
        if background_mode == "layer" and background_layer_id in by_id
        else ""
    )

    if background_mode == "none":
        included = {
            layer_id for layer_id in included if not by_id[layer_id].basemap
        }
    elif explicit_background:
        included = {
            layer_id for layer_id in included if not by_id[layer_id].basemap
        }
        included.add(explicit_background)

    main_ids = _ordered_subset(ordered_ids, included)
    detected_backgrounds = {
        layer_id
        for layer_id in main_ids
        if by_id[layer_id].basemap
    }
    if explicit_background:
        main_ids = _move_to_bottom(main_ids, {explicit_background})
    elif background_mode == "automatic" and detected_backgrounds:
        # Un fond ajouté par QuickMapServices peut être placé n'importe où
        # dans l'arbre. Le cadre doit toutefois toujours le dessiner sous les
        # couches thématiques.
        main_ids = _move_to_bottom(main_ids, detected_backgrounds)
    if not main_ids and focus_id in by_id:
        main_ids = (focus_id,)
    if not main_ids and ordered_ids:
        main_ids = (ordered_ids[0],)

    if explicit_background:
        background_ids = (explicit_background,)
    elif background_mode == "none":
        background_ids = ()
    else:
        background_ids = tuple(
            layer_id for layer_id in main_ids if by_id[layer_id].basemap
        )

    locator_mode = _choice(
        locator_mode,
        allowed={"automatic", "main", "background"},
        fallback="automatic",
    )
    if locator_mode == "main":
        locator_ids = main_ids
    else:
        locator_set = set(background_ids)
        if locator_mode == "automatic":
            # Les limites et repères vectoriels restent utiles dans une carte de
            # situation. Les rasters thématiques opaques sont exclus afin de ne
            # pas masquer le fond ni l'indicateur d'emprise.
            locator_set.update(
                layer_id
                for layer_id in main_ids
                if by_id[layer_id].kind == "vector"
            )
        if not locator_set:
            locator_set.update(
                layer_id
                for layer_id in main_ids
                if by_id[layer_id].kind == "vector"
            )
        if not locator_set:
            locator_ids = main_ids
        else:
            locator_ids = _ordered_subset(ordered_ids, locator_set)
            locator_ids = _move_to_bottom(locator_ids, set(background_ids))

    return LayerStackPlan(
        main_ids=tuple(main_ids),
        locator_ids=tuple(locator_ids),
        background_ids=tuple(background_ids),
    )


def _unique_descriptors(
    layers: Iterable[LayerDescriptor],
) -> tuple[LayerDescriptor, ...]:
    seen: set[str] = set()
    result: list[LayerDescriptor] = []
    for item in layers:
        layer_id = str(item.layer_id or "")
        if not layer_id or layer_id in seen:
            continue
        seen.add(layer_id)
        result.append(item)
    return tuple(result)


def _ordered_subset(
    ordered_ids: Iterable[str],
    included: set[str],
) -> tuple[str, ...]:
    return tuple(layer_id for layer_id in ordered_ids if layer_id in included)


def _move_to_bottom(
    layer_ids: Iterable[str],
    bottom_ids: set[str],
) -> tuple[str, ...]:
    values = tuple(layer_ids)
    return tuple(item for item in values if item not in bottom_ids) + tuple(
        item for item in values if item in bottom_ids
    )


def _choice(value: str, *, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback
