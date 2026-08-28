# Parité fonctionnelle avec Cartomize QGIS 10.5.1

| Fonction QGIS | Équivalent ArcGIS Pro livré | Statut |
| --- | --- | --- |
| Panneau Cartomize | DockPane WPF | Source native créée |
| Menu et barre d'outils | Onglet Cartomize du ruban | Source native créée |
| Fournisseur Processing | Commandes et services natifs du DockPane ; `.pyt` autonome dans les sources | Adapté au modèle ArcGIS Pro |
| Audit de projet | `AuditProject` | Porté |
| Autopilote | `AutopilotMap`, 18 objectifs, 4 profils, 3 propositions | Porté |
| Création de mise en page | `CreateLayout` avec `arcpy.mp` | Porté |
| 24 maquettes hors ligne | 24 JSON validés | Porté intégralement |
| Analyse vectorielle | mêmes rôles, règles multilingues, champs et géométries | Porté |
| Analyse raster | Raster Engine : profilage, NoData, classes, anomalies et bandes | Règles QGIS transposées ; lecture native ArcGIS par `PixelBlock` |
| Analyse du projet | synthèse, audit, graphe de relations et pile de couches | Porté |
| Production par lots | manifeste QGIS v1, 5 000 cartes, sorties multiples | Porté |
| Recettes réutilisables | lecture QGIS v1 et ArcGIS Pro v1 | Porté |
| MapOps | sources, CRS, emprises, données, styles et mises en page | Porté |
| PDF, PNG, JPEG, TIFF, SVG | `CreateExportFormat` et `Layout.export` | Porté |
| Fond de carte hors légende | `LegendElement.removeItem()` uniquement | Porté et testé |
| QML / QPT | Renderers, LYRX et PAGX | Porté dans les formats natifs ArcGIS Pro |
| Visite guidée QGIS | aide du panneau | À enrichir après test UX Windows |
| Validation humaine certifiée | checklist, statut et certificat SHA-256 | Noyau porté |
| Catalogue communautaire en ligne | non activé automatiquement | Reporté pour préserver le fonctionnement hors ligne |

## Différences intentionnelles

ArcGIS Pro ne prend pas en charge les plugins Python UI comme QGIS.
L'interface et les traitements du complément sont donc en C#/WPF avec le SDK
.NET ArcGIS Pro. Les rendus reposent sur les renderers et colorizers ArcGIS
Pro, et les styles enregistrés par le Raster Engine sont des fichiers LYRX.

Les zones `chart` et `table` des maquettes sont créées comme emplacements réservés éditables. Leur liaison automatique à un graphique ou une table métier exige une source et des champs choisis par l'utilisateur ; Cartomize ne les devine pas sans preuve.
