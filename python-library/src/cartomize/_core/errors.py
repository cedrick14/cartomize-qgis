"""Hiérarchie d’erreurs publique de Cartomize 10.5.1."""


class CartomizeError(RuntimeError):
    pass


class ValidationError(CartomizeError):
    pass


class CompatibilityError(CartomizeError):
    pass


class TemplateError(CartomizeError):
    """Maquette absente, invalide ou non sûre."""


class LayoutBuildError(CartomizeError):
    """Échec de création d'une mise en page ArcGIS Pro."""


class ExportError(CartomizeError):
    """Échec d'un export cartographique."""
