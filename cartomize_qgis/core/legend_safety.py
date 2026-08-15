"""Protections pour personnaliser une légende sans modifier le projet QGIS."""
from __future__ import annotations


def isolate_legend_model(legend) -> bool:
    """Détache le modèle de légende de l'arbre des couches du projet.

    Dans QGIS 3, une légende nouvellement créée suit par défaut l'arbre du
    projet. Supprimer un nœud de ce modèle avant de désactiver la
    synchronisation peut donc retirer la couche correspondante du panneau des
    couches. Cartomize ne personnalise jamais le modèle tant que ce détachement
    n'a pas réussi.
    """

    setter = getattr(legend, "setAutoUpdateModel", None)
    if not callable(setter):
        return False
    try:
        setter(False)
        checker = getattr(legend, "autoUpdateModel", None)
        if callable(checker) and bool(checker()):
            return False
    except Exception:
        return False
    return True
