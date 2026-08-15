"""Préférences locales du plugin, stockées dans QSettings/QGIS."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlparse

from qgis.PyQt.QtCore import QSettings

from .constants import (
    DEFAULT_AUTHOR,
    DEFAULT_COMMUNITY_URL,
    DEFAULT_EXPORT_DPI,
    DEFAULT_MINIMUM_FONT_SIZE_PT,
    DEFAULT_PREVIEW_WIDTH_PX,
    DEFAULT_TEXT_SCALE_PERCENT,
    LEGACY_SETTINGS_PREFIXES,
    SETTINGS_PREFIX,
)


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
        settings = QSettings()
        preview_width_px = max(
            1920,
            min(
                7680,
                _as_int(
                    _setting_value(settings, "preview_width_px", DEFAULT_PREVIEW_WIDTH_PX),
                    DEFAULT_PREVIEW_WIDTH_PX,
                ),
            ),
        )
        text_scale = max(100, min(180, _as_int(_setting_value(settings, "text_scale_percent", DEFAULT_TEXT_SCALE_PERCENT), DEFAULT_TEXT_SCALE_PERCENT)))
        minimum_font = max(8.0, min(14.0, _as_float(_setting_value(settings, "minimum_font_size_pt", DEFAULT_MINIMUM_FONT_SIZE_PT), DEFAULT_MINIMUM_FONT_SIZE_PT)))
        profile_version = _as_int(_setting_value(settings, "readability_profile_version", 0), 0)
        if profile_version < 5:
            preview_width_px = max(preview_width_px, DEFAULT_PREVIEW_WIDTH_PX)
            text_scale = max(text_scale, DEFAULT_TEXT_SCALE_PERCENT)
            minimum_font = max(minimum_font, DEFAULT_MINIMUM_FONT_SIZE_PT)
            settings.setValue(f"{SETTINGS_PREFIX}/readability_profile_version", 5)
        return cls(
            author=str(_setting_value(settings, "author", DEFAULT_AUTHOR)),
            organization=str(_setting_value(settings, "organization", "")),
            # Le portail officiel est intégré au plugin. Une ancienne préférence
            # vide ou erronée ne doit jamais obliger l'utilisateur à le configurer.
            community_url=DEFAULT_COMMUNITY_URL,
            default_dpi=max(150, min(1200, _as_int(_setting_value(settings, "default_dpi", DEFAULT_EXPORT_DPI), DEFAULT_EXPORT_DPI))),
            preview_width_px=preview_width_px,
            text_scale_percent=text_scale,
            minimum_font_size_pt=minimum_font,
            open_designer_after_creation=_as_bool(_setting_value(settings, "open_designer", True)),
            preserve_map_layer_set=_as_bool(_setting_value(settings, "preserve_map_layer_set", True)),
            filter_legend_by_map=_as_bool(_setting_value(settings, "filter_legend_by_map", True)),
        )

    def save(self) -> None:
        settings = QSettings()
        prefix = SETTINGS_PREFIX
        settings.setValue(f"{prefix}/author", self.author.strip()[:200])
        settings.setValue(f"{prefix}/organization", self.organization.strip()[:200])
        settings.setValue(f"{prefix}/community_url", DEFAULT_COMMUNITY_URL)
        settings.setValue(f"{prefix}/default_dpi", max(150, min(1200, int(self.default_dpi))))
        settings.setValue(f"{prefix}/preview_width_px", max(1920, min(7680, int(self.preview_width_px))))
        settings.setValue(f"{prefix}/text_scale_percent", max(100, min(180, int(self.text_scale_percent))))
        settings.setValue(f"{prefix}/minimum_font_size_pt", max(8.0, min(14.0, float(self.minimum_font_size_pt))))
        settings.setValue(f"{prefix}/open_designer", bool(self.open_designer_after_creation))
        settings.setValue(f"{prefix}/preserve_map_layer_set", bool(self.preserve_map_layer_set))
        settings.setValue(f"{prefix}/filter_legend_by_map", bool(self.filter_legend_by_map))
        settings.setValue(f"{prefix}/readability_profile_version", 5)


def _setting_value(settings: QSettings, suffix: str, default):
    """Lit la nouvelle clé, puis migre silencieusement une ancienne préférence."""
    current_key = f"{SETTINGS_PREFIX}/{suffix}"
    try:
        if settings.contains(current_key):
            return settings.value(current_key, default)
    except Exception:
        value = settings.value(current_key, None)
        if value is not None:
            return value
    for prefix in LEGACY_SETTINGS_PREFIXES:
        legacy_key = f"{prefix}/{suffix}"
        try:
            exists = settings.contains(legacy_key)
        except Exception:
            exists = settings.value(legacy_key, None) is not None
        if exists:
            value = settings.value(legacy_key, default)
            settings.setValue(current_key, value)
            return value
    return default


def validate_community_url(value: str) -> str:
    """Retourne une URL HTTPS sûre ou lève ValueError."""
    validated = _validated_url(value)
    if value.strip() and not validated:
        raise ValueError(
            "L'adresse de la communauté doit utiliser HTTPS et ne doit contenir "
            "ni identifiants ni fragment."
        )
    return validated


def _validated_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        return ""
    hostname = (parsed.hostname or "").strip().casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return ""
    try:
        address = ipaddress.ip_address(hostname)
        if not address.is_global:
            return ""
    except ValueError:
        pass
    return value


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
