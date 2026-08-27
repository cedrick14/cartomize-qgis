"""Noyau déterministe d'inférence raster, indépendant de l'interface QGIS."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class RasterValueProfile:
    value: float
    pixel_count: int
    percentage: float
    border_percentage: float = 0.0
    center_percentage: float = 0.0
    estimated: bool = False
    corner_percentage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RasterEvidence:
    band_count: int
    data_type: str
    total_pixels: int
    valid_pixels: int
    unique_count: int
    values: tuple[RasterValueProfile, ...]
    minimum: float | None = None
    maximum: float | None = None
    source_nodata: float | None = None
    has_mask: bool = False
    has_alpha: bool = False
    has_color_table: bool = False
    has_rat: bool = False
    rat_labels: tuple[tuple[float, str], ...] = ()
    color_labels: tuple[tuple[float, str], ...] = ()
    band_color_interpretations: tuple[str, ...] = ()
    metadata_text: str = ""
    sample_fraction: float = 1.0


@dataclass(frozen=True)
class RasterCandidate:
    value: float
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RasterInference:
    raster_type: str
    confidence: float
    rationale: tuple[str, ...]
    nodata_candidates: tuple[RasterCandidate, ...]
    automatic_nodata_values: tuple[float, ...]
    anomalous_values: tuple[RasterCandidate, ...]
    class_values: tuple[float, ...]
    possible_missing_codes: tuple[int, ...]
    recommended_renderer: str
    recommended_palette: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodata_candidates"] = [item.to_dict() for item in self.nodata_candidates]
        payload["anomalous_values"] = [item.to_dict() for item in self.anomalous_values]
        return payload


def infer_raster(evidence: RasterEvidence) -> RasterInference:
    """Combine plusieurs indices au lieu d'utiliser une règle unique sur le nombre de valeurs."""
    dtype = evidence.data_type.casefold()
    metadata = evidence.metadata_text.casefold()
    values = tuple(sorted(evidence.values, key=lambda item: item.value))
    reasons: list[str] = []

    rgb_score = 0.0
    categorical_score = 0.0
    continuous_score = 0.0

    interpretations = " ".join(evidence.band_color_interpretations).casefold()
    if evidence.band_count >= 3:
        rgb_score += 0.30
    if all(token in interpretations for token in ("red", "green", "blue")):
        rgb_score += 0.55
        reasons.append("Des bandes rouge, verte et bleue sont déclarées dans les métadonnées.")

    integer_dtype = any(token in dtype for token in ("byte", "int", "uint")) and "float" not in dtype
    float_dtype = any(token in dtype for token in ("float", "double"))
    if integer_dtype:
        categorical_score += 0.18
        reasons.append("Le type numérique entier est compatible avec des codes de classes.")
    if float_dtype:
        continuous_score += 0.30
        reasons.append("Le type à virgule flottante favorise l'hypothèse d'une variable continue.")

    if evidence.has_rat:
        categorical_score += 0.48
        reasons.append("Une Raster Attribute Table est disponible.")
    if evidence.has_color_table:
        categorical_score += 0.38
        reasons.append("Une table de couleurs est disponible.")

    if 1 < evidence.unique_count <= 16:
        categorical_score += 0.28
    elif evidence.unique_count <= 64:
        categorical_score += 0.20
    elif evidence.unique_count >= 256:
        continuous_score += 0.24
    if evidence.unique_count > 4096:
        continuous_score += 0.18

    if values and all(_integer_like(item.value) for item in values):
        categorical_score += 0.16
    elif values:
        continuous_score += 0.12

    thematic_tokens = (
        "class", "classe", "lulc", "landcover", "land cover", "occupation du sol",
        "categor", "palette", "code", "worldcover", "igbp",
    )
    if any(token in metadata for token in thematic_tokens):
        categorical_score += 0.22
        reasons.append("Les métadonnées contiennent des termes associés à une classification thématique.")
    continuous_tokens = ("elevation", "altitude", "dem", "temperature", "ndvi", "precip", "density")
    if any(token in metadata for token in continuous_tokens):
        continuous_score += 0.16

    nodata_candidates = detect_nodata_candidates(evidence)
    automatic_nodata_values = select_automatic_nodata_values(evidence, nodata_candidates)
    nodata_values = set()
    if evidence.source_nodata is not None:
        try:
            nodata_values.add(float(evidence.source_nodata))
        except (TypeError, ValueError):
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    nodata_values.update(automatic_nodata_values)
    class_values = tuple(item.value for item in values if item.value not in nodata_values)
    if automatic_nodata_values:
        formatted = ", ".join(_pretty_number(value) for value in automatic_nodata_values)
        reasons.append(
            f"Fond NoData probable détecté par sa concentration sur le pourtour ({formatted}). "
            "Le masquage proposé est visuel, réversible et modifiable par l’expert."
        )

    if evidence.band_count == 1 and len(class_values) == 2 and all(_integer_like(value) for value in class_values):
        raster_type = "binary"
        confidence = min(0.99, 0.78 + categorical_score * 0.20)
        reasons.append("Deux codes thématiques valides sont présents dans une bande unique.")
        renderer = "paletted"
        palette = "qualitative"
    elif rgb_score >= 0.68 and rgb_score > categorical_score:
        raster_type = "rgb"
        confidence = min(0.99, rgb_score)
        renderer = "multiband_color"
        palette = "rgb"
    elif evidence.band_count > 1 and rgb_score < 0.68 and categorical_score < 0.55:
        raster_type = "multiband"
        confidence = 0.72
        reasons.append("Plusieurs bandes sont présentes sans signature RGB ou classification suffisamment forte.")
        renderer = "multiband_color" if evidence.band_count >= 3 else "singleband_gray"
        palette = "neutral"
    elif categorical_score >= max(0.50, continuous_score + 0.08):
        raster_type = "categorized"
        confidence = min(0.99, 0.58 + categorical_score * 0.45)
        renderer = "paletted"
        palette = "qualitative"
    else:
        raster_type = "continuous"
        margin = continuous_score - categorical_score
        confidence = min(0.97, max(0.58, 0.70 + margin * 0.35))
        renderer = "singleband_pseudocolor"
        palette = "diverging" if _crosses_zero(evidence.minimum, evidence.maximum) else "sequential"

    missing = detect_possible_missing_codes(class_values, raster_type)
    anomalies = detect_anomalies(evidence, class_values, nodata_values)
    return RasterInference(
        raster_type=raster_type,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        rationale=tuple(_dedupe(reasons)),
        nodata_candidates=nodata_candidates,
        automatic_nodata_values=automatic_nodata_values,
        anomalous_values=anomalies,
        class_values=class_values,
        possible_missing_codes=missing,
        recommended_renderer=renderer,
        recommended_palette=palette,
    )


