"""Bibliothèque thématique pure du Raster Engine.

Ce module ne dépend pas de PyQGIS. Il peut donc être testé dans la CI et
utilisé par l'interface sans transformer les valeurs du raster source.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ThematicClass:
    label: str
    color: str


@dataclass(frozen=True)
class RasterThemeProfile:
    key: str
    label: str
    mode: str
    palette: tuple[str, ...]
    description: str
    keywords: tuple[str, ...] = ()
    classes: tuple[ThematicClass, ...] = ()
    preferred_class_count: int = 7
    expected_range: tuple[float, float] | None = None


@dataclass(frozen=True)
class RasterThemeMatch:
    key: str
    confidence: float
    reasons: tuple[str, ...]


def _classes(*items: tuple[str, str]) -> tuple[ThematicClass, ...]:
    return tuple(ThematicClass(label, color) for label, color in items)


THEME_PROFILES: tuple[RasterThemeProfile, ...] = (
    RasterThemeProfile(
        "land_cover", "Occupation du sol", "categorical",
        ("#1B5E20", "#7CB342", "#F9A825", "#8D6E63", "#D32F2F", "#1565C0", "#90A4AE"),
        "Classes discrètes d'occupation ou de couverture terrestre.",
        ("occupation du sol", "couverture terrestre", "land cover", "landcover", "lulc", "worldcover", "esa"),
        _classes(
            ("Forêt", "#1B5E20"), ("Végétation basse", "#7CB342"),
            ("Agriculture", "#F9A825"), ("Sol nu", "#8D6E63"),
            ("Zone bâtie", "#D32F2F"), ("Eau", "#1565C0"),
            ("Autre classe", "#90A4AE"),
        ), 7,
    ),
    RasterThemeProfile(
        "forest_dynamics", "Dynamique forestière", "categorical",
        ("#1B5E20", "#D32F2F", "#F57C00", "#66BB6A", "#9E9E9E"),
        "États stables et transitions du couvert forestier.",
        ("dynamique forestiere", "forest dynamics", "forest change", "changement forestier", "regeneration"),
        _classes(
            ("Forêt stable", "#1B5E20"), ("Déforestation", "#D32F2F"),
            ("Dégradation", "#F57C00"), ("Régénération", "#66BB6A"),
            ("Non-forêt", "#9E9E9E"),
        ), 5,
    ),
    RasterThemeProfile(
        "deforestation", "Déforestation", "categorical",
        ("#1B5E20", "#D32F2F", "#81C784", "#BDBDBD"),
        "Pertes, gains et couvert forestier stable.",
        ("deforestation", "tree cover loss", "forest loss", "perte forestiere", "hansen"),
        _classes(
            ("Forêt stable", "#1B5E20"), ("Perte forestière", "#D32F2F"),
            ("Gain forestier", "#81C784"), ("Non-forêt", "#BDBDBD"),
        ), 4,
    ),
    RasterThemeProfile(
        "forest_degradation", "Dégradation forestière", "categorical",
        ("#0B5D1E", "#A5D66A", "#F9A825", "#D84315", "#BDBDBD"),
        "Niveaux ordonnés de dégradation du couvert forestier.",
        ("degradation forestiere", "forest degradation", "canopy degradation"),
        _classes(
            ("Forêt intacte", "#0B5D1E"), ("Faible dégradation", "#A5D66A"),
            ("Dégradation modérée", "#F9A825"), ("Forte dégradation", "#D84315"),
            ("Non-forêt", "#BDBDBD"),
        ), 5,
    ),
    RasterThemeProfile(
        "land_cover_change", "Changement d'occupation du sol", "categorical",
        ("#546E7A", "#2E7D32", "#C62828", "#F9A825", "#1565C0"),
        "Classes stables et transitions entre deux dates.",
        ("changement occupation", "land cover change", "transition", "change detection"),
        _classes(
            ("Stable", "#546E7A"), ("Gain de végétation", "#2E7D32"),
            ("Perte de végétation", "#C62828"), ("Autre transition", "#F9A825"),
            ("Eau / zone humide", "#1565C0"),
        ), 5,
    ),
    RasterThemeProfile(
        "ndvi", "NDVI / végétation", "continuous",
        ("#8B0000", "#D73027", "#FEE08B", "#D9EF8B", "#1A9850", "#006837"),
        "Rampe divergente adaptée aux indices de végétation.",
        ("ndvi", "vegetation index", "indice de vegetation"), (), 7, (-1.0, 1.0),
    ),
    RasterThemeProfile(
        "elevation", "Altitude / MNT", "continuous",
        ("#1B7837", "#7FBF7B", "#DFC27D", "#A6611A", "#8C6D5A", "#FFFFFF"),
        "Teintes hypsométriques pour altitude, MNT, MNS ou relief.",
        ("mnt", "mns", "dem", "dtm", "dsm", "elevation", "altitude", "srtm", "relief"), (), 9,
    ),
    RasterThemeProfile(
        "slope", "Pente", "continuous",
        ("#FFFFE5", "#FFF7BC", "#FEC44F", "#D95F0E", "#7F2704"),
        "Progression claire à sombre pour les valeurs de pente.",
        ("pente", "slope", "inclinaison"), (), 7, (0.0, 90.0),
    ),
    RasterThemeProfile(
        "temperature", "Température", "continuous",
        ("#313695", "#4575B4", "#74ADD1", "#FEE090", "#F46D43", "#A50026"),
        "Rampe froid-chaud pour température de surface ou de l'air.",
        ("temperature", "temp", "thermal", "lst", "chaleur"), (), 9,
    ),
    RasterThemeProfile(
        "precipitation", "Précipitations", "continuous",
        ("#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"),
        "Rampe séquentielle pour pluie et cumul de précipitations.",
        ("precipitation", "precip", "pluie", "rainfall", "chirps"), (), 8,
    ),
    RasterThemeProfile(
        "risk", "Risque", "continuous",
        ("#FFFFCC", "#FFEDA0", "#FEB24C", "#F03B20", "#BD0026"),
        "Progression conventionnelle de risque faible à élevé.",
        ("risque", "risk", "hazard", "alea", "vulnerabilite", "susceptibilite"), (), 5,
    ),
    RasterThemeProfile(
        "probability", "Probabilité", "continuous",
        ("#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"),
        "Progression de probabilité de 0 à 1 ou de 0 à 100 %.",
        ("probabilite", "probability", "likelihood", "confidence", "confiance"), (), 6, (0.0, 1.0),
    ),
    RasterThemeProfile(
        "categorical", "Classification raster", "categorical",
        ("#2E7D32", "#F9A825", "#1565C0", "#8D6E63", "#6A1B9A", "#546E7A"),
        "Palette qualitative générique conservant les codes et libellés existants.",
        ("classification", "classified", "classe", "categorical"), (), 6,
    ),
    RasterThemeProfile(
        "rgb", "Image satellite RGB", "rgb", (),
        "Composition en couleurs naturelles à partir des bandes identifiées.",
        ("true color", "natural color", "rgb", "optical", "satellite"), (), 3,
    ),
    RasterThemeProfile(
        "false_color", "Image satellite fausses couleurs", "rgb", (),
        "Composition proche infrarouge, rouge et vert lorsque ces bandes sont disponibles.",
        ("false color", "fausses couleurs", "near infrared", "nir"), (), 3,
    ),
    RasterThemeProfile(
        "continuous", "Autre carte thématique continue", "continuous",
        ("#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"),
        "Rampe perceptuelle générique pour une variable continue.", (), (), 7,
    ),
)


_PROFILE_BY_KEY = {profile.key: profile for profile in THEME_PROFILES}


def theme_profile(key: str) -> RasterThemeProfile:
    return _PROFILE_BY_KEY.get(str(key), _PROFILE_BY_KEY["continuous"])


def detect_raster_theme(
    *,
    text: str,
    raster_type: str,
    minimum: float | None = None,
    maximum: float | None = None,
    labels: tuple[str, ...] = (),
    band_roles: tuple[str, ...] = (),
) -> RasterThemeMatch:
    """Détecte un profil et explique les preuves utilisées.

    La confiance est volontairement prudente : une simple plage numérique ne
    suffit jamais à annoncer un thème métier avec une forte certitude.
    """
    haystack = _normalise(" ".join((text, *labels, *band_roles)))
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for profile in THEME_PROFILES:
        if profile.key in {"categorical", "continuous", "rgb"}:
            continue
        matched = [word for word in profile.keywords if _normalise(word) in haystack]
        if matched:
            scores[profile.key] = min(0.92, 0.68 + 0.08 * min(3, len(matched)))
            reasons[profile.key] = [
                "Indices textuels ou métadonnées concordants : " + ", ".join(matched[:4]) + "."
            ]

    if minimum is not None and maximum is not None and minimum < maximum:
        if -1.05 <= minimum <= 0.2 and 0.2 <= maximum <= 1.05:
            scores["ndvi"] = max(scores.get("ndvi", 0.0), 0.58)
            reasons.setdefault("ndvi", []).append("La plage observée est compatible avec un indice normalisé [-1, 1].")
        if 0.0 <= minimum and maximum <= 1.000001:
            scores["probability"] = max(scores.get("probability", 0.0), 0.53)
            reasons.setdefault("probability", []).append("La plage [0, 1] est compatible avec une probabilité, sans la prouver.")

    if scores:
        best = max(scores, key=scores.get)
        return RasterThemeMatch(best, scores[best], tuple(reasons[best]))

    if raster_type in {"rgb", "multiband"}:
        return RasterThemeMatch(
            "rgb", 0.62,
            ("Plusieurs bandes sont disponibles, mais aucune métadonnée thématique décisive n'a été trouvée.",),
        )
    if raster_type in {"categorized", "binary"}:
        return RasterThemeMatch(
            "categorical", 0.60,
            ("Les valeurs sont discrètes; les libellés métier doivent être confirmés par l'expert.",),
        )
    return RasterThemeMatch(
        "continuous", 0.60,
        ("La distribution est continue et aucun thème métier fiable n'est identifiable dans les métadonnées.",),
    )


def is_generic_class_label(label: str) -> bool:
    normalised = _normalise(label).strip()
    return bool(re.fullmatch(r"(?:classe|class|valeur|value)(?:\s+[-+]?\d+(?:[.,]\d+)?)?", normalised))


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value))
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_value.casefold().replace("_", " ").replace("-", " ")).strip()
