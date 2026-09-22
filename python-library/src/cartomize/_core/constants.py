"""Constantes partagées par les outils Cartomize."""

APP_NAME = "Cartomize for ArcGIS Pro"
APP_VERSION = "10.5.1"
AUTHOR = "ONDON NKOUA Cédrick Belmich"
# Noms historiques conservés pour que les recettes et les modules publics
# Cartomize QGIS 10.5.1 restent importables sans branche conditionnelle.
PLUGIN_NAME = "Cartomize"
PLUGIN_VERSION = APP_VERSION
DEFAULT_AUTHOR = AUTHOR
PLUGIN_MENU = "&Cartomize"
SETTINGS_PREFIX = "Cartomize"
LEGACY_SETTINGS_PREFIXES = ("CartomizeProfessional",)
DEFAULT_COMMUNITY_URL = "https://cartomizeplugin.com"
OFFLINE_TEMPLATE_MANIFEST = "offline_catalog.json"
OFFLINE_TEMPLATE_COUNT = 24
COMMUNITY_CATALOG_CACHE_MAX_BYTES = 2_000_000
COMMUNITY_CATALOG_MAX_ITEMS = 250
COMMUNITY_CATALOG_MAX_PAGES = 12
COMMUNITY_CATALOG_TIMEOUT_SECONDS = 8
DEFAULT_DPI = 600
DEFAULT_EXPORT_DPI = DEFAULT_DPI
DEFAULT_PREVIEW_WIDTH_PX = 3840
DEFAULT_TEXT_SCALE_PERCENT = 130
DEFAULT_MINIMUM_FONT_PT = 9.5
DEFAULT_MINIMUM_FONT_SIZE_PT = DEFAULT_MINIMUM_FONT_PT
MAX_TEMPLATE_BYTES = 1_000_000
MAX_TEMPLATE_ELEMENTS = 250
MAX_AUDIT_LAYERS = 2_000
MAX_PROFILE_FEATURES = 5_000
TEMPLATE_SCALE_PX_PER_MM = 3.0
SUPPORTED_PAGE_FORMATS = {
    "A4 paysage": (297.0, 210.0),
    "A4 portrait": (210.0, 297.0),
    "A3 paysage": (420.0, 297.0),
    "A3 portrait": (297.0, 420.0),
}
BASEMAP_HINTS = (
    "basemap", "base map", "fond de carte", "world hillshade", "world imagery",
    "topographic", "streets", "oceans", "human geography", "openstreetmap",
    "terrain", "light gray", "dark gray", "navigation",
)
