"""Préférences locales Cartomize, adaptées au profil ArcGIS Pro."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from .constants import (
    DEFAULT_AUTHOR, DEFAULT_COMMUNITY_URL, DEFAULT_EXPORT_DPI,
    DEFAULT_MINIMUM_FONT_SIZE_PT, DEFAULT_PREVIEW_WIDTH_PX,
    DEFAULT_TEXT_SCALE_PERCENT,
)


def _settings_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "Cartomize" / "settings-10.5.1.json"


@dataclass
class CartomizeSettings:
    author: str = DEFAULT_AUTHOR
    organization: str = ""
    community_url: str = DEFAULT_COMMUNITY_URL
    default_dpi: int = DEFAULT_EXPORT_DPI
    preview_width_px: int = DEFAULT_PREVIEW_WIDTH_PX
    text_scale_percent: int = DEFAULT_TEXT_SCALE_PERCENT
    minimum_font_size_pt: float = DEFAULT_MINIMUM_FONT_SIZE_PT
    open_designer_after_creation: bool = True
    preserve_map_layer_set: bool = True
    filter_legend_by_map: bool = True

    @classmethod
    def load(cls) -> "CartomizeSettings":
        try:
            payload = json.loads(_settings_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            author=str(payload.get("author") or DEFAULT_AUTHOR)[:200],
            organization=str(payload.get("organization") or "")[:200],
            community_url=DEFAULT_COMMUNITY_URL,
            default_dpi=max(150, min(1200, _as_int(payload.get("default_dpi"), DEFAULT_EXPORT_DPI))),
            preview_width_px=max(1920, min(7680, _as_int(payload.get("preview_width_px"), DEFAULT_PREVIEW_WIDTH_PX))),
            text_scale_percent=max(100, min(180, _as_int(payload.get("text_scale_percent"), DEFAULT_TEXT_SCALE_PERCENT))),
            minimum_font_size_pt=max(8.0, min(14.0, _as_float(payload.get("minimum_font_size_pt"), DEFAULT_MINIMUM_FONT_SIZE_PT))),
            open_designer_after_creation=_as_bool(payload.get("open_designer_after_creation", True)),
            preserve_map_layer_set=_as_bool(payload.get("preserve_map_layer_set", True)),
            filter_legend_by_map=_as_bool(payload.get("filter_legend_by_map", True)),
        )

    def save(self) -> None:
        target = _settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["community_url"] = DEFAULT_COMMUNITY_URL
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def to_dict(self):
        return asdict(self)


def validate_community_url(value: str) -> str:
    validated = _validated_url(value)
    if str(value or "").strip() and not validated:
        raise ValueError("L'adresse de la communauté doit utiliser HTTPS et ne contenir ni identifiants ni fragment.")
    return validated


def _validated_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        return ""
    hostname = (parsed.hostname or "").strip().casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return ""
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return ""
    except ValueError:
        pass
    return value


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
