"""Point d'entrée du plugin Cartomize pour QGIS."""


def classFactory(iface):  # noqa: N802
    from .plugin import CartomizePlugin

    return CartomizePlugin(iface)
