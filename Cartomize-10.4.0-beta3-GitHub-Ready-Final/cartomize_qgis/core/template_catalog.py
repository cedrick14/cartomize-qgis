"""Catalogue sécurisé des maquettes Cartomize historiques.

Les maquettes JSON sont des spécifications déclaratives. Elles sont converties
à l'exécution en objets QgsLayout natifs et ne peuvent contenir aucun script.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from .constants import MAX_TEMPLATE_BYTES, MAX_TEMPLATE_ELEMENTS, SUPPORTED_PAGE_FORMATS
from .errors import TemplateError

_ALLOWED_TYPES = {
    "map_frame",
    "legend",
    "scale_bar",
    "north_arrow",
    "title",
    "subtitle",
    "text",
    "shape",
    "chart",
    "table",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_ALLOWED_STYLE_KEYS = {
    "fill",
    "stroke",
    "strokeWidth",
    "fontSize",
    "fontFamily",
    "fontWeight",
    "fontStyle",
    "textAlign",
    "verticalAlign",
    "opacity",
}
_ALLOWED_CONTENT_KEYS = {
    "text",
    "role",
    "mode",
    "title",
    "map_id",
    "field",
    "source",
}


@dataclass(frozen=True)
class TemplateSpec:
    template_id: str
    path: Path
    name: str
    category: str
    variant: str
    description: str
    page_format: str
    accent_color: str
    tags: tuple[str, ...]
    purpose: str
    notes: tuple[str, ...]
    elements: tuple[dict[str, Any], ...]
    background_color: str

    @property
    def page_size_mm(self) -> tuple[float, float]:
        return SUPPORTED_PAGE_FORMATS[self.page_format]

    @property
    def map_count(self) -> int:
        return sum(1 for item in self.elements if item.get("type") == "map_frame")


class TemplateCatalog:
    """Charge et valide un catalogue local, sans suivre de liens symboliques."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._templates: dict[str, TemplateSpec] = {}

    def reload(self) -> None:
        templates: dict[str, TemplateSpec] = {}
        if not self.root.is_dir():
            raise TemplateError(f"Dossier de maquettes introuvable : {self.root}")
        for path in sorted(self.root.rglob("*.json")):
            if path.is_symlink():
                continue
            resolved = path.resolve()
            if self.root not in resolved.parents:
                continue
            spec = self._load_one(resolved)
            if spec.template_id in templates:
                raise TemplateError(f"Identifiant de maquette dupliqué : {spec.template_id}")
            templates[spec.template_id] = spec
        if not templates:
            raise TemplateError("Aucune maquette Cartomize valide n'a été trouvée.")
        self._templates = templates

    def all(self) -> list[TemplateSpec]:
        if not self._templates:
            self.reload()
        return sorted(self._templates.values(), key=lambda x: (x.category, x.name.casefold()))

    def get(self, template_id: str) -> TemplateSpec:
        if not self._templates:
            self.reload()
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise TemplateError(f"Maquette inconnue : {template_id}") from exc

    def categories(self) -> list[str]:
        return sorted({item.category for item in self.all()})

    def search(self, text: str = "", category: str = "") -> list[TemplateSpec]:
        needle = text.strip().casefold()
        category = category.strip().casefold()
        result: list[TemplateSpec] = []
        for item in self.all():
            if category and category != "toutes" and item.category.casefold() != category:
                continue
            haystack = " ".join((item.name, item.description, item.category, *item.tags)).casefold()
            if needle and needle not in haystack:
                continue
            result.append(item)
        return result

    def _load_one(self, path: Path) -> TemplateSpec:
        if path.stat().st_size > MAX_TEMPLATE_BYTES:
            raise TemplateError(f"Maquette trop volumineuse : {path.name}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TemplateError(f"JSON de maquette invalide : {path.name}") from exc
        if not isinstance(raw, dict):
            raise TemplateError(f"Structure de maquette invalide : {path.name}")
        layout = raw.get("layout_json")
        if not isinstance(layout, dict):
            raise TemplateError(f"layout_json absent : {path.name}")
        page_format = str(raw.get("page_format") or layout.get("page_format") or "").strip()
        if page_format not in SUPPORTED_PAGE_FORMATS:
            raise TemplateError(f"Format de page non pris en charge dans {path.name}: {page_format}")
        elements = layout.get("elements")
        if (
            not isinstance(elements, list)
            or not elements
            or len(elements) > MAX_TEMPLATE_ELEMENTS
        ):
            raise TemplateError(f"Liste d'éléments invalide dans {path.name}")
        clean: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, element in enumerate(elements):
            clean.append(self._validate_element(element, index, seen, path.name))
        relative = path.relative_to(self.root).with_suffix("")
        template_id = relative.as_posix()
        return TemplateSpec(
            template_id=template_id,
            path=path,
            name=_limited_text(raw.get("name"), 160, template_id),
            category=_limited_text(raw.get("category"), 64, relative.parts[0]),
            variant=_limited_text(raw.get("variant"), 64, "standard"),
            description=_limited_text(raw.get("description"), 1000, ""),
            page_format=page_format,
            accent_color=_safe_color(raw.get("accent_color"), "#1e293b"),
            tags=tuple(_limited_text(t, 64, "") for t in _iter_strings(raw.get("tags"), 20)),
            purpose=_limited_text(raw.get("purpose"), 100, "cartographie"),
            notes=tuple(
                _limited_text(t, 300, "")
                for t in _iter_strings(raw.get("cartographic_notes"), 20)
            ),
            elements=tuple(clean),
            background_color=_safe_color(layout.get("background_color"), "#ffffff"),
        )

    @staticmethod
    def _validate_element(
        element: Any, index: int, seen: set[str], filename: str
    ) -> dict[str, Any]:
        if not isinstance(element, dict):
            raise TemplateError(f"Élément #{index} invalide dans {filename}")
        kind = str(element.get("type") or "").strip()
        if kind not in _ALLOWED_TYPES:
            raise TemplateError(f"Type d'élément interdit dans {filename}: {kind}")
        item_id = str(element.get("id") or f"{kind}-{index}").strip()
        if not _SAFE_ID.fullmatch(item_id) or item_id in seen:
            item_id = f"{kind}-{index}"
        seen.add(item_id)
        return {
            "id": item_id,
            "type": kind,
            "x": _bounded_float(element.get("x"), -5000, 5000, 0),
            "y": _bounded_float(element.get("y"), -5000, 5000, 0),
            "width": _bounded_float(element.get("width"), 1, 5000, 100),
            "height": _bounded_float(element.get("height"), 1, 5000, 40),
            "angle": _bounded_float(element.get("angle"), -3600, 3600, 0),
            "z_index": int(_bounded_float(element.get("z_index"), -1000, 1000, index)),
            "locked": bool(element.get("locked", False)),
            "style": _clean_style(element.get("style")),
            "content": _clean_content(element.get("content")),
        }


def _clean_style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in _ALLOWED_STYLE_KEYS:
        if key not in value:
            continue
        candidate = value[key]
        if key in {"fill", "stroke"}:
            clean[key] = _safe_color(candidate, "#000000" if key == "stroke" else "#ffffff")
        elif key in {"strokeWidth", "fontSize", "opacity"}:
            clean[key] = _bounded_float(candidate, 0, 500, 1)
        else:
            clean[key] = _limited_text(candidate, 120, "")
    return clean


def _clean_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in _ALLOWED_CONTENT_KEYS:
        if key in value:
            clean[key] = _limited_text(value[key], 4000 if key == "text" else 200, "")
    return clean


def _iter_strings(value: Any, max_items: int) -> Iterable[str]:
    if not isinstance(value, list):
        return ()
    return (str(item) for item in value[:max_items] if isinstance(item, (str, int, float)))


def _limited_text(value: Any, limit: int, default: str) -> str:
    if value is None:
        return default
    text = str(value).replace("\x00", "").strip()
    return text[:limit] or default


def _safe_color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", text):
        return text
    return default


def _bounded_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(minimum, min(maximum, number))
