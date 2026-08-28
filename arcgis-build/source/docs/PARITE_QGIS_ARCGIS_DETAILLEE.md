# Parité Cartomize QGIS 10.5.1 → ArcGIS Pro 10.5.1

Ce document décrit le portage fonctionnel. Les règles métier, les maquettes,
les noms Cartomize et les formats JSON restent communs. Seuls les objets du
SIG hôte changent : PyQGIS dans QGIS, ArcPy et le SDK .NET dans ArcGIS Pro.

## Interface

| QGIS 10.5.1 | ArcGIS Pro 10.5.1 | État |
|---|---|---|
| Une action principale Cartomize | Une action « Ouvrir Cartomize » | Identique |
| 7 onglets | 7 onglets dans le même ordre | Identique |
| Thème natif QGIS | Ressources de thème natives ArcGIS Pro | Adaptation native |
| Texte du thème, sélection bleue | Texte du thème, sélection ArcGIS Pro | Adaptation native |
| Version 10.5.1 | Version 10.5.1 | Identique |

Ordre des onglets : Automatisation, Projet, Mise en page, Qualité,
Production, Communauté, Système.

## Noyaux communs

| Fonction | Parité ArcGIS Pro |
|---|---|
| Raster Engine | Même noyau déterministe, même analyse NoData, mêmes classes, mêmes anomalies, mêmes 16 profils thématiques |
| Analyse vectorielle | Mêmes indices multilingues, rôles, champs d’étiquette et champs thématiques, mêmes limites d’échantillon |
| Relations du projet | Même graphe par emprises, mêmes priorités et mêmes relations contains/within/overlaps |
| Piles de couches | Même règle de conservation des couches visibles et des fonds de carte, fonds placés sous les couches thématiques |
| Audit | Même pondération, mêmes seuils et contrôles équivalents ArcGIS Pro |
| MapOps | Même instantané des sources, CRS, emprises, données, styles et mises en page |
| Recettes | Lecture du schéma QGIS v1 et du schéma ArcGIS Pro v1 |
| Production | Lecture du manifeste QGIS v1, limite de 5 000 cartes, sorties multiples |
| Validation humaine | Même checklist, même statut et même empreinte de certificat |

## Mise en page et formats

Les 24 fichiers JSON de maquettes sont copiés sans modification depuis le
plugin QGIS 10.5.1. Les éléments restent éditables dans ArcGIS Pro : cadres,
textes, légende, barre d’échelle, flèche nord, formes, tableaux et graphiques.

| QGIS | ArcGIS Pro | Raison |
|---|---|---|
| QPT | PAGX | Format natif éditable de mise en page ArcGIS Pro |
| PDF | PDF | Identique |
| SVG | SVG | Identique |
| PNG | PNG | Identique |
| JPEG | JPEG | Identique |
| TIFF | TIFF | Identique |
| Grille QGIS | Grille de style ArcGIS Pro | Objet natif du cadre cartographique |

## Contrats des neuf outils

1. Contrôler la qualité cartographique du projet.
2. Créer automatiquement une carte.
3. Rejouer une recette Cartomize.
4. Produire une série de cartes Cartomize.
5. Créer une mise en page Cartomize.
6. Analyser le projet.
7. Vérifier les changements MapOps.
8. Analyser un raster avec Raster Engine.
9. Analyser une couche vectorielle.

Les libellés visibles restent courts et professionnels. Le terme
« intelligence » n’est pas affiché dans l’interface ArcGIS Pro.

## Garanties

- Aucune suppression de couche pendant la création d’une mise en page.
- Le fond de carte peut être exclu de la légende sans être retiré de la carte.
- Les analyses vectorielles et raster sont non destructives.
- Les maquettes, recettes, rapports et manifestes sont validés avant usage.
- Les couleurs, polices et états de sélection du panneau suivent le thème
  ArcGIS Pro au lieu d’imposer une charte parallèle.
