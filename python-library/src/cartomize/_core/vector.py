"""Port ArcPy du moteur vectoriel Cartomize QGIS 10.5.1.

Les règles de profilage, de rôles sémantiques et de recommandations restent
identiques à la version QGIS. Seule la lecture des champs et géométries est
adaptée à ArcPy. Les données et la symbologie ne sont jamais modifiées ici.
"""

from __future__ import annotations

from dataclasses import asdict
import math
import statistics
import unicodedata
from typing import Any

from .constants import MAX_PROFILE_FEATURES
from .models import FieldProfile

_NAME_HINTS = (
    "name", "nom", "nombre", "nome", "label", "libelle", "libellé",
    "title", "titre", "titulo", "título", "toponym", "toponimo", "topônimo",
)
_ID_HINTS = ("id", "fid", "gid", "objectid", "code", "uuid")
_AREA_HINTS = ("area", "área", "surface", "superf", "ha", "hectare", "hectarea", "hectárea")
_POP_HINTS = (
    "population", "poblacion", "población", "populacao", "população", "pop",
    "habit", "menage", "ménage", "density", "densite", "densité", "densidad", "densidade",
)
_CLASS_HINTS = (
    "class", "classe", "clase", "type", "tipo", "category", "categorie", "catégorie",
    "categoria", "status", "statut", "estado", "landuse", "occupation", "ocupacion",
    "ocupación", "ocupacao", "ocupação", "zone", "zona",
)
_TIME_HINTS = (
    "year", "annee", "année", "ano", "año", "date", "data", "fecha",
    "time", "temps", "tempo", "mois", "month", "mes",
)
_IMPORTANCE_HINTS = (
    "level", "niveau", "nivel", "rank", "rang", "rango", "importance",
    "importancia", "capital", "classe_route", "road_class", "clase_via",
)


def analyze_vector(arcpy: Any, source: Any, sample_limit: int = 1_000) -> dict[str, Any]:
    limit = max(100, min(int(sample_limit), MAX_PROFILE_FEATURES))
    desc = arcpy.Describe(source)
    fields = [field for field in arcpy.ListFields(source) if field.type not in {"Geometry", "Blob", "Raster"}]
    names = [field.name for field in fields]
    values: dict[str, list[Any]] = {name: [] for name in names}
    invalid = empty = multipart = duplicate = sampled = 0
    hashes: set[int] = set()
    cursor_fields = names + (["SHAPE@"] if getattr(desc, "shapeType", None) else [])

    with arcpy.da.SearchCursor(source, cursor_fields) as cursor:
        for row in cursor:
            if sampled >= limit:
                break
            sampled += 1
            for index, name in enumerate(names):
                values[name].append(row[index])
            if len(cursor_fields) > len(names):
                geometry = row[-1]
                if geometry is None or bool(getattr(geometry, "isEmpty", False)):
                    empty += 1
                else:
                    multipart += int(bool(getattr(geometry, "isMultipart", False)))
                    key = hash(bytes(getattr(geometry, "WKB", b"")))
                    duplicate += int(key in hashes)
                    hashes.add(key)
                    try:
                        invalid += int(not bool(getattr(geometry, "isSimple", True)))
                    except Exception:
                        pass

    profiles = [_profile_field(field, values[field.name], sampled) for field in fields]
    geometry_type = _geometry_name(desc)
    role, role_confidence = _infer_role(
        str(getattr(desc, "name", source)),
        str(getattr(desc, "catalogPath", "")),
        geometry_type,
        profiles,
    )
    label = _choose_label(profiles)
    thematic = _choose_thematic(profiles)
    warnings: list[str] = []
    if invalid:
        warnings.append(f"{invalid} géométrie(s) potentiellement non simples dans l'échantillon.")
    if empty:
        warnings.append(f"{empty} géométrie(s) vide(s) dans l'échantillon.")
    if duplicate:
        warnings.append(f"{duplicate} géométrie(s) dupliquée(s) dans l'échantillon.")

    feature_count = int(arcpy.management.GetCount(source)[0])
    if feature_count > sampled:
        warnings.append(
            f"Profil attributaire calculé sur {sampled:,} entités parmi {feature_count:,}."
        )
    if not label and geometry_type == "point":
        warnings.append("Aucun champ d’étiquette suffisamment fiable n’a été identifié.")

    return {
        "layer_id": str(getattr(source, "URI", "") or getattr(desc, "catalogPath", "")),
        "name": str(getattr(desc, "name", source)),
        "source": str(getattr(desc, "catalogPath", "")),
        "layer_name": str(getattr(desc, "name", source)),
        "catalog_path": str(getattr(desc, "catalogPath", "")),
        "geometry_type": geometry_type,
        "crs": str(getattr(getattr(desc, "spatialReference", None), "name", "Unknown")),
        "spatial_reference": str(getattr(getattr(desc, "spatialReference", None), "name", "Unknown")),
        "feature_count": feature_count,
        "sampled_features": sampled,
        "invalid_geometry_count": invalid,
        "empty_geometry_count": empty,
        "multipart_count": multipart,
        "duplicate_geometry_count": duplicate,
        "role": role,
        "role_confidence": role_confidence,
        "label_field": label,
        "thematic_field": thematic,
        "fields": [asdict(item) for item in profiles],
        "warnings": warnings,
    }


