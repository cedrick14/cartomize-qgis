# Vérification des demandes — Cartomize Python 0.5.0a1

Audit du 22 septembre 2026, fondé sur les demandes disponibles dans la
conversation, le code Python, les tests et la version ArcGIS Pro du dépôt.
**Toutes les fonctions de Cartomize ArcGIS Pro ne sont pas encore transposées.**
La version précédente possédait un diagnostic par couche ; elle ne réalisait
pas l’application complète du NoData et de la nomenclature au projet.

Le [nouvel audit outil par outil](TOOL_AUDIT.md) décrit les corrections 0.5, le parcours d’assistance et les transferts effectifs.

## État vérifié

| Demande | État et portée effective |
|---|---|
| Bibliothèque Python indépendante et utilisable avec GeoPandas | Réalisé : API installable, GeoDataFrame/GeoSeries standards, sans dépendance ArcPy/QGIS |
| Fenêtre native ouverte depuis Python | Réalisé : `cm.launch()`, 14 rubriques, fichiers importables et traitements en arrière-plan |
| Icône Cartomize dans ses couleurs normales | Corrigé : ressource originale inchangée et affichage en couleur ; titre et contrôles sobres |
| Intitulés techniques, absence du slogan « ADN ArcGIS Pro » | Réalisé dans la fenêtre ; la provenance reste dans la documentation |
| Production depuis les scènes avant les indices | Réalisé : Assistant cartographique est l’écran d’ouverture ; Production automatisée reste disponible ; indices facultatifs |
| Sélection de plusieurs scènes/bandes | Réalisé pour Landsat C2 L2 SR et Sentinel-2 L2A reconnus ; correspondance explicite Python requise pour les autres produits |
| Mosaïque, composite multibande, découpage par emprise | Réalisé : calibration et qualité, grille commune, choix cohérent des pixels entre bandes, extraction par masque |
| GeoTIFF scientifique et composition colorée | Réalisé : multibande calibré séparé du RGBA de visualisation |
| Superposition raster/vecteur, routes, limites et localités | Réalisé : ordre par rôle, reprojection au rendu, découpage vectoriel, styles et étiquettes ; rôles inférés à contrôler |
| Analyse du projet qui prépare réellement le NoData | Ajouté : analyse de plusieurs fichiers, copies masquées, rapport des valeurs retenues, classes et plan JSON |
| Retrait du fond noir et des valeurs NoData | Ajouté avec limites explicites : masques déclarés et fonds périphériques détectés ; règles explicites et valeurs à conserver disponibles |
| Préserver les zéros valides et pouvoir rétablir les sources | Réalisé et testé : binaires 0/1, îlots intérieurs, classes documentées ; sources inchangées et rechargement original |
| Nomenclature d’occupation du sol, couleurs et légende | Ajouté : métadonnées ou saisie, édition dans la fenêtre, transmission réelle à l’export ; aucune signification inventée à partir d’un code |
| Mise en page et fonctions cartographiques héritées | Partiel : 24 maquettes, cadres, encarts, textes, tableaux, graphiques, habillage, aperçu et PDF/PNG/SVG ; parité complète native non atteinte |
| Atlas et production en série | Réalisé pour une carte par entité ; les anciens manifestes batch de l’extension ne sont pas directement compatibles |
| Traitements similaires à GeoPandas | Réalisé : découpage, intersection/union/différence, jointure spatiale, dissolution, tampon, mesures et réparation ; méthodes GeoPandas disponibles |
| Algèbre raster et indices | Partiel par nature : opérateurs pris en charge, 18 indices intégrés et formules extensibles ; pas tous les algorithmes raster existants |
| Rapidité et gros volumes | Réalisé sur plusieurs moteurs : fenêtres, lectures partagées, concurrence bornée, progression et annulation ; aucune accélération universelle garantie |
| Publication et visibilité auprès des utilisateurs Python | Préparé : wheel, source, métadonnées, guide de publication et dépôt ; aucune publication PyPI/TestPyPI ni adoption communautaire acquise |

## Ce qui reste à implémenter ou à valider

- Lecture/édition complète d’un projet APRX ou QGZ, export PAGX et synchronisation
  d’une mise en page native existante.
- Portage des recettes historiques, des manifestes batch natifs et de
  l’ensemble du contrôle des changements et des validations MapOps.
- Analyse spatiale relationnelle automatique complète entre couches
  (intersections et proximités choisies automatiquement) et optimisation
  avancée de tous les styles, étiquettes et variantes de maquette.
- Classification supervisée d’occupation du sol et reconnaissance universelle
  des capteurs et produits. Une composition colorée ne classe pas l’image.
- Validation manuelle de bureau sous Windows et essais sur de grands jeux
  réels ; les tests effectués ici utilisent Linux et des jeux contrôlés.

Ces points ne sont pas présentés comme réalisés. Le nouvel outil Analyse du
projet ne reproduit pas l’intégralité de l’état, des services et des rendus
d’un projet ArcGIS Pro.

## Éléments vérifiables

- Dans la version native, `AnalyzeAutomationAsync` propose la recommandation
  et `ApplyRecommendationAsync` l’applique. Les services
  `NativeRasterAnalysisService`, `NativeRasterRecommendationService` et
  `NativeRasterOutlineService` gèrent analyse, masquage et contour.
- Dans Python, `project.py`, `nodata.py` et `desktop_project.py` réalisent
  désormais diagnostic, copies masquées, classes et application à `Map`.
- `tests/test_project.py` compare les composantes par blocs à une propagation
  indépendante, vérifie masques, classes, sources, RVB, réversibilité et erreurs.
- `tests/test_desktop.py` clique sur les vrais widgets, vérifie l’icône en
  couleur, analyse un raster, modifie la nomenclature, exporte une carte et
  rétablit les sources. Les parcours précédents restent testés.
- [Validation](VALIDATION.md), [couverture cartographique](FUNCTIONAL_COVERAGE.md)
  et [règles NoData](PROJECT_ANALYSIS.md) précisent les résultats et limites.
