"""Analyse intelligente, explicable et non destructive des couches vectorielles QGIS."""
from __future__ import annotations
import logging

from dataclasses import asdict, dataclass
import math
import statistics
from typing import Any

from qgis.core import QgsFeatureRequest, QgsVectorLayer, QgsWkbTypes

from .constants import MAX_PROFILE_FEATURES
from .errors import CartomizeError


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


@dataclass(frozen=True)
class FieldProfile:
    name: str
    type_name: str
    count: int
    null_count: int
    null_percent: float
    unique_count: int
    unique_ratio: float
    minimum: float | None
    maximum: float | None
    median: float | None
    mean: float | None
    skewness: float | None
    semantic_role: str
    recommended_use: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VectorLayerProfile:
    layer_id: str
    name: str
    source: str
    geometry_type: str
    crs: str
    feature_count: int
    sampled_features: int
    invalid_geometry_count: int
    empty_geometry_count: int
    multipart_count: int
    duplicate_geometry_count: int
    role: str
    role_confidence: float
    label_field: str
    thematic_field: str
    fields: tuple[FieldProfile, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["fields"] = [field.to_dict() for field in self.fields]
        return result


class VectorIntelligenceEngine:
    """Profile une couche vectorielle sans modifier les données ni la symbologie."""

    def __init__(self, *, sample_limit: int | None = None, geometry_check_limit: int = 300):
        # Un échantillon borné suffit à recommander champs et styles. Cette
        # limite protège surtout les couches réseau (WFS/PostGIS) sur QGIS LTR.
        requested_limit = 1_000 if sample_limit is None else int(sample_limit)
        self.sample_limit = max(100, min(requested_limit, MAX_PROFILE_FEATURES))
        self.geometry_check_limit = max(50, min(int(geometry_check_limit), self.sample_limit))

    def analyze(self, layer: QgsVectorLayer) -> VectorLayerProfile:
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise CartomizeError("Vector Intelligence exige une couche vectorielle valide.")

        fields = list(layer.fields())
        values_by_field: dict[str, list[Any]] = {field.name(): [] for field in fields}
        geometry_checked = invalid = empty = multipart = duplicate_geometry = sampled = 0
        seen_geometry_hashes: set[int] = set()

        request = QgsFeatureRequest()
        try:
            request.setLimit(self.sample_limit)
        except AttributeError:
            logging.getLogger(__name__).debug(
                "Cette version QGIS n'expose pas QgsFeatureRequest.setLimit.",
                exc_info=True,
            )
        for feature in layer.getFeatures(request):
            sampled += 1
            for field in fields:
                name = field.name()
                try:
                    values_by_field[name].append(feature[name])
                except Exception:
                    try:
                        values_by_field[name].append(feature.attribute(name))
                    except Exception:
                        values_by_field[name].append(None)
            if geometry_checked < self.geometry_check_limit:
                geometry_checked += 1
                try:
                    geometry = feature.geometry()
                    if geometry is None or geometry.isNull() or geometry.isEmpty():
                        empty += 1
                    else:
                        try:
                            if geometry.isMultipart():
                                multipart += 1
                        except Exception:
                            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
                        try:
                            signature = hash(bytes(geometry.asWkb()))
                            if signature in seen_geometry_hashes:
                                duplicate_geometry += 1
                            else:
                                seen_geometry_hashes.add(signature)
                        except Exception:
                            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
                        try:
                            if not geometry.isGeosValid():
                                invalid += 1
                        except Exception:
                            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
                except Exception:
                    empty += 1
            if sampled >= self.sample_limit:
                break

        profiles = tuple(
            self._profile_field(field, values_by_field.get(field.name(), []))
            for field in fields
        )
        geometry_name = self._geometry_name(layer)
        role, role_confidence = self._infer_role(layer, geometry_name, profiles)
        label_field = self._choose_label_field(profiles)
        thematic_field = self._choose_thematic_field(profiles)
        warnings: list[str] = []
        if invalid:
            warnings.append(
                f"{invalid} géométrie(s) invalide(s) détectée(s) dans un échantillon de {geometry_checked}."
            )
        if empty:
            warnings.append(
                f"{empty} géométrie(s) vide(s) détectée(s) dans un échantillon de {geometry_checked}."
            )
        if duplicate_geometry:
            warnings.append(
                f"{duplicate_geometry} géométrie(s) dupliquée(s) détectée(s) dans l’échantillon contrôlé."
            )
        try:
            feature_count = int(layer.featureCount())
        except Exception:
            feature_count = sampled
        if feature_count > sampled:
            warnings.append(
                f"Profil attributaire calculé sur {sampled:,} entités parmi {feature_count:,}."
            )
        if not label_field and geometry_name == "point":
            warnings.append("Aucun champ d’étiquette suffisamment fiable n’a été identifié.")
        return VectorLayerProfile(
            layer_id=str(layer.id()),
            name=str(layer.name()),
            source=str(layer.source() or ""),
            geometry_type=geometry_name,
            crs=layer.crs().authid() or layer.crs().description() or "",
            feature_count=feature_count,
            sampled_features=sampled,
            invalid_geometry_count=invalid,
            empty_geometry_count=empty,
            multipart_count=multipart,
            duplicate_geometry_count=duplicate_geometry,
            role=role,
            role_confidence=role_confidence,
            label_field=label_field,
            thematic_field=thematic_field,
            fields=profiles,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _geometry_name(layer: QgsVectorLayer) -> str:
        try:
            geometry = QgsWkbTypes.geometryType(layer.wkbType())
            if geometry == QgsWkbTypes.GeometryType.PointGeometry:
                return "point"
            if geometry == QgsWkbTypes.GeometryType.LineGeometry:
                return "line"
            if geometry == QgsWkbTypes.GeometryType.PolygonGeometry:
                return "polygon"
        except Exception:
            logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
        return "unknown"

    def _profile_field(self, field, values: list[Any]) -> FieldProfile:
        name = str(field.name())
        try:
            type_name = str(field.typeName())
        except Exception:
            type_name = ""
        count = len(values)
        clean = [value for value in values if not _is_null(value)]
        null_count = count - len(clean)
        unique_values = _unique_values(clean, 2000)
        unique_count = len(unique_values)
        unique_ratio = unique_count / max(1, len(clean))
        numeric = _numeric_values(clean)
        minimum = maximum = median = mean = skewness = None
        if numeric:
            minimum = min(numeric)
            maximum = max(numeric)
            median = statistics.median(numeric)
            mean = statistics.fmean(numeric)
            skewness = _skewness(numeric)
        semantic_role, recommended_use, confidence = self._infer_field_role(
            name, type_name, len(clean), unique_count, unique_ratio, numeric, minimum, maximum
        )
        return FieldProfile(
            name=name,
            type_name=type_name,
            count=count,
            null_count=null_count,
            null_percent=null_count / max(1, count) * 100.0,
            unique_count=unique_count,
            unique_ratio=unique_ratio,
            minimum=minimum,
            maximum=maximum,
            median=median,
            mean=mean,
            skewness=skewness,
            semantic_role=semantic_role,
            recommended_use=recommended_use,
            confidence=confidence,
        )

    @staticmethod
    def _infer_field_role(
        name: str,
        type_name: str,
        valid_count: int,
        unique_count: int,
        unique_ratio: float,
        numeric: list[float],
        minimum: float | None,
        maximum: float | None,
    ) -> tuple[str, str, float]:
        text = name.casefold().replace("_", " ")
        compact = text.replace(" ", "")
        name_tokens = tuple(token for token in text.replace("-", " ").split() if token)
        if any(token in text for token in _NAME_HINTS):
            return "label", "Étiquetage", 0.93
        if compact in _ID_HINTS or (name_tokens and name_tokens[-1] in _ID_HINTS):
            return "identifier", "Identifiant, éviter comme variable thématique", 0.88
        if any(token in text for token in _TIME_HINTS):
            return "temporal", "Filtre temporel ou série", 0.84
        if any(token in text for token in _POP_HINTS):
            return "quantitative", "Gradué ou symbole proportionnel", 0.94 if numeric else 0.70
        if any(token in text for token in _AREA_HINTS):
            return "measure", "Mesure auxiliaire", 0.86 if numeric else 0.65
        if any(token in text for token in _IMPORTANCE_HINTS):
            return "ordinal", "Hiérarchie visuelle et priorité d’étiquetage", 0.88
        if any(token in text for token in _CLASS_HINTS):
            return "category", "Catégories ou règles", 0.90
        if numeric and valid_count:
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

    @staticmethod
    def _choose_label_field(fields: tuple[FieldProfile, ...]) -> str:
        candidates = [field for field in fields if field.semantic_role == "label"]
        if not candidates:
            candidates = [
                field for field in fields
                if field.semantic_role == "identifier_or_label" and field.null_percent < 15
            ]
        if not candidates:
            return ""
        best = max(
            candidates,
            key=lambda field: (
                field.confidence,
                -field.null_percent,
                min(field.unique_count, 5000),
            ),
        )
        return best.name

    @staticmethod
    def _choose_thematic_field(fields: tuple[FieldProfile, ...]) -> str:
        useful = [
            field for field in fields
            if field.semantic_role in {
                "category", "coded_category", "quantitative", "diverging_quantitative", "ordinal"
            }
            and field.null_percent < 40
            and field.unique_count >= 2
        ]
        if not useful:
            return ""
        best = max(
            useful,
            key=lambda field: (
                field.confidence,
                1 if field.semantic_role in {"category", "quantitative", "diverging_quantitative"} else 0,
                -field.null_percent,
            ),
        )
        return best.name

    @staticmethod
    def _infer_role(
        layer: QgsVectorLayer,
        geometry_name: str,
        fields: tuple[FieldProfile, ...],
    ) -> tuple[str, float]:
        text = f"{layer.name()} {layer.source()} {' '.join(field.name for field in fields)}".casefold()
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
        for role, tokens, confidence in rules:
            if any(token in text for token in tokens):
                return role, confidence
        if geometry_name == "point":
            return "points_thématiques", 0.62
        if geometry_name == "line":
            return "réseau", 0.60
        if geometry_name == "polygon":
            return "zones_thématiques", 0.60
        return "contexte", 0.45


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        if hasattr(value, "isNull") and value.isNull():
            return True
    except Exception:
        logging.getLogger(__name__).debug("Non-fatal Cartomize operation failed", exc_info=True)
    return isinstance(value, float) and not math.isfinite(value)


def _unique_values(values: list[Any], limit: int) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = f"{type(value).__name__}:{value!r}"
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _numeric_values(values: list[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            logging.getLogger(__name__).debug("Non-fatal Cartomize item skipped", exc_info=True)
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def _skewness(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = statistics.fmean(values)
    variance = statistics.fmean((value - mean) ** 2 for value in values)
    if variance <= 1e-20:
        return 0.0
    sigma = math.sqrt(variance)
    return statistics.fmean(((value - mean) / sigma) ** 3 for value in values)
