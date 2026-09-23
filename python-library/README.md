# Cartomize Python

**Smart Maps, Better Decisions.**

Assistant cartographique intelligent, disponible comme bibliothèque Python et fenêtre de traitement,
par **ONDON NKOUA Cédrick Belmich**.
Le moteur autonome fonctionne sans installation d'ArcGIS Pro, d'ArcPy ou de QGIS.

**Version 0.8.0a1 : calcul distribué Dask, moteur CUDA optionnel, styles QGIS enrichis et validation des moteurs natifs.** Elle reprend les règles Python
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
python -m pip install cartomize-0.8.0a1-py3-none-any.whl
```

Les dépendances sont téléchargées par pip. Aucun compte Cartomize ou accès
réseau n'est nécessaire pour traiter des fichiers locaux après installation.

## Interface graphique

```bash
python -m pip install ".[gui]"
cartomize gui
```

Depuis Python :

```python
import cartomize as cm
cm.launch()
```

L’ouverture donne accès à **Assistant cartographique** : objectif, données, zone d’étude et examen initial. Les étapes proposées sont justifiées et ouvrent les outils avec leurs entrées. **Production automatisée** conserve le parcours complet scènes → mosaïque → multibande → masque → composition colorée → export. Les indices,
la calculatrice et les statistiques restent accessibles comme outils
complémentaires. L’icône conserve ses couleurs originales ; le titre et les contrôles restent en noir, blanc et gris.
Les traitements s’exécutent en arrière-plan. L’annulation est disponible sur les moteurs par blocs et entre les pages d’un atlas ; les opérations vectorielles et un rendu cartographique individuel doivent se terminer.

La rubrique **Mise en page** donne accès aux 24 maquettes, aux formats A4/A3,
aux cadres multiples, aux légendes, aux échelles et à l’orientation. Elle
permet de contrôler la symbologie, les étiquettes et les contenus des
maquettes, puis de prévisualiser et d’exporter la carte. **Atlas cartographique**
produit une carte par entité d’une couche d’index. Les rubriques **Analyse des
couches**, **Traitements vectoriels** et **Traitements raster** donnent accès
aux diagnostics et aux opérations de la bibliothèque.

Voir le [guide de l’interface graphique](docs/DESKTOP.md) et le
[tableau des fonctionnalités](docs/FUNCTIONAL_COVERAGE.md).

## Corrections et extensions 0.7

- 34 opérations enregistrées, chaînables depuis l’API, la ligne de commande ou les formulaires de la fenêtre.
- Références aux résultats intermédiaires, y compris les sorties secondaires : `@drainage:watersheds`, `@classification:confidence`.
- Transmission des travailleurs, blocs et budgets mémoire ; validation des dépendances et publication atomique.
- Import QGIS : sous-couches GeoPackage, ordre et visibilité des groupes, couleurs catégorisées, transparence et champs d’étiquettes ; rapport explicite des propriétés non transférées.
- Masquage multibande par emprise valide, conservation des classes zéro et contrôle complet des codes raster par blocs.
- Légendes sur plusieurs colonnes et étiquettes évitant les symboles ponctuels.
- Priority-Flood, directions D8, accumulation, réseau par seuil et bassins versants ; plus court chemin sur réseau préparé.
- Recherche STAC, téléchargement contrôlé, empreintes, calibration STAC 1.0/1.1 et manifestes multisenseurs.

Voir [le guide des chaînes et nouveaux traitements](docs/PROCESSING.md).

## Fonctions introduites en 0.6

- **Planification exécutable** : examen des entrées, propositions de maquettes, relations spatiales, traitements dépendants et carte finale ; les couches complémentaires accompagnent les scènes.
- **Classification** : forêt aléatoire, arbres extrêmement aléatoires, K-moyennes par mini-lots ; validation par entités/groupes ou jeu indépendant, probabilités et modèle rechargeable sans pickle.
- **Projets** : paramètres de tous les outils, couches, cadres, contenus, résultats et état de l’assistant ; sauvegarde JSON, archive portable CMZ, annuler/rétablir les états enregistrés dans l’historique.
- **Mise en page** : modification des positions, dimensions, rotation des textes, corps et ordre des éléments ; textes mesurés, placement des étiquettes, contrôle des débordements.
- **Recettes et séries** : variables, associations de couches, migration des recettes historiques, manifestes jusqu’à 5 000 cartes, journal des résultats.
- **Révision** : empreintes des fichiers et paramètres, comparaison des changements, décision nominative liée à l’empreinte.
- **Raster** : pente, exposition, ombrage, TPI, TRI, rugosité et convolution, avec calcul parallèle par blocs.
- **Projets SIG** : inventaire QGS/QGZ sans QGIS ; lecture, copie et export des mises en page via un Python QGIS ou ArcGIS Pro installé. Cette passerelle native reste à valider dans ces moteurs.

```python
plan = cm.plan_cartography(
    ["multibande.tif", "routes.gpkg", "localites.gpkg"],
    goal="landcover", classification="supervised",
    training="echantillons.gpkg", class_column="classe",
    title="Occupation du sol", credits="Sources des données",
)
cm.run_plan(plan, "nouvelle_production", workers=4)
```

La classification supervisée exige des références fournies par l’utilisateur. Sans références, les groupes spectraux ne reçoivent pas de signification inventée. Lire le [guide des nouvelles fonctions](docs/AUTOMATION.md).

## Examen initial et connexions

```python
rapport = cm.assess_project(["occupation.tif", "routes.gpkg"], goal="landcover")
print(rapport["issues"], rapport["steps"])
# Pour des scènes : cm.assess_project("scenes", data_kind="scenes")
```

**Résultats du projet** transmet les sorties aux outils suivants. **Contrôler la carte** examine les géométries, champs, classes échantillonnées et contenus. **Préparer l’atlas** reprend couches et habillage. Lire l’[audit détaillé de tous les outils](docs/TOOL_AUDIT.md) pour les fonctions complètes dans leur périmètre, partielles ou absentes.

## Analyse du projet et NoData

La rubrique **Analyse du projet** importe plusieurs couches, détecte les fonds
périphériques, prépare des copies masquées et propose des classes. Le bouton
**Appliquer à la mise en page** transmet les couches et la nomenclature éditée
au rendu cartographique. **Rétablir les sources** recharge les fichiers initiaux.

```python
projet = cm.prepare_project([
    {"data": "occupation.tif", "classes": {
        2: ("Forêt primaire", "#26743b"),
        3: ("Forêt secondaire", "#88ad56"),
    }},
    "routes.gpkg", "localites.gpkg",
], "resultats/analyse_01")
projet.compose(title="Occupation du sol").export("carte.pdf")
# Recharger le plan ou retrouver les sources sans masquage supplémentaire :
projet = cm.load_project("resultats/analyse_01/project.json")
original = cm.load_project(projet.manifest, original_sources=True)
```

Les fonds non déclarés sont une inférence spatiale, jamais une certitude.
Les rasters binaires 0/1 et les classes documentées sont protégés par défaut.
Les libellés ne sont pas devinés à partir des codes. Voir le
[fonctionnement des masques](docs/PROJECT_ANALYSIS.md) et le
[bilan des demandes](docs/REQUEST_AUDIT.md).

## Automatiser la production depuis Python

```python
import cartomize as cm

