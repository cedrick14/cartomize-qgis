"""Inférence explicable des rôles de bandes et indices spectraux possibles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class BandSemantic:
    band: int
    role: str
    confidence: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpectralIndexProposal:
    index_id: str
    name: str
    formula: str
    required_roles: tuple[str, ...]
    band_mapping: tuple[tuple[str, int], ...]
    confidence: float
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "red": ("red", "rouge", "rojo", "vermelho", "b04", "b4", "sr_b4"),
    "green": ("green", "vert", "verde", "b03", "b3", "sr_b3"),
    "blue": ("blue", "bleu", "azul", "b02", "b2", "sr_b2"),
    "nir": ("nir", "nearinfrared", "near infrared", "proche infrarouge", "b08", "b8", "b8a", "sr_b5"),
    "swir1": ("swir1", "swir 1", "shortwave infrared 1", "b11", "sr_b6"),
    "swir2": ("swir2", "swir 2", "shortwave infrared 2", "b12", "sr_b7"),
    "alpha": ("alpha", "transparency", "transparence"),
    "pan": ("panchromatic", "pan", "b08 pan", "b8 pan"),
}


def infer_band_semantics(
    band_names: Iterable[str],
    color_interpretations: Iterable[str] = (),
    band_metadata: Iterable[dict[str, Any]] = (),
) -> tuple[BandSemantic, ...]:
    names = list(band_names)
    colors = list(color_interpretations)
    metadata = list(band_metadata)
    result: list[BandSemantic] = []
    for index, name in enumerate(names, start=1):
        fragments = [str(name)]
        if index <= len(colors):
            fragments.append(str(colors[index - 1]))
        if index <= len(metadata):
            fragments.extend(f"{key} {value}" for key, value in metadata[index - 1].items())
        text = _normalise(" ".join(fragments))
        candidates: list[tuple[float, str, str]] = []
        color = _normalise(colors[index - 1]) if index <= len(colors) else ""
        wavelength = _wavelength_candidate(metadata[index - 1] if index <= len(metadata) else {})
        if wavelength is not None:
            role = _role_from_wavelength(wavelength)
            if role:
                candidates.append((
                    0.90,
                    role,
                    f"Longueur d’onde centrale déclarée : {wavelength:.4g} µm.",
                ))
        for role, aliases in _ROLE_ALIASES.items():
            for alias in aliases:
                token = _normalise(alias)
                if not token:
                    continue
                if color == token:
                    candidates.append((0.98, role, f"Interprétation couleur GDAL/QGIS : {colors[index - 1]}."))
                elif _contains_token(text, token):
                    confidence = 0.93 if token in {"nir", "swir1", "swir2", "red", "green", "blue"} else 0.84
                    candidates.append((confidence, role, f"Nom ou métadonnée de bande associé à « {alias} »."))
        if candidates:
            score, role, reason = max(candidates, key=lambda item: item[0])
            result.append(BandSemantic(index, role, score, (reason,)))
        else:
            result.append(BandSemantic(index, "unknown", 0.0, ("Aucun rôle spectral explicite détecté.",)))
    return tuple(result)


def propose_spectral_indices(
    semantics: Iterable[BandSemantic],
) -> tuple[SpectralIndexProposal, ...]:
    best: dict[str, BandSemantic] = {}
    for item in semantics:
        previous = best.get(item.role)
        if item.role != "unknown" and (previous is None or item.confidence > previous.confidence):
            best[item.role] = item

    definitions = (
        ("ndvi", "NDVI", "(NIR - Red) / (NIR + Red)", ("nir", "red")),
        ("ndwi", "NDWI (McFeeters)", "(Green - NIR) / (Green + NIR)", ("green", "nir")),
        ("ndmi", "NDMI", "(NIR - SWIR1) / (NIR + SWIR1)", ("nir", "swir1")),
        ("ndbi", "NDBI", "(SWIR1 - NIR) / (SWIR1 + NIR)", ("swir1", "nir")),
        ("savi", "SAVI (L=0.5)", "1.5 * (NIR - Red) / (NIR + Red + 0.5)", ("nir", "red")),
        ("evi", "EVI", "2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)", ("nir", "red", "blue")),
    )
    proposals: list[SpectralIndexProposal] = []
    for index_id, name, formula, required in definitions:
        if not all(role in best for role in required):
            continue
        mapping = tuple((role, best[role].band) for role in required)
        confidence = min(best[role].confidence for role in required)
        rationale = tuple(
            f"{role.upper()} identifié sur la bande {best[role].band} ({best[role].confidence:.0%})."
            for role in required
        )
        proposals.append(
            SpectralIndexProposal(index_id, name, formula, required, mapping, confidence, rationale)
        )
    return tuple(proposals)


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _contains_token(text: str, token: str) -> bool:
    return bool(re.search(rf"(?:^|\s){re.escape(token)}(?:$|\s)", text))


def _wavelength_candidate(metadata: dict[str, Any]) -> float | None:
    """Lit une longueur d'onde explicite et la normalise en micromètres."""
    for key, value in metadata.items():
        key_text = _normalise(str(key))
        if not any(token in key_text for token in ("wavelength", "longueur onde", "center wave", "central wave")):
            continue
        match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
        if not match:
            continue
        try:
            wavelength = float(match.group(0).replace(",", "."))
        except ValueError:
            continue
        value_text = str(value).casefold()
        if "nm" in value_text or wavelength > 100:
            wavelength /= 1000.0
        if 0.3 <= wavelength <= 3.0:
            return wavelength
    return None


def _role_from_wavelength(wavelength_um: float) -> str:
    ranges = (
        ("blue", 0.43, 0.52), ("green", 0.52, 0.60),
        ("red", 0.62, 0.70), ("nir", 0.75, 1.05),
        ("swir1", 1.50, 1.85), ("swir2", 2.00, 2.45),
    )
    for role, lower, upper in ranges:
        if lower <= wavelength_um <= upper:
            return role
    return ""
