# Architecture et périmètre 0.5.0a1

## Provenance technique

Dépôt : https://github.com/cedrick14/cartomize-qgis

Branche source : `arcgispro-build-10.5.1.3`.
Commit : `4790f0e152834725d989e336199f799782bc3680`.
Édition : Cartomize for ArcGIS Pro 10.5.1.

Le dossier `arcgis-build/source` contient l'extension C#/WPF, les services
natifs Esri et une boîte à outils Python ArcPy. La bibliothèque reprend les
modules Python indépendants d'ArcPy et les maquettes de cette édition.
Les dix modules repris sont conservés dans `_core`, à usage interne.
Leur version interne 10.5.1 exprime leur provenance; la version du nouveau
paquet est 0.5.0a1. Les fichiers originaux ne sont pas modifiés.

## Fonctionnalités

| Composant | Réutilisation et nouveau fonctionnement |
|---|---|
| Maquettes | 24 JSON originaux, validation et conversion en millimètres conservées |
| Analyse des champs | Règles de rôle, champ d'étiquette et champ thématique d'ArcGIS Pro, adaptateur GeoPandas |
| Analyse raster | Profils et inférence originaux, lecture/masque Rasterio |
| Cartographie | Nouveau rendu Matplotlib, cadres multiples, échelle géodésique locale, nord vrai, légendes |
| Géométrie | GeoPandas/Shapely : clip, overlay, sjoin, dissolve, buffer, réparation et audit |
| Mesures | Distances en mètres, surfaces m²/ha/km² et conversion des unités projetées |
| Raster | NDVI/différence normalisée, reclassification, découpage, reprojection, statistiques zonales, surfaces et transitions |
| Imagerie | Découverte des scènes, calibration, masques, mosaïque cohérente, multibande, AOI, compositions RGB/RGBA et traçabilité |
| Superposition | Ordre par rôle, styles des routes/limites/localités et explication par layer_plan |
| Algèbre raster | Interpréteur AST sans exécution Python, traitement par blocs, lecture commune et calculs concurrents |
| Indices spectraux | 18 formules documentées, paramètres et registre extensible |
| Statistiques | Voisinages avec marges de blocs et synthèse multirasters |
| Interface graphique | Qt facultatif, assistant cartographique et treize rubriques complémentaires, tâches en arrière-plan, progression et annulation |
| Production | Atlas, CLI, wheel, distribution source et procédure PyPI |

## Choix techniques

- Aucun import `arcpy`, `qgis` ou composant natif Esri à l'exécution.
- Objets GeoPandas standards, sans nouvelle classe concurrente de GeoDataFrame.
- CRS explicite, entrées copiées pour les opérations vectorielles.
- Masques déclarés prioritaires; le diagnostic individuel reste en lecture seule. Le nouveau parcours de projet applique les fonds périphériques retenus dans des copies réversibles.
- Écritures raster temporaires puis remplacement atomique de chaque fichier, sources protégées. Les trois fichiers d’un produit multiscène sont remplacés successivement; une panne système pendant cette phase peut interrompre la livraison du groupe.
- Les grands calculs NDVI/reclassification et comptages sont lus par fenêtres.
- Les exports utilisent des images raster rééchantillonnées à 2048 pixels par
  dimension par défaut. `max_raster_size` ajuste cette limite d'affichage.
- La taille physique A4/A3 n'est pas recadrée à l'export.
- Aucun téléchargement de fond de carte, télémétrie, connexion ou envoi de données automatique.

## Limites explicites

Il s'agit d'une première bibliothèque alpha, et non du port complet de
l'interface ArcGIS Pro. Elle n'ouvre pas les projets APRX, ne produit pas de
PAGX, et ne reprend pas les moteurs natifs C# ni toute l’automatisation de choix de maquette de l’extension ; la proposition Python utilise l’objectif et le nombre de cadres. Les 24 maquettes sont accessibles et
rendus par un nouveau moteur; la parité pixel à pixel avec Esri n'est pas visée.

La suppression de collisions d'étiquettes est une heuristique simple et peut
masquer des étiquettes dans les zones denses. Les titres longs peuvent exiger
une adaptation de la maquette. Les passages de l'antiméridien et les cartes
polaires demandent une projection et des emprises préparées par l'utilisateur.

Les surfaces sont planaires et dépendent du choix de projection. La barre
d'échelle exprime une distance géodésique locale, pas une échelle uniforme
sur toute une carte à grande étendue. Les statistiques zonales recoupent
chaque zone indépendamment, sans supprimer les chevauchements.

Les calculs à grande étendue peuvent nécessiter beaucoup de mémoire pour
les géométries, le découpage raster, ou une zone individuelle. La validation
locale est réalisée sur Linux/Python 3.12; un workflow fournit une matrice
Windows/Linux/Python 3.11 et 3.12. Ne pas présenter ces autres exécutions
comme réussies avant d'avoir consulté leurs résultats.

## Références techniques

- https://geopandas.org/en/stable/docs/reference/api/geopandas.overlay.html
- https://geopandas.org/en/stable/docs/reference/api/geopandas.sjoin.html
- https://rasterio.readthedocs.io/en/stable/topics/masks.html
- https://packaging.python.org/en/latest/tutorials/packaging-projects/

Le [guide imagerie](IMAGERY_WORKFLOW.md) précise les formats reconnus, les masques,
les contraintes scientifiques et les fonctionnalités encore à développer.

Le moteur de calcul, ses paramètres de mémoire et ses limites sont décrits
dans [Algèbre raster](RASTER_CALCULATIONS.md). Les commandes graphiques sont
décrites dans [Interface graphique](DESKTOP.md).

## Chaîne cartographique

`workflow.cartographic_workflow` enchaîne l'identification des scènes,
`prepare_imagery`, `color_composite`, `compose_map` et les exports. Un
répertoire de production neuf est publié après la réussite de toutes les
opérations. L'annulation et les erreurs nettoient les produits temporaires.
La page Production automatisée appelle la même API que les scripts Python.
L'icône originale est distribuée dans `cartomize/assets`.

## Accès aux fonctions cartographiques

`desktop_layout` expose les maquettes, les cadres et les contenus au moteur
`Map`. `desktop_tools` expose les diagnostics et les traitements existants.
La page Mise en page et la page Atlas partagent la même configuration.
Leur aperçu utilise le rendu réel, dans le fil de traitement existant.
Le [tableau fonctionnel](FUNCTIONAL_COVERAGE.md) distingue la disponibilité
dans Python des fonctions nécessitant encore un portage natif.

## Préparation d’un projet de couches

`project.analyze_project` rassemble les diagnostics. `project.prepare_project`
appelle `nodata.mask_background`, dénombre les classes présentes et prépare un
plan JSON. `nodata` associe un échantillonnage spatial conservateur à un
étiquetage des composantes connexes par tuiles. Seules les composantes de fond
reliées au bord sont supprimées du masque de validité ; les bandes restent
identiques. Les valeurs NoData explicitement saisies ont une portée globale.
Le masque interne GeoTIFF accompagne le fichier lors des déplacements.
`desktop_project` expose l’analyse, la nomenclature et le rétablissement des
sources. Le plan charge les classes dans `MappingPage`, puis dans `Map`.

Les tableaux raster sont limités aux tuiles ; les métadonnées de composantes
croissent avec leur nombre et celui des tuiles. La limite de composantes ne
constitue pas une limite stricte de mémoire du processus.
