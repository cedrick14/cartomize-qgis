"""Outils de profilage raster purs, testables sans instance QGIS.

Le module centralise les règles NoData/masque afin que les analyses rapides et
approfondies produisent les mêmes résultats.  Les fréquences d'un échantillon
sont extrapolées uniquement sur les pixels valides et les valeurs conservées
sont les plus fréquentes, jamais les premières valeurs numériques.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .raster_intelligence_core import RasterValueProfile


@dataclass(frozen=True)
class RasterSampleSummary:
    profiles: tuple[RasterValueProfile, ...]
    sampled_pixels: int
    valid_pixels: int
    nodata_pixels: int
    observed_unique_count: int
    profile_limited: bool
    quantiles: tuple[tuple[float, float], ...] = ()


def profile_array(
    array: Any,
    mask: Any = None,
    nodata: float | None = None,
    *,
    total_pixels: int | None = None,
    max_profiles: int = 4096,
) -> RasterSampleSummary:
    """Profile un tableau raster en excluant strictement masque et NoData.

    ``mask`` suit la convention GDAL/QGIS : zéro signifie invalide. Une valeur
    NoData déclarée reste invalide même si le masque la marque comme valide.
    Les valeurs NaN/Inf sont également exclues. ``total_pixels`` représente
    la population valide à extrapoler, et non le nombre incluant les NoData.
    """
    try:
        import numpy as np
    except Exception:
        return RasterSampleSummary((), 0, 0, 0, 0, False)

    if array is None:
        return RasterSampleSummary((), 0, 0, 0, 0, False)
    values = np.asarray(array)
    if values.ndim < 2 or values.size == 0:
        return RasterSampleSummary((), int(values.size), 0, int(values.size), 0, False)

    finite = np.isfinite(values)
    valid = finite.copy()
    if mask is not None:
        mask_values = np.asarray(mask)
        if mask_values.shape == values.shape:
            valid &= mask_values != 0
    if nodata is not None:
        try:
            nodata_value = float(nodata)
            if math.isnan(nodata_value):
                valid &= ~np.isnan(values.astype(float, copy=False))
            elif math.isfinite(nodata_value):
                valid &= ~np.isclose(
                    values.astype(float, copy=False), nodata_value, rtol=0.0, atol=0.0
                )
        except (TypeError, ValueError, OverflowError):
            pass

    sampled_pixels = int(values.size)
    valid_count = int(valid.sum())
    nodata_count = sampled_pixels - valid_count
    if valid_count == 0:
        return RasterSampleSummary((), sampled_pixels, 0, nodata_count, 0, False)

    valid_values = values[valid]
    quantile_levels = np.linspace(0.0, 1.0, 51)
    quantile_values = np.quantile(valid_values.astype(float, copy=False), quantile_levels)
    quantiles = tuple(
        (float(level), float(value))
        for level, value in zip(quantile_levels.tolist(), quantile_values.tolist())
        if math.isfinite(float(value))
    )
    unique, counts = np.unique(valid_values, return_counts=True)
    observed_unique_count = int(unique.size)
    max_profiles = max(1, int(max_profiles))
    limited = observed_unique_count > max_profiles
    if limited:
        # Stable ranking: frequency descending, then numeric value ascending.
        order = np.lexsort((unique, -counts))[:max_profiles]
        unique = unique[order]
        counts = counts[order]
        numeric_order = np.argsort(unique)
        unique = unique[numeric_order]
        counts = counts[numeric_order]

    border_mask = np.zeros(values.shape, dtype=bool)
    edge = max(1, min(values.shape[-2:]) // 20)
    border_mask[:edge, :] = True
    border_mask[-edge:, :] = True
    border_mask[:, :edge] = True
    border_mask[:, -edge:] = True
    border_valid = valid & border_mask
    center_valid = valid & ~border_mask
    corner_mask = np.zeros(values.shape, dtype=bool)
    corner_edge = max(1, min(values.shape[-2:]) // 10)
    corner_mask[:corner_edge, :corner_edge] = True
    corner_mask[:corner_edge, -corner_edge:] = True
    corner_mask[-corner_edge:, :corner_edge] = True
    corner_mask[-corner_edge:, -corner_edge:] = True
    corner_valid = valid & corner_mask
    border_total = int(border_valid.sum())
    center_total = int(center_valid.sum())
    corner_total = int(corner_valid.sum())
    population = max(1, int(total_pixels if total_pixels is not None else valid_count))

    profiles = []
    for value, count in zip(unique.tolist(), counts.tolist()):
        value_f = float(value)
        border_count = int(((values == value) & border_valid).sum())
        center_count = int(((values == value) & center_valid).sum())
        corner_count = int(((values == value) & corner_valid).sum())
        profiles.append(
            RasterValueProfile(
                value=value_f,
                pixel_count=int(round(int(count) / valid_count * population)),
                percentage=int(count) / valid_count * 100.0,
                border_percentage=border_count / max(1, border_total),
                center_percentage=center_count / max(1, center_total),
                estimated=population != valid_count,
                corner_percentage=corner_count / max(1, corner_total),
            )
        )
    return RasterSampleSummary(
        tuple(profiles), sampled_pixels, valid_count, nodata_count,
        observed_unique_count, limited, quantiles,
    )


def weighted_quantile_curve(
    counts: dict[float, int],
    *,
    steps: int = 50,
) -> tuple[tuple[float, float], ...]:
    """Construit une courbe de quantiles bornée sans développer les fréquences.

    Cette variante est utilisée par les fournisseurs QGIS qui exposent les
    cellules d'un bloc une par une. Les quantiles restent ceux de l'échantillon
    observé et ne sont jamais présentés comme des statistiques exactes du raster.
    """
    ordered = sorted(
        (float(value), max(0, int(count)))
        for value, count in counts.items()
        if int(count) > 0 and math.isfinite(float(value))
    )
    total = sum(count for _, count in ordered)
    if total <= 0:
        return ()
    steps = max(2, int(steps))
    result: list[tuple[float, float]] = []
    cumulative = 0
    index = 0
    for step in range(steps + 1):
        level = step / steps
        rank = 1 if step == 0 else max(1, int(math.ceil(level * total)))
        while index < len(ordered) - 1 and cumulative + ordered[index][1] < rank:
            cumulative += ordered[index][1]
            index += 1
        result.append((level, ordered[index][0]))
    return tuple(result)


def quantile_value(
    curve: tuple[tuple[float, float], ...],
    probability: float,
) -> float | None:
    """Interpole une valeur sur une courbe de quantiles échantillonnée."""
    points = sorted(
        (float(level), float(value))
        for level, value in curve
        if math.isfinite(float(level)) and math.isfinite(float(value))
    )
    if not points:
        return None
    target = min(1.0, max(0.0, float(probability)))
    if target <= points[0][0]:
        return points[0][1]
    for (left_p, left_v), (right_p, right_v) in zip(points, points[1:]):
        if target <= right_p:
            if right_p <= left_p:
                return right_v
            ratio = (target - left_p) / (right_p - left_p)
            return left_v + ratio * (right_v - left_v)
    return points[-1][1]


def exact_valid_values(array: Any, mask: Any = None, nodata: float | None = None):
    """Retourne les valeurs valides d'un bloc selon les mêmes règles."""
    import numpy as np

    values = np.asarray(array)
    valid = np.isfinite(values)
    if mask is not None:
        mask_values = np.asarray(mask)
        if mask_values.shape == values.shape:
            valid &= mask_values != 0
    if nodata is not None:
        try:
            nodata_value = float(nodata)
            if math.isnan(nodata_value):
                valid &= ~np.isnan(values.astype(float, copy=False))
            elif math.isfinite(nodata_value):
                valid &= ~np.isclose(
                    values.astype(float, copy=False), nodata_value, rtol=0.0, atol=0.0
                )
        except (TypeError, ValueError, OverflowError):
            pass
    return values[valid], int(values.size - valid.sum())
