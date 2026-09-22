# Validation de Cartomize Python 0.1.0a1

Validation locale effectuée le 22 septembre 2026 sous Linux, Python 3.12.14.

## Résultats

- **30 tests automatisés réussis**.
- Les 24 maquettes originales ont été chargées et rendues; une planche de
  contrôle a permis d'examiner les cadres, légendes, titres et éléments liés.
- Carte de démonstration produite en PDF, PNG et SVG, et atlas de deux pages.
- Données de démonstration explicitement fictives.
- Wheel et archive source construits avec `python -m build`.
- Métadonnées des deux distributions acceptées par `python -m twine check`.
- Installation du wheel dans un nouvel environnement virtuel, import,
  accès aux 24 maquettes et rendu d'une carte réussis.

## Risques couverts par les tests

Mesures en mètres et conversion des pieds; refus des calculs en degrés;
alignement des CRS pour jointures/intersections; audit et réparation de
géométries; profilage sémantique hérité; conservation des attributs et index;
NoData, masques et zéro valide; NDVI et facteurs de mise à l'échelle;
reclassification; zones sans intersection; surfaces sur grille tournée;
contrôle d'alignement des matrices de changement; reprojection et découpage;
dimensions physiques des exports; cadres indépendants; distance de la barre
d'échelle vérifiée par calcul géodésique; atlas et collisions de noms;
empreintes des modules/maquettes repris et absence d'import ArcPy/QGIS.

17 avertissements de dépréciation proviennent de l'utilisation de l'opérateur
matriciel d'Affine par Rasterio dans les tests. Aucun échec de test associé.

## Portée

Ces contrôles démontrent le fonctionnement de cette première version sur
les cas couverts. Ils ne valident pas tous les jeux de données SIG possibles,
la parité complète avec le rendu Esri, ni les performances à l'échelle de
rasters très volumineux. Le workflow GitHub prévoit Windows/Linux avec
Python 3.11 et 3.12; consulter ses exécutions avant d'annoncer leur réussite.

Les fichiers ont été préparés localement pour la distribution. Aucun envoi
vers TestPyPI ou PyPI n'a été réalisé.