def _profile_field(field: Any, values: list[Any], sampled: int) -> FieldProfile:
    non_null = [value for value in values if value not in (None, "")]
    unique = {str(value) for value in non_null}
    numeric = []
    if str(field.type) in {"SmallInteger", "Integer", "Single", "Double", "OID", "BigInteger"}:
        numeric = [float(value) for value in non_null if _finite(value)]
    skewness = _skewness(numeric)
    role, recommended, confidence = _semantic_role(
        field.name, field.type, len(non_null), len(unique),
        len(unique) / max(1, len(non_null)), numeric,
        min(numeric) if numeric else None,
        max(numeric) if numeric else None,
    )
    return FieldProfile(
        name=field.name,
        type_name=str(field.type),
        count=len(non_null),
        null_count=max(0, sampled - len(non_null)),
        null_percent=round(100 * max(0, sampled - len(non_null)) / max(1, sampled), 2),
        unique_count=len(unique),
        unique_ratio=round(len(unique) / max(1, len(non_null)), 4),
        minimum=min(numeric) if numeric else None,
        maximum=max(numeric) if numeric else None,
        median=statistics.median(numeric) if numeric else None,
        mean=statistics.fmean(numeric) if numeric else None,
        skewness=skewness,
        semantic_role=role,
        recommended_use=recommended,
        confidence=round(confidence, 3),
    )


def _semantic_role(
    name: str,
    field_type: str,
    valid_count: int,
    unique_count: int,
    unique_ratio: float,
    numeric_values: list[float],
    minimum: float | None,
    maximum: float | None,
) -> tuple[str, str, float]:
    token = _normalise(name)
    compact = token.replace(" ", "")
    tokens = tuple(item for item in token.replace("-", " ").split() if item)
    numeric = str(field_type) in {"SmallInteger", "Integer", "Single", "Double", "BigInteger"}
    if _matches(token, _NAME_HINTS):
        return "label", "Étiquetage", 0.93
    if compact in _ID_HINTS or (tokens and tokens[-1] in _ID_HINTS):
        return "identifier", "Identifiant, éviter comme variable thématique", 0.88
    if _matches(token, _TIME_HINTS):
        return "temporal", "Filtre temporel ou série", 0.84
    if _matches(token, _POP_HINTS):
        return "quantitative", "Gradué ou symbole proportionnel", 0.94 if numeric else 0.70
    if _matches(token, _AREA_HINTS):
        return "measure", "Mesure auxiliaire", 0.86 if numeric else 0.65
    if _matches(token, _IMPORTANCE_HINTS):
        return "ordinal", "Hiérarchie visuelle et priorité d’étiquetage", 0.88
    if _matches(token, _CLASS_HINTS):
        return "category", "Catégories ou règles", 0.90
    if numeric_values and valid_count:
        if unique_count <= 12 and unique_ratio < 0.25:
            return "coded_category", "Catégories numériques", 0.76
        if minimum is not None and maximum is not None and minimum < 0 < maximum:
            return "diverging_quantitative", "Gradué divergent", 0.82
        return "quantitative", "Gradué", 0.78
    if unique_count and unique_count <= 25 and unique_ratio < 0.55:
        return "category", "Catégories", 0.74
    if unique_ratio > 0.85:
        return "identifier_or_label", "Étiquette possible, vérifier le sens", 0.58
    return "descriptive", "Contexte attributaire", 0.50


