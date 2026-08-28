# Historique

## 10.5.1 — 2026-08-27

- adoption de l’identité visuelle native d’ArcGIS Pro dans le DockPane ;
- restauration des sept onglets `Automatisation`, `Projet`, `Mise en page`,
  `Qualité`, `Production`, `Communauté` et `Système` ;
- alignement des noms d’outils et de leurs catégories sur le fournisseur
  Traitements de Cartomize QGIS 10.5.1 ;
- simplification du ruban à l’unique action `Ouvrir Cartomize`, conformément à
  la barre d’outils QGIS ;
- conservation de l’icône originale Cartomize, identique à celle du plugin QGIS.
- normalisation de la version visible et du manifeste à `10.5.1`.
- correction des types de texte ArcGIS Pro 3.7 : `POLYGON` pour les blocs et
  `POINT` pour les libellés ponctuels, à la place des anciennes valeurs
  `PARAGRAPH_TEXT` et `POINT_TEXT` non acceptées par ArcPy.
- adoption des ressources WPF natives d’ArcGIS Pro pour les textes, boutons,
  bordures, arrière-plans et états de sélection ; le DockPane suit désormais
  automatiquement les thèmes clair, sombre et contraste élevé.
- simplification des titres, descriptions et actions de l’interface ;
- remplacement du vocabulaire promotionnel par des libellés métier directs.
- correction de l’entrée `GPRasterLayer` : la valeur textuelle ArcGIS Pro est
  désormais résolue en nom ou chemin avant l’ouverture par `arcpy.Raster` ;
- restauration bit pour bit du noyau déterministe Raster Engine de Cartomize
  QGIS 10.5.1 (profilage, inférence et sémantique des bandes) ;
- maintien du diagnostic raster en lecture seule, avec rapport QGIS complet et
  clés de compatibilité pour les traitements ArcGIS Pro existants.

## 10.5.1-arcgispro.2 — 2026-08-27

- correction de la création de mise en page lorsque les champs facultatifs
  `Sous-titre` ou `Sources et crédits` sont laissés vides par ArcGIS Pro ;
- normalisation des valeurs textuelles ArcPy absentes (`None`) ;
- correction du conditionnement de `Config.daml` à la racine du `.esriAddInX` ;
- ajout de tests de non-régression pour les textes facultatifs.

## 10.5.1-arcgispro.1 — 2026-08-26

- première édition ArcGIS Pro issue de Cartomize QGIS 10.5.1 ;
- add-in C#/WPF pour ArcGIS Pro 3.7, .NET 10 et Visual Studio 2026 ;
- boîte à outils Python de neuf outils ;
- conversion native des 24 maquettes JSON en mises en page `arcpy.mp` ;
- audit, analyses vectorielle et raster, et synthèse du projet ;
- symbologies ArcGIS Pro réversibles sans réécriture des sources ;
- recettes v1, MapOps et exports par lots PDF/PNG/JPEG/TIFF/SVG ;
- protection contre la suppression involontaire des fonds de carte lors du nettoyage des légendes ;
- sept tests unitaires et validation statique hors ArcGIS Pro.
