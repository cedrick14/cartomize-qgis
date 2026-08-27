"""Hiérarchie d’erreurs publique de Cartomize 10.5.1."""


class CartomizeError(RuntimeError):
    pass


class ValidationError(CartomizeError):
    pass


class CompatibilityError(CartomizeError):
    pass
