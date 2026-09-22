# Validation de Cartomize Python 0.2.0a1

Validation locale effectuée le 22 septembre 2026 sous Linux, Python 3.12.14.

## Résultats

- **52 tests automatisés réussis**.
- Les contrôles antérieurs sur les 24 maquettes sont conservés; leur provenance et
  leur chargement sont couverts par la suite existante.
- Nouvelle démonstration multiscène : cinq bandes à 10/20 m, deux scènes,
  masque de qualité, zone polygonale, RGBA naturel/fausses couleurs, NDVI,
  origine des pixels et carte PDF/PNG avec routes, limites et localités.
- Résultat synthétique : 9 219 pixels valides sur 9 267 dans la zone (99,482 %);
  5 644 pixels issus de A et 3 575 de B. Les zones invalides restent transparentes.
- Données de démonstration explicitement fictives.
- Wheel et archive source construits avec `python -m build`.
- Métadonnées des deux distributions acceptées par `python -m twine check`.
- Installation du wheel 0.2 dans un environnement distinct du code source, import,
  accès aux 24 maquettes et démonstration multiscène complète réussis.

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

Nouveaux contrôles : mosaïque adjacente; cohérence de toutes les bandes dans
les recouvrements; masque des nuages avant interpolation; résolutions
10/20 m et trous d'une zone polygonale; facteurs de calibration; bits QA/SCL;
saturation; rejet de capteurs/dates/bandes incompatibles; protection des
sorties; noms standards Landsat/Sentinel et décalages Sentinel; conservation
des pixels noirs et du canal alpha; NoData par bande pendant la reprojection
RGB; rapport JSON strict; chaîne CLI; ordre effectif des artistes de la carte;
reprojection et découpage des couches vectorielles.

103 avertissements de dépréciation proviennent de l'utilisation de l'opérateur
matriciel d'Affine par Rasterio dans les tests. Aucun échec de test associé.

## Portée

Ces contrôles démontrent le fonctionnement de cette version sur
les cas couverts. Ils ne valident pas tous les jeux de données SIG possibles,
l'ingestion complète de produits SAFE réels, la parité avec le rendu Esri, ni les performances à l'échelle de
rasters très volumineux. Le workflow GitHub prévoit Windows/Linux avec
Python 3.11 et 3.12; consulter ses exécutions avant d'annoncer leur réussite.

Les fichiers ont été préparés localement pour la distribution. Aucun envoi
vers TestPyPI ou PyPI n'a été réalisé.
