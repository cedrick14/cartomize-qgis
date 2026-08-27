"""Chargement sécurisé du catalogue déclaratif des 24 maquettes."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

from .constants import MAX_TEMPLATE_BYTES, MAX_TEMPLATE_ELEMENTS, SUPPORTED_PAGE_FORMATS
from .models import TemplateSpec

_ALLOWED_TYPES = {
    "map_frame", "legend", "scale_bar", "north_arrow", "title", "subtitle",
    "text", "shape", "chart", "table",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_SAFE_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def discover_template_root(toolbox_file: str | Path) -> Path:
    here = Path(toolbox_file).resolve().parent
    candidates = (
        here.parent / "Templates",
        here.parent / "templates_library",
        here / "templates_library",
    )
    for candidate in candidates:
        if (candidate / "offline_catalog.json").is_file():
            return candidate.resolve()
    raise FileNotFoundError("Le catalogue local des 24 maquettes Cartomize est introuvable.")


class TemplateCatalog:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._items: dict[str, TemplateSpec] = {}

    def reload(self) -> None:
        manifest_path = self.root / "offline_catalog.json"
        manifest = self._read_json(manifest_path)
        entries = manifest.get("templates") if isinstance(manifest, dict) else None
        if not isinstance(entries, list) or len(entries) != 24:
            raise ValueError("Le catalogue hors ligne doit référencer exactement 24 maquettes.")

        items: dict[str, TemplateSpec] = {}
        for entry in entries:
            relative = str(entry.get("path") if isinstance(entry, dict) else "").replace("\\", "/")
            parts = Path(relative).parts
            if not relative.endswith(".json") or not parts or ".." in parts or Path(relative).is_absolute():
                raise ValueError(f"Chemin de maquette interdit : {relative or '<vide>'}")
            path = (self.root / relative).resolve()
            if self.root not in path.parents or path.is_symlink() or not path.is_file():
                raise ValueError(f"Maquette locale invalide : {relative}")
            spec = self._load_one(path)
            if spec.template_id in items:
                raise ValueError(f"Identifiant de maquette dupliqué : {spec.template_id}")
            items[spec.template_id] = spec
        self._items = items

    def all(self) -> list[TemplateSpec]:
        if not self._items:
            self.reload()
        return sorted(self._items.values(), key=lambda item: (item.category, item.name.casefold()))

    def get(self, template_id: str) -> TemplateSpec:
        if not self._items:
            self.reload()
        try:
            return self._items[template_id]
        except KeyError as exc:
            raise KeyError(f"Maquette Cartomize inconnue : {template_id}") from exc

    def labels(self) -> dict[str, str]:
        return {f"{item.category} — {item.name}": item.template_id for item in self.all()}

    def _load_one(self, path: Path) -> TemplateSpec:
        raw = self._read_json(path)
        layout = raw.get("layout_json") if isinstance(raw, dict) else None
        if not isinstance(layout, dict):
            raise ValueError(f"layout_json absent : {path.name}")
        page_format = str(raw.get("page_format") or layout.get("page_format") or "").strip()
        if page_format not in SUPPORTED_PAGE_FORMATS:
            raise ValueError(f"Format de page non pris en charge : {page_format}")
        elements = layout.get("elements")
        if not isinstance(elements, list) or not elements or len(elements) > MAX_TEMPLATE_ELEMENTS:
            raise ValueError(f"Liste d’éléments invalide : {path.name}")
        clean: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, element in enumerate(elements):
            clean.append(self._clean_element(element, index, seen))
        template_id = path.relative_to(self.root).with_suffix("").as_posix()
        return TemplateSpec(
            template_id=template_id,
            name=_text(raw.get("name"), 160, template_id),
            category=_text(raw.get("category"), 64, Path(template_id).parts[0]),
            description=_text(raw.get("description"), 1000, ""),
            page_format=page_format,
            background_color=_color(layout.get("background_color"), "#FFFFFF"),
            accent_color=_color(raw.get("accent_color"), "#1F5C45"),
            elements=tuple(clean),
        )

    @staticmethod
    def _clean_element(value: Any, index: int, seen: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Élément #{index} invalide.")
        kind = str(value.get("type") or "").strip()
        if kind not in _ALLOWED_TYPES:
            raise ValueError(f"Type d’élément interdit : {kind}")
        item_id = str(value.get("id") or f"{kind}-{index}").strip()
        if not _SAFE_ID.fullmatch(item_id) or item_id in seen:
            item_id = f"{kind}-{index}"
        seen.add(item_id)
        style = value.get("style") if isinstance(value.get("style"), dict) else {}
        content = value.get("content") if isinstance(value.get("content"), dict) else {}
        return {
            "id": item_id,
            "type": kind,
            "x": _number(value.get("x"), -5000, 5000, 0),
            "y": _number(value.get("y"), -5000, 5000, 0),
            "width": _number(value.get("width"), 1, 5000, 100),
            "height": _number(value.get("height"), 1, 5000, 40),
            "angle": _number(value.get("angle"), -3600, 3600, 0),
            "z_index": int(_number(value.get("z_index"), -1000, 1000, index)),
            "locked": bool(value.get("locked", False)),
            "style": {
                "fill": _color(style.get("fill"), "#000000"),
                "stroke": _color(style.get("stroke"), "#000000"),
                "strokeWidth": _number(style.get("strokeWidth"), 0, 50, 0.5),
                "fontSize": _number(style.get("fontSize"), 1, 200, 10),
                "fontFamily": _text(style.get("fontFamily"), 120, "Arial").split(",")[0],
                "fontWeight": _text(style.get("fontWeight"), 30, "normal"),
                "textAlign": _text(style.get("textAlign"), 30, "left"),
                "opacity": _number(style.get("opacity"), 0, 1, 1),
            },
            "content": {str(k): _text(v, 4000, "") for k, v in content.items()},
        }

    @staticmethod
    def _read_json(path: Path) -> Any:
        if path.stat().st_size > MAX_TEMPLATE_BYTES:
            raise ValueError(f"Fichier de maquette trop volumineux : {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))


def _text(value: Any, limit: int, default: str) -> str:
    text = str(value if value is not None else "").replace("\x00", "").strip()
    return text[:limit] or default


def _color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if _SAFE_COLOR.fullmatch(text) else default


def _number(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(low, min(high, number)) if math.isfinite(number) else float(default)
