# Des scènes à la carte — Cartomize 0.2.0a1

## Le principe

Une carte assemble des informations géoréférencées selon un objectif de
communication. L'image fournit un fond ou une information thématique; les
routes, cours d'eau, limites et localités apportent le contexte. La mise en
page ajoute le titre, les légendes, l'échelle, le nord et les sources.
La cohérence géographique exige des systèmes de coordonnées correctement
déclarés; la cohérence visuelle exige un ordre et une symbologie adaptés.
Voir le [guide de production cartographique QGIS](https://docs.qgis.org/3.44/en/docs/gentle_gis_introduction/map_production.html).

Trois opérations sont distinctes :

| Opération | Effet |
|---|---|
| Mosaïque | Réunit spatialement plusieurs scènes pour couvrir une plus grande zone |
| Assemblage des bandes | Conserve plusieurs mesures spectrales dans un même GeoTIFF multibande |
| Composition colorée | Affecte trois bandes aux canaux rouge, vert et bleu de l'affichage |

La bibliothèque combine la mosaïque et l'assemblage dans une seule écriture
sur une grille commune. À chaque pixel, elle choisit **une scène pour toutes
les bandes**, pour éviter de mélanger des acquisitions dans un même spectre.
L'emprise de travail est limitée dès le départ par la zone d'étude; le masque
polygonal est appliqué pendant l'écriture. Il n'est pas nécessaire d'écrire
une immense mosaïque intermédiaire avant de la découper.

## Utilisation sur des produits standards

Entrées reconnues automatiquement : Landsat Collection 2 Level 2 Surface
Reflectance, et Sentinel-2 L2A avec noms standards et métadonnées SAFE.
Les archives doivent être décompressées. Garder les fichiers QA/SCL et,
pour Sentinel, `MTD_MSIL2A.xml` dans l'arborescence du produit.

```python
import cartomize as cm

scenes = cm.discover_scenes("donnees/scenes")
# Une liste de fichiers sélectionnés est également acceptée.
for scene in scenes:
    print(scene.scene_id, scene.acquired, list(scene.bands))

image = cm.prepare_imagery(
    scenes,
    "resultats/multibande.tif",
    aoi="donnees/zone_etude.gpkg",
    band_order=["blue", "green", "red", "nir", "swir1", "swir2"],
    target_crs="EPSG:32733",  # Exemple : choisir une projection adaptée au lieu.
    resolution=30,           # Mètres, choix explicite de l'utilisateur.
)

cm.color_composite(image.path, "resultats/naturelle.tif", bands="natural")
cm.color_composite(image.path, "resultats/vegetation.tif", bands="vegetation")
cm.raster.ndvi(image.path, "resultats/ndvi.tif", red=3, nir=4)

carte = cm.compose_map([
    {"data": "donnees/localites.gpkg", "name": "Localités", "labels": "auto"},
    {"data": "donnees/routes.gpkg", "name": "Routes"},
    {"data": "donnees/zone_etude.gpkg", "name": "Limites", "role": "boundaries"},
    {"data": image.path, "name": "Image satellite", "rgb": "natural"},
], aoi="donnees/zone_etude.gpkg", crs="EPSG:32733",
   title="Ma zone d'étude", credits="Sources et auteur à renseigner")
print(carte.layer_plan())  # Ordre explicable, du fond au premier plan.
carte.export("resultats/carte.pdf")
```

Les numéros du NDVI correspondent à `band_order`, à partir de 1. Les facteurs
de calibration sont déjà appliqués dans le produit : ne pas les appliquer
une deuxième fois. Le GeoTIFF multibande conserve les valeurs scientifiques;
les fichiers RGBA sont destinés à la visualisation.

Sans `resolution`, la résolution la plus grossière des bandes sélectionnées,
transformée dans le CRS cible, est utilisée. Sans `target_crs`, le CRS de la
première bande est utilisé s'il est projeté. Des données en longitude/latitude
exigent un CRS cible projeté explicite.

## Contrôles et traçabilité

- Même capteur déclaré et même niveau de traitement exigés. Aucune
  harmonisation radiométrique intercapteurs n'est supposée.
- Dates identiques par défaut. `allow_mixed_dates=True` autorise explicitement
  une mosaïque multitemporelle; ce choix est enregistré dans le rapport.
- Calibration native avant reprojection. Pour Landsat C2 L2 SR : DN ×
  0,0000275 − 0,2; DN nul exclu. Pour Sentinel L2A : quantification et décalages
  lus dans les métadonnées, sans supposer un facteur universel.
- QA_PIXEL Landsat : exclusion des pixels de remplissage, nuages, cirrus,
  nuages dilatés, ombres et neige. QA_RADSAT, lorsqu'il existe : exclusion
  conservatrice de toute valeur non nulle. Son absence est visible dans le rapport.
- SCL Sentinel : conservation des classes 2, 4, 5, 6 et 7; exclusion des
  pixels invalides, saturés, ombres de nuages, nuages, cirrus et neige.
  La classe 7 reste incertaine; ce masque n'est pas une garantie d'absence de nuages.
- Les masques sont appliqués **avant** l'interpolation des bandes. Leur
  reprojection utilise toujours le plus proche voisin.
- Un pixel de sortie exige toutes les bandes valides. `overlap="first"`
  privilégie la première scène de la liste; `"last"` privilégie la dernière.
  L'ordre de découverte est date puis identifiant; il peut être réordonné.
- Les zones non couvertes restent NoData, sans reconstruction inventée.
- `multibande_source_index.tif` indique la scène retenue : 0 = absent,
  1 = première scène, 2 = deuxième, etc. Le fichier JSON fournit les chemins,
  dates, paramètres, résolutions, calibration et couverture réelle de la zone.
- Les bandes, la mosaïque et le RGBA sont traités par fenêtres. Les bandes
  calibrées utilisent des fichiers temporaires, ce qui demande de l'espace disque.

Les règles de calibration proviennent de l'[USGS](https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products)
et de [Copernicus](https://sentiwiki.copernicus.eu/web/s2-products).
Voir aussi les [bits QA Landsat](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands),
le [traitement Sentinel-2](https://sentiwiki.copernicus.eu/web/s2-processing)
et les [principes de reprojection GDAL](https://gdal.org/en/stable/programs/gdalwarp.html).

## Autres fichiers et choix explicites

Les fichiers au nom inconnu demandent une description; la bibliothèque ne
devine pas qu'une bande B4 représente le rouge sur tous les capteurs.
Exemple pour une scène déjà calibrée :

```python
scene = cm.Scene(
    "scene_A",
    bands={"red": cm.Band("rouge.tif", unit="reflectance"),
           "nir": cm.Band("proche_infrarouge.tif", unit="reflectance")},
    sensor="mon_capteur", acquired="2026-08-17",
    quality="pixels_valides.tif", quality_kind="valid_mask",
)
image = cm.prepare_imagery([scene], "sortie.tif")
```

`Band` permet aussi `index`, `scale`, `offset` et `nodata`. Pour un masque
personnalisé, zéro signifie invalide et toute autre valeur valide. Sans masque
de qualité disponible, `mask_clouds=False` doit être demandé explicitement.
Les données physiques doivent être correctement décrites par l'appelant.

Les compositions nommées utilisent les descriptions des bandes :

| Composition | Rouge affiché | Vert affiché | Bleu affiché |
|---|---|---|---|
| `natural` | red | green | blue |
| `vegetation` | nir | red | green |
| `swir` | swir2 | nir | red |
| `agriculture` | swir1 | nir | blue |

Trois indices explicites sont également acceptés : `bands=(4, 3, 2)`.
Sentinel B8A est nommée `nir_narrow`, distincte de B8/`nir`. Les limites
d'étirement sont estimées sur un aperçu borné, commun à toute l'image.
`percentiles=(2, 98)` et `gamma=1` sont modifiables. Le canal alpha distingue
les pixels absents des pixels noirs valides.

## Superposition et habillage

Ordre par défaut : image de fond, occupation du sol, surfaces thématiques,
autres polygones, eau, lignes, routes, voies ferrées, limites, localités, points.
Les étiquettes se placent au-dessus; les limites administratives sont sans
remplissage et les routes ont un fin liseré blanc.

L'inférence utilise le nom, le type géométrique et les paramètres fournis.
Elle reste une heuristique : une couche ambiguë peut demander `role=`.
Les options `color`, `alpha`, `linewidth`, `zorder` et `labels` permettent
d'ajuster le résultat. `Map(auto_order=False)` conserve l'ordre d'ajout.
Un polygone thématique opaque peut volontairement masquer l'image : régler
sa transparence pour une lecture simultanée. Les collisions d'étiquettes
utilisent le mécanisme simple existant; certaines étiquettes peuvent être omises.

Cette version lit des données, pas les styles ou projets `.qgz`/`.aprx`.

## Ligne de commande et démonstration

```bash
cartomize scenes donnees/scenes
cartomize prepare donnees/scenes multibande.tif --bands blue,green,red,nir --aoi zone.gpkg --crs EPSG:32733 --resolution 30
cartomize composite multibande.tif naturelle.tif --rgb natural
cartomize map multibande.tif carte.pdf --rgb vegetation --title "Végétation"
python examples/imagery_workflow.py
```

La démonstration génère **deux scènes entièrement fictives**, cinq bandes à
10/20 m, un masque de nuages et des couches vectorielles. Elle produit les
GeoTIFF, le NDVI, le rapport, un comparatif PNG et une carte PDF/PNG. Ces
résultats illustrent le traitement, sans constituer des observations de terrain.

## Ce qui reste à développer

Une composition colorée ne produit pas une classification d'occupation du
sol. Il faut un module distinct, des classes définies, des données
d'apprentissage si nécessaire et une validation indépendante. Les extensions
suivantes seraient utiles : classification supervisée et matrice de confusion,
sélection temporelle par score de qualité, harmonisation intercapteurs,
meilleur placement des étiquettes et import de styles SIG.

Cette alpha ne fait ni correction atmosphérique de produits bruts, ni
égalisation entre scènes, ni téléchargement automatique, ni correction des
erreurs de géoréférencement. Elle n'a pas encore été éprouvée sur de grandes
collections satellitaires réelles. Choisir une résolution plus fine ne crée
pas de détails supplémentaires. Pour des scènes éloignées, sélectionner une
zone et une projection adaptées au lieu d'une mosaïque mondiale implicite.
