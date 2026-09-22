# Architecture et périmètre 0.1.0a1

## Base retrouvée

Dépôt : https://github.com/cedrick14/cartomize-qgis

Branche source : `arcgispro-build-10.5.1.3`.
Commit : `4790f0e152834725d989e336199f799782bc3680`.
Édition : Cartomize for ArcGIS Pro 10.5.1.

Le dossier `arcgis-build/source` contient l'extension C#/WPF, les services
natifs Esri et une boîte à outils Python ArcPy. La bibliothèque reprend les
modules Python indépendants d'ArcPy et les maquettes de cette édition.
Les dix modules repris sont conservés dans `_core`, à usage interne.
Leur version interne 10.5.1 exprime leur provenance; la version du nouveau
paquet est 0.1.0a1. Les fichiers originaux ne sont pas modifiés.

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
| Production | Atlas, CLI, wheel, distribution source et procédure PyPI |

## Choix techniques

- Aucun import `arcpy`, `qgis` ou composant natif Esri à l'exécution.
- Objets GeoPandas standards, sans nouvelle classe concurrente de GeoDataFrame.
- CRS explicite, entrées copiées pour les opérations vectorielles.
- Masques déclarés prioritaires; les suggestions heuristiques restent un diagnostic.
- Écritures raster temporaires puis remplacement atomique, sources protégées.
- Les grands calculs NDVI/reclassification et comptages sont lus par fenêtres.
- Les exports utilisent des images raster rééchantillonnées à 2048 pixels par
  dimension par défaut. `max_raster_size` ajuste cette limite d'affichage.
- La taille physique A4/A3 n'est pas recadrée à l'export.
- Aucun téléchargement de fond de carte, télémétrie, connexion ou envoi de données automatique.

## Limites explicites

Il s'agit d'une première bibliothèque alpha, et non du port complet de
l'interface ArcGIS Pro. Elle n'ouvre pas les projets APRX, ne produit pas de
PAGX, et ne reprend pas les moteurs natifs C# ni toute l'automatisation
de choix de maquette de l'extension. Les 24 maquettes sont accessibles et
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