def detect_nodata_candidates(evidence: RasterEvidence) -> tuple[RasterCandidate, ...]:
    candidates: dict[float, RasterCandidate] = {}
    if evidence.source_nodata is not None and math.isfinite(float(evidence.source_nodata)):
        value = float(evidence.source_nodata)
        candidates[value] = RasterCandidate(value, 0.995, "Valeur NoData déclarée par le fournisseur raster.")

    for profile in evidence.values:
        border_signal = profile.border_percentage - profile.center_percentage
        strong_perimeter = (
            profile.border_percentage >= 0.60
            and profile.center_percentage <= 0.45
            and border_signal >= 0.35
        )
        strong_corners = (
            profile.corner_percentage >= 0.75
            and profile.border_percentage >= 0.50
            and profile.center_percentage <= 0.60
            and border_signal >= 0.20
        )
        if strong_perimeter or strong_corners:
            spatial_signal = max(border_signal, profile.corner_percentage - profile.center_percentage)
            confidence = min(0.96, 0.62 + spatial_signal * 0.45)
            reason = "Valeur concentrée sur le pourtour et les coins, plus rare au centre du raster."
            previous = candidates.get(profile.value)
            candidate = RasterCandidate(profile.value, round(confidence, 4), reason)
            if previous is None or candidate.confidence > previous.confidence:
                candidates[profile.value] = candidate
    return tuple(sorted(candidates.values(), key=lambda item: (-item.confidence, item.value)))


