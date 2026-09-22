# Cartomize Python

**Smart Maps, Better Decisions.**

Bibliothèque Python de cartographie et d'analyse spatiale, dérivée des sources
de **Cartomize for ArcGIS Pro 10.5.1**, par **ONDON NKOUA Cédrick Belmich**.
Elle fonctionne sans installation d'ArcGIS Pro, d'ArcPy ou de QGIS.

**Version 0.1.0a1 : première version alpha.** Elle reprend les règles Python
et les 24 maquettes originales. Le rendu autonome et les traitements
GeoPandas/Rasterio sont nouveaux : cette version ne prétend pas reproduire
toutes les fonctions de l'extension native. Aucun paquet n'a encore été
publié sur PyPI dans le cadre de cette livraison.

## Installation

Python 3.11 ou plus récent. Depuis ce dossier :

```bash
python -m pip install .
```

Ou, avec le fichier wheel fourni :

```bash
python -m pip install cartomize-0.1.0a1-py3-none-any.whl
```

Les dépendances sont téléchargées par pip. Aucun compte Cartomize ou accès
réseau n'est nécessaire pour traiter des fichiers locaux après installation.

## Produire une carte

```python
import cartomize as cm

villages = cm.read_file("villages.gpkg")
carte = cm.Map(
    title="Localisation des villages",
    subtitle="District de Mvouti",
    crs="EPSG:32733",
    credits="Sources : données de terrain | Auteur : Cédrick Belmich",
)
carte.add_layer(villages, name="Villages", labels="nom", color="#254f54")
carte.export("villages.pdf", dpi=300)
```

Les légendes, la flèche du nord vrai et l'échelle sont activées par défaut.
Les exports PDF, PNG et SVG conservent le format physique de la page.
Pour un raster, déclarer explicitement les libellés et couleurs des classes :

```python
carte = cm.Map(title="Occupation du sol", crs="EPSG:32733")
carte.add_layer("occupation.tif", name="Occupation du sol", classes={
    1: ("Forêt dense", "#1b5e20"),
    2: ("Forêt perturbée", "#81c784"),
    3: ("Agriculture", "#e8c46a"),
})
carte.export("occupation.png", dpi=300)
```

## Traitements vectoriels compatibles avec GeoPandas

Les fonctions retournent des **GeoDataFrame/GeoSeries standards** : les
méthodes habituelles de GeoPandas restent utilisables.

```python
zones = cm.buffer(villages, 500, metric_crs="EPSG:32733")  # mètres
zones["surface_ha"] = cm.area(zones, metric_crs="EPSG:32733")
intersection = cm.overlay(zones, cm.read_file("forets.gpkg"))
jointure = cm.sjoin(villages, cm.read_file("districts.gpkg"), predicate="within")
fusion = cm.dissolve(intersection, by="nom")
rapport = cm.vector.analyze(villages, name="Villages")
```

Également disponibles : `clip`, `reproject`, `from_xy`, `length`, `validate`,
`make_valid`. Les fonctions combinant deux couches alignent le CRS de la
seconde sur celui de la première. Les mesures exigent un CRS projeté, fourni
par les données ou par `metric_crs`; les distances ne sont jamais calculées
en degrés. Les surfaces sont planaires : choisir une projection adaptée à
l'étendue et au niveau de précision recherché.

## Traitements raster

```python
cm.raster.ndvi("multispectral.tif", "ndvi.tif", red=3, nir=4)
cm.raster.reclassify("classes.tif", "foret.tif", {1: 1, 2: 0, 3: 0})
statistiques = cm.raster.zonal_stats("ndvi.tif", zones)
surfaces = cm.raster.class_areas("classes.tif", unit="ha")
changements = cm.raster.change_matrix("classes_2000.tif", "classes_2026.tif")
diagnostic = cm.raster.inspect("classes.tif")
```

`ndvi` exige les numéros réels des bandes, à partir de 1; il ne devine pas le
capteur. Les facteurs d'échelle et décalages GDAL sont appliqués; utiliser
`scale=` et `offset=` si le produit les fournit séparément. `raster.clip` et
`raster.reproject` complètent les traitements. Les transformations écrivent
une seule bande; elles ne modifient pas les fichiers sources.

Les masques, NoData, NaN et Inf sont exclus des calculs. Un zéro valide est
conservé. Le diagnostic hérité propose des valeurs NoData potentielles sans
les appliquer. Les matrices de changement exigent des grilles identiques.
La surface raster utilise le déterminant de la transformation et les unités
du CRS projeté. Les indices et reclassifications sont traités par fenêtres;
le découpage charge l'emprise découpée en mémoire.

## Les 24 maquettes de Cartomize

```python
print(cm.list_templates())
identifiant = cm.list_templates()[0]["id"]
carte = cm.Map(template=identifiant, title="Ma carte", crs="EPSG:32733")
carte.add_layer(villages, labels="nom")
print(carte.frame_ids)
# Configurer chaque cadre avec ses limites dans son CRS si nécessaire :
# carte.set_frame("main-map", extent=(xmin, ymin, xmax, ymax))
carte.export("maquette.pdf")
```

Les identifiants exacts sont fournis par `list_templates` et `frame_ids`.
`set_frame` permet aussi de sélectionner les couches par leur nom et un CRS
particulier. Sans configuration, les cadres partagent les données et
l'emprise par défaut : une vraie carte de localisation exige des couches et
des emprises appropriées. `set_text`, `set_table` et `set_chart` remplissent
les éléments nommés des maquettes. Un tableau ou graphique non renseigné
reste vide. Le rendu Matplotlib peut différer du rendu natif Esri.

## Atlas et ligne de commande

```python
cm.atlas(carte, cm.read_file("zones.gpkg"), "atlas", name_column="nom")
```

```bash
cartomize --version
cartomize templates
cartomize inspect occupation.tif
cartomize map villages.gpkg villages.pdf --labels nom --title "Villages"
python examples/demo.py
```

La démonstration génère des **données fictives**, explicitement identifiées,
et des cartes PDF/PNG/SVG. Les fichiers existants sont protégés sauf demande
explicite `overwrite=True`. L'atlas vérifie les noms avant de produire les pages.

## Développement, provenance et publication

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

- [Guide de publication PyPI](docs/PUBLICATION.md)
- [Architecture et limites](docs/ARCHITECTURE.md)
- [Provenance des composants repris](docs/PROVENANCE.json)

Code : GNU GPL v3. Maquettes : CC BY 4.0, Cartomize / ONDON NKOUA Cédrick
Belmich. Voir `LICENSE` et `NOTICE.md`.
