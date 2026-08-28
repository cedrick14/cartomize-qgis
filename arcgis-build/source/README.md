# Cartomize 10.5.1 for ArcGIS Pro

Édition native ArcGIS Pro de Cartomize, issue du plugin QGIS 10.5.1. Elle comprend :

- un add-in C#/WPF intégré au ruban et au panneau latéral d'ArcGIS Pro ;
- des services C# utilisant directement le SDK ArcGIS Pro 3.7 pour les couches,
  géométries, rasters, rendus, mises en page et exports ;
- 24 maquettes hors ligne converties en mises en page ArcGIS Pro éditables ;
- les règles Cartomize QGIS 10.5.1 portées vers les objets natifs ArcGIS Pro :
  audit, profils vectoriels et raster, symbologie, recettes, MapOps,
  validation et production par manifeste.

## Livrables et niveau de disponibilité

Le paquet `Cartomize-ArcGISPro-10.5.1.esriAddInX` contient l’interface et les
moteurs natifs. Le dossier `toolbox` reste dans le dépôt comme implémentation
ArcPy indépendante et référence de parité; il n'est pas requis par l'add-in.
Le code source complet permet de reconstruire le paquet
sur Windows avec ArcGIS Pro 3.7, .NET 10 et Visual Studio 2026.

## Fonctions livrées

1. Auditer le projet
2. Création automatique d’une carte avec les 18 objectifs et 3 propositions QGIS
3. Créer une mise en page
4. Analyse vectorielle
5. Analyse raster
6. Analyse du projet
7. Production cartographique par manifeste QGIS v1, jusqu’à 5 000 cartes
8. Rejouer une recette
9. Contrôler les changements MapOps

Le moteur de mise en page crée de vrais cadres cartographiques, légendes,
barres d'échelle, flèches nord, textes, formes et grilles. Il exporte PDF,
SVG, PNG, JPEG et TIFF, et enregistre la maquette native ArcGIS Pro en PAGX.
Les fonds de carte restent dans la carte et dans les cadres ; Cartomize retire
seulement leurs éléments de la légende lorsque cette option est activée.

## Installation rapide

1. Fermez ArcGIS Pro.
2. Double-cliquez sur `Cartomize-ArcGISPro-10.5.1.esriAddInX`.
3. Cliquez sur **Installer le complément**.
4. Relancez ArcGIS Pro et ouvrez l’onglet **Cartomize**.

Le guide complet est dans [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Compiler l'add-in natif

Sur Windows 11 avec ArcGIS Pro 3.7 :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-addin.ps1
```

Le script restaure `Esri.ArcGISPro.Extensions30` 3.7.0.1901, compile en Release, recherche le `.esriAddInX` généré et le copie dans `release/`.

## Validation exécutée

- compilation C# x64 contre le SDK ArcGIS Pro 3.7 ;
- analyse syntaxique de la boîte `.pyt` de référence ;
- validation XML de `Config.daml` et du panneau WPF ;
- validation des 24 maquettes et de leurs limites de page ;
- test de non-régression : retirer un fond de la légende ne retire jamais la couche de la carte ;
- tests des recettes QGIS/ArcGIS, manifestes, profils vectoriels/raster,
  palettes, piles de couches et empreintes MapOps détaillées.

Exécuter localement :

```bash
python scripts/validate.py
```

Le test interactif final doit être réalisé dans ArcGIS Pro 3.7, conformément à [docs/VALIDATION.md](docs/VALIDATION.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Installation et compilation](docs/INSTALLATION.md)
- [Parité avec QGIS 10.5.1](docs/PARITE_FONCTIONNELLE.md)
- [Matrice de parité détaillée](docs/PARITE_QGIS_ARCGIS_DETAILLEE.md)
- [Recherche officielle Esri](docs/RECHERCHE_ESRI.md)
- [Validation](docs/VALIDATION.md)
- [Sécurité et données](docs/SECURITY.md)

## Licence

GNU GPL v3. ArcGIS Pro, ArcPy, Esri et `.esriAddInX` sont des technologies et marques d'Esri. Cartomize est un produit indépendant et n'est pas une extension éditée ou certifiée par Esri.
