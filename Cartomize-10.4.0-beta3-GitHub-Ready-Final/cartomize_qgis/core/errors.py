"""Exceptions explicites de Cartomize."""


class CartomizeError(RuntimeError):
    """Erreur fonctionnelle présentable à l'utilisateur."""


class TemplateError(CartomizeError):
    """Maquette absente, invalide ou non sûre."""


class LayoutBuildError(CartomizeError):
    """Échec de création d'une mise en page QGIS."""


class ExportError(CartomizeError):
    """Échec d'un export cartographique."""