def _choose_label(fields: list[FieldProfile]) -> str:
    candidates = [field for field in fields if field.semantic_role == "label"]
    if not candidates:
        candidates = [
            field for field in fields
            if field.semantic_role == "identifier_or_label" and field.null_percent < 15
        ]
    best = max(
        candidates,
        key=lambda item: (item.confidence, -item.null_percent, min(item.unique_count, 5000)),
        default=None,
    )
    return best.name if best else ""


def _choose_thematic(fields: list[FieldProfile]) -> str:
    candidates = [
        field for field in fields
        if field.semantic_role in {
            "category", "coded_category", "quantitative", "diverging_quantitative", "ordinal"
        }
        and field.null_percent < 40
        and field.unique_count >= 2
    ]
    best = max(
        candidates,
        key=lambda item: (
            item.confidence,
            1 if item.semantic_role in {"category", "quantitative", "diverging_quantitative"} else 0,
            -item.null_percent,
        ),
        default=None,
    )
    return best.name if best else ""


def _geometry_name(desc: Any) -> str:
    value = str(getattr(desc, "shapeType", "") or "").casefold()
    if "point" in value:
        return "point"
    if "line" in value or "polyline" in value:
        return "line"
    if "polygon" in value:
        return "polygon"
    return "unknown"


def _infer_role(
    name: str,
    source: str,
    geometry_name: str,
    fields: list[FieldProfile],
) -> tuple[str, float]:
    text = f"{name} {source} {' '.join(field.name for field in fields)}".casefold()
    rules = (
        ("transport", ("route", "road", "rail", "transport", "autoroute", "highway", "carretera", "estrada", "rodovia", "ferrocarril"), 0.96),
        ("hydrographie", ("rivi", "fleuve", "hydro", "water", "eau", "lac", "bassin", "rio", "río", "agua", "lago", "bacia", "cuenca"), 0.96),
        ("limites", ("limite", "boundary", "province", "district", "commune", "departement", "département", "frontera", "fronteira", "municipio", "município"), 0.95),
        ("localités", ("ville", "city", "village", "localite", "localité", "chef lieu", "town", "ciudad", "cidade", "pueblo", "localidad"), 0.94),
        ("bâtiments", ("bati", "bâti", "building", "batiment", "bâtiment", "edificio", "edifício"), 0.91),
        ("parcelles", ("parcelle", "parcel", "parcela", "cadastre", "catastro", "cadastral"), 0.91),
        ("risques", ("risque", "hazard", "alea", "aléa", "vulnerab", "flood", "inond"), 0.90),
        ("occupation_sol", ("landcover", "land cover", "lulc", "occupation", "landuse"), 0.90),
    )
    for role, hints, confidence in rules:
        if any(hint in text for hint in hints):
            return role, confidence
    if geometry_name == "point":
        return "points_thématiques", 0.62
    if geometry_name == "line":
        return "réseau", 0.60
    if geometry_name == "polygon":
        return "zones_thématiques", 0.60
    return "contexte", 0.45


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().replace("_", " ")


def _matches(value: str, hints: tuple[str, ...]) -> bool:
    return any(token in value for token in hints)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _skewness(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = statistics.fmean(values)
    variance = statistics.fmean((value - mean) ** 2 for value in values)
    if variance <= 1e-20:
        return 0.0
    sigma = math.sqrt(variance)
    return statistics.fmean(((value - mean) / sigma) ** 3 for value in values)