def select_automatic_nodata_values(
    evidence: RasterEvidence,
    candidates: Iterable[RasterCandidate],
) -> tuple[float, ...]:
    """Sélectionne uniquement les fonds NoData dont le signal spatial est fort.

    Une valeur (y compris 0) n'est jamais masquée à cause de son code numérique.
    En l'absence d'un NoData déclaré, la décision automatique exige un raster
    thématique entier et une nette concentration de la valeur sur le pourtour.
    """
    selected: set[float] = set()
    source_nodata = evidence.source_nodata
    if source_nodata is not None:
        try:
            numeric = float(source_nodata)
            if math.isfinite(numeric):
                selected.add(numeric)
        except (TypeError, ValueError):
            pass

    dtype = evidence.data_type.casefold()
    profiles = {float(item.value): item for item in evidence.values}
    float_dtype = any(token in dtype for token in ("float", "double"))
    integer_dtype = (
        any(token in dtype for token in ("byte", "int", "uint"))
        or (not float_dtype and bool(profiles) and all(_integer_like(value) for value in profiles))
    )
    categorical_shape = (
        evidence.band_count == 1
        and integer_dtype
        and 2 <= evidence.unique_count <= 64
        and bool(profiles)
        and all(_integer_like(value) for value in profiles)
    )
    if not categorical_shape:
        return tuple(sorted(selected))

    for candidate in candidates:
        value = float(candidate.value)
        if value in selected:
            continue
        profile = profiles.get(value)
        if profile is None:
            continue
        border_signal = profile.border_percentage - profile.center_percentage
        strong_perimeter = (
            candidate.confidence >= 0.78
            and profile.border_percentage >= 0.65
            and profile.center_percentage <= 0.38
            and border_signal >= 0.42
        )
        strong_corners = (
            candidate.confidence >= 0.78
            and profile.corner_percentage >= 0.85
            and profile.border_percentage >= 0.55
            and profile.center_percentage <= 0.55
            and border_signal >= 0.25
        )
        if strong_perimeter or strong_corners:
            selected.add(value)
    return tuple(sorted(selected))


def detect_anomalies(
    evidence: RasterEvidence,
    class_values: Iterable[float],
    nodata_values: set[float],
) -> tuple[RasterCandidate, ...]:
    values = sorted(float(value) for value in class_values if value not in nodata_values)
    if len(values) < 4:
        return ()
    profiles = {float(item.value): item for item in evidence.values}
    diffs = [b - a for a, b in zip(values[:-1], values[1:]) if b > a]
    typical_gap = _median(diffs) if diffs else 0.0
    candidates: list[RasterCandidate] = []
    for index, value in enumerate(values):
        profile = profiles.get(value)
        if profile is None:
            continue
        rarity = profile.percentage <= 0.5
        left = value - values[index - 1] if index > 0 else 0.0
        right = values[index + 1] - value if index < len(values) - 1 else 0.0
        gap = max(left, right)
        isolated = typical_gap > 0 and gap >= max(typical_gap * 4.0, 5.0)
        if rarity and isolated:
            confidence = min(0.95, 0.65 + min(0.25, gap / max(typical_gap, 1.0) * 0.03))
            candidates.append(
                RasterCandidate(value, round(confidence, 4), "Valeur rare et nettement isolée des autres codes observés.")
            )
    return tuple(candidates)


def detect_possible_missing_codes(class_values: Iterable[float], raster_type: str) -> tuple[int, ...]:
    if raster_type not in {"categorized", "binary"}:
        return ()
    integers = sorted({int(round(value)) for value in class_values if _integer_like(value)})
    if len(integers) < 2 or len(integers) > 128:
        return ()
    span = integers[-1] - integers[0]
    if span <= 0 or span > 128:
        return ()
    existing = set(integers)
    return tuple(value for value in range(integers[0], integers[-1] + 1) if value not in existing)


def _integer_like(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and abs(number - round(number)) < 1e-9


def _pretty_number(value: float) -> str:
    return str(int(round(value))) if _integer_like(value) else f"{float(value):.6g}"


def _crosses_zero(minimum: float | None, maximum: float | None) -> bool:
    return minimum is not None and maximum is not None and minimum < 0 < maximum


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