production = cm.cartographic_workflow(
    "donnees/scenes", "resultats/production_01",
    aoi="zone.gpkg",
    layers=["routes.gpkg", "localites.gpkg", "limites.gpkg"],
    composition="natural", title="Carte de la zone d'étude",
    credits="Sources et auteur", formats=("pdf", "png"),
)
print(production.multiband, production.maps)
```

Le répertoire de production doit être nouveau. Les produits sont préparés
ensemble avant leur enregistrement final. La reconnaissance automatique
couvre Landsat C2 L2 SR et Sentinel-2 L2A; d'autres données peuvent être
fournies en Python par des objets `Scene` et `Band` explicites.

## Algèbre raster et indices spectraux

```python
import cartomize as cm

cm.spectral_indices("multibande.tif", "indices.tif",
                    ["NDVI", "EVI", "SAVI", "NDMI"], workers=4)
cm.calculate("where((nir-red)/(nir+red) > 0.4, 1, 0)",
             {"nir": ("multibande.tif", 4), "red": ("multibande.tif", 3)},
             "seuil.tif")
cm.focal("ndvi.tif", "moyenne_locale.tif", statistic="mean", size=5)
cm.reduce_rasters(["ndvi_2020.tif", "ndvi_2026.tif"], "moyenne_temporelle.tif")
```

Le catalogue comprend 18 indices documentés et accepte des définitions
supplémentaires avec `register_index`. Le calculateur accepte des expressions
arithmétiques, logiques, conditionnelles et statistiques. Les bandes doivent
être nommées ou affectées explicitement, et leurs valeurs correctement calibrées.

Les blocs bornent les données chargées en mémoire. Plusieurs indices partagent
une même lecture des bandes et peuvent être calculés sur plusieurs threads.
Sur le benchmark local documenté, trois indices sur 2 048 × 2 048 pixels passent
de 2,55 s (appels séparés) à 1,37 s (traitement groupé, quatre threads).
Ce résultat dépend du matériel et du jeu d'essai; les données de sortie sont identiques.

- [Formules, opérations, masques et paramètres](docs/RASTER_CALCULATIONS.md)
- [Protocole et résultats de performances](docs/PERFORMANCE.md)

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

## Des scènes satellite à la carte

La nouvelle chaîne reconnaît les bandes Landsat C2 L2 et Sentinel-2 L2A,
aligne les grilles, applique les facteurs de calibration et masques de qualité,
assemble les scènes en GeoTIFF multibande et découpe selon la zone d'étude.
Elle exporte aussi l'origine des pixels et un rapport de couverture.

```python
scenes = cm.discover_scenes("donnees/scenes")
image = cm.prepare_imagery(
    scenes, "resultats/multibande.tif", aoi="zone.gpkg",
    band_order=["blue", "green", "red", "nir"],
    target_crs="EPSG:32733",  # À adapter à votre zone.
)
carte = cm.compose_map([
    {"data": "routes.gpkg", "name": "Routes"},
    {"data": "localites.gpkg", "name": "Localités", "labels": "auto"},
    {"data": image.path, "rgb": "natural"},
], aoi="zone.gpkg", title="Ma carte")
carte.export("resultats/carte.pdf")
```

Les couches sont ordonnées automatiquement par rôle; `role` et `zorder`
permettent de corriger l'inférence. Une composition colorée n'est pas une
classification d'occupation du sol. Les sources sans métadonnées reconnues
peuvent être décrites explicitement par `Scene` et `Band`.

Voir le [guide détaillé et les principes cartographiques](docs/IMAGERY_WORKFLOW.md)
et la démonstration `python examples/imagery_workflow.py`.

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
`raster.reproject` complètent les traitements. Les transformations de ce module écrivent
une seule bande; elles ne modifient pas les fichiers sources.

Les masques, NoData, NaN et Inf sont exclus des calculs. Un zéro valide est
conservé. Le diagnostic individuel `raster.inspect` propose des valeurs NoData potentielles
sans les appliquer. `prepare_project` applique les règles documentées de
préparation dans des copies ; `keep_values` protège les valeurs valides. Les matrices de changement exigent des grilles identiques.
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

Le guide [EXECUTION](docs/EXECUTION.md) décrit les moteurs de calcul, leur installation et leur portée. Le GPU est implémenté pour l’algèbre, les indices et les réductions ; sa validation sur matériel CUDA reste à réaliser. Le calcul distribué est testé sur des processus réels.
