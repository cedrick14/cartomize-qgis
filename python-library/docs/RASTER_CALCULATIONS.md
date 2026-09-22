# Algèbre raster et indices spectraux

## Indices spectraux

Le catalogue initial contient 18 indices : NDVI, EVI, EVI2, SAVI, OSAVI,
MSAVI, GNDVI, NDRE, NDWI, MNDWI, NDMI, NBR, NBR2, NDBI, BSI, ARVI, VARI et SR.
`list_indices()` fournit leurs noms, formules, bandes, paramètres et références.
Les indices sont calculés en valeurs physiques non multipliées par 10 000.

```python
import cartomize as cm

cm.spectral_indices(
    "multibande.tif", "indices_spectraux.tif",
    indices=["NDVI", "EVI", "SAVI", "NDMI"],
    band_map={"blue": 1, "red": 3, "nir": 4, "swir1": 5},
    parameters={"SAVI": {"L": 0.5}},
    workers=4,
)
```

Avec un produit `prepare_imagery`, les descriptions spectrales des bandes
permettent d'omettre `band_map`. Sans descriptions non ambiguës, il faut
fournir les correspondances. Les numéros commencent à 1.

Les facteurs et décalages GDAL enregistrés dans le raster sont appliqués.
`scale` et `offset` permettent de les remplacer explicitement. Les formules
avec constantes additives, notamment EVI, EVI2, SAVI et MSAVI, exigent une
réflectance correctement calibrée. Ne pas traiter directement les DN bruts
en supposant que tous les indices sont invariants au facteur d'échelle.
Le prétraitement Landsat/Sentinel assure cette conversion pour les formats
pris en charge; une réflectance déjà calibrée ne doit pas être recalibrée.

Le NDWI fourni suit McFeeters (vert/PIR). Le NDMI utilise PIR/SWIR1.
Le NDRE utilise `rededge1`. L'OSAVI suit ici la convention
`(nir-red)/(nir+red+0.16)`, sans facteur 1,16; une autre convention peut être
définie explicitement. Le MSAVI correspond à la formule explicite à racine
carrée couramment désignée MSAVI2. Aucune valeur n'est arbitrairement limitée
à l'intervalle −1/+1. Le contrôle qualité des observations précède le calcul.

Références de calibration et d'usage :
[indices Landsat USGS](https://www.usgs.gov/landsat-missions/landsat-surface-reflectance-derived-spectral-indices),
[EVI](https://www.usgs.gov/landsat-missions/landsat-enhanced-vegetation-index),
[SAVI](https://www.usgs.gov/landsat-missions/landsat-soil-adjusted-vegetation-index).
Chaque définition expose aussi la référence de sa formule. La convention
BSI est celle du champ BI du [catalogue Awesome Spectral Indices](https://github.com/awesome-spectral-indices/awesome-spectral-indices/blob/main/output/spectral-indices-dict.json).

## Indices personnalisés

```python
cm.register_index(
    "DIFFERENCE_SPECTRALE", "nir - red",
    bands=["nir", "red"], title="Différence spectrale",
)
cm.spectral_indices("multibande.tif", "difference.tif", "DIFFERENCE_SPECTRALE")
```

L'enregistrement est valable dans le processus Python courant. Un indice
personnalisé n'acquiert pas une validation scientifique par son enregistrement.
Sa définition, ses unités et son domaine d'utilisation relèvent de l'auteur.
Les paramètres numériques déclarés peuvent être modifiés à l'appel.

## Calculatrice raster

```python
cm.calculate(
    "where((nir - red) / (nir + red) > 0.4, 1, 0)",
    {"red": ("multibande.tif", 3), "nir": ("multibande.tif", 4)},
    "seuil_vegetation.tif", workers=4,
)

# Plusieurs expressions, une lecture commune des bandes par bloc.
cm.calculate(
    {"difference": "recent - ancien", "moyenne": "mean(ancien, recent)"},
    {"ancien": "indice_2020.tif", "recent": "indice_2026.tif"},
    "comparaison_temporelle.tif",
)
```

Les variables désignent un chemin, un couple `(chemin, numéro_de_bande)` ou
un objet `Band`. Un objet `Band` fournit explicitement sa calibration et
remplace celle du fichier; un chemin/couple utilise la calibration GDAL.
Un dictionnaire d'expressions crée autant de bandes de sortie que de clés.
Seules les variables effectivement utilisées sont lues.

| Famille | Syntaxe |
|---|---|
| Arithmétique | `+`, `-`, `*`, `/`, `**`, `%`, parenthèses |
| Comparaison | `<`, `<=`, `>`, `>=`, `==`, `!=`, comparaisons chaînées |
| Logique | `&`, `\|`, `^`, `~`, `and`, `or`, `not` |
| Conditions | `where(condition, valeur_vraie, valeur_fausse)` |
| Valeurs absentes | `isvalid(a)`, `coalesce(a, b)` |
| Fonctions | `sqrt`, `log`, `log10`, `exp`, `abs`, `floor`, `ceil` |
| Trigonométrie | `sin`, `cos`, `tan`, `arcsin`, `arccos`, `arctan` (radians) |
| Bornes | `minimum(a,b)`, `maximum(a,b)`, `clip(a,min,max)` |
| Statistiques entre rasters | `mean`, `sum`, `min`, `max`, `std`, `median`, `count` |
| Masques binaires QA | `bitand(a, masque)` |
| Constantes | `pi`, `e`, valeurs numériques finies |

Les opérateurs `&`, `|`, `^` et `~` sont logiques; `bitand` réalise
l'opération sur bits d'entiers non négatifs, exactement représentables
jusqu'à 2**53−1. Les fonctions statistiques combinent les arguments **à la
même position spatiale**, et non tous les pixels d'une image. `std` est
l'écart-type de population. Les variables ne peuvent pas porter le nom
d'une fonction ou d'une constante.

## Valeurs NoData et grilles

- Une opération arithmétique exclut les pixels invalides de ses opérandes.
- Division par zéro, logarithme non défini, racine négative et débordement
  du type de sortie deviennent NoData. Le zéro valide reste valide.
- `where` conserve le masque de la condition et celui de la seule branche
  sélectionnée. `coalesce(a,b)` utilise b uniquement lorsque a est invalide.
- Les statistiques multirasters ignorent les observations absentes.
  Toutes les observations absentes donnent NoData, sauf `count` qui donne 0.
- Les grilles doivent être identiques : CRS, transformation et dimensions.
  `align=True` autorise une reprojection sur la première entrée utilisée;
  elle peut donc exclure ce qui se trouve hors de cette emprise.
- `resampling="nearest"` est le défaut. L'interpolation bilinéaire ou cubique
  ne convient pas aux codes de classes. Un NoData personnalisé avec
  alignement exige un prétraitement préalable.
- Les sorties GeoTIFF sont en float32, ou float64 sur demande. Les expressions,
  sources, bandes, calibrations et paramètres de traitement sont enregistrés
  dans leurs métadonnées. Les fichiers sources sont protégés.

La syntaxe est interprétée à partir d'un arbre validé : aucun `eval`, import,
accès à un attribut, indexation Python ou appel arbitraire n'est exécuté.
Une formule fait au plus 8 192 caractères et 512 nœuds syntaxiques.

## Statistiques focales

```python
cm.focal("ndvi.tif", "ndvi_moyenne.tif", statistic="mean", size=5, workers=4)
```

Fenêtre carrée impaire de 1 à 255 pixels; moyenne, somme, minimum, maximum,
étendue, écart-type ou nombre de valeurs valides. Les marges de chaque bloc
sont lues pour éviter des discontinuités entre blocs. Les cellules hors image
ne comptent pas comme zéro. `min_valid` fixe le nombre minimal de voisins.
`preserve_nodata=True` conserve par défaut les trous du pixel central;
sa désactivation autorise explicitement leur estimation par le voisinage.

Les filtres de SciPy opèrent sur des valeurs finies et un masque de validité
séparé; les NaN ne sont pas transmis au filtre uniforme. Voir
[SciPy uniform_filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.uniform_filter.html).

## Statistiques multirasters

```python
cm.reduce_rasters(
    ["ndvi_2020.tif", "ndvi_2023.tif", "ndvi_2026.tif"],
    "ndvi_median.tif", statistic="median", min_valid=2,
)
```

Disponibles : moyenne, somme, minimum, maximum, médiane, écart-type et compte.
Les dates et l'interprétation temporelle sont fournies par l'utilisateur.
`count` retourne toujours le nombre d'observations, y compris zéro;
`min_valid` s'applique aux autres statistiques. Ce calcul ne remplace pas une
analyse de tendance, un test statistique ou une harmonisation des capteurs.

## Exécution et performances

`workers` choisit 1 à 32 threads, ou `"auto"` (au plus quatre). Les lectures et
écritures GDAL restent dans un seul thread; les calculs sur tableaux peuvent
s'exécuter simultanément. Les travaux en attente sont bornés. La taille des
blocs, 512 pixels par défaut, diminue si nécessaire selon `memory_limit_mb`.
Ce budget estime les tableaux de travail; ce n'est pas une limite stricte
de la mémoire totale du processus, qui comprend aussi GDAL, Python et Qt.

Les bénéfices proviennent de la lecture commune des bandes, de la
vectorisation NumPy et du recouvrement des calculs avec les entrées/sorties.
Ils dépendent du processeur, du stockage, du nombre d'indices et de la
compression. Augmenter le nombre de threads ne garantit pas un gain et peut
augmenter la mémoire. Les rasters ne sont pas chargés intégralement en RAM.
Voir les [principes de concurrence Rasterio](https://rasterio.readthedocs.io/en/stable/topics/concurrency.html).

`progress(completed, total)` permet de suivre le traitement. Un
`threading.Event` passé comme `cancel` demande l'annulation; elle est prise
en compte entre blocs, avant publication du fichier de sortie. Un résultat
existant est conservé si le traitement échoue ou est interrompu.

Le [rapport de performances](PERFORMANCE.md) décrit les mesures locales.
La mosaïque conserve son moteur distinct : le parallélisme ajouté ici concerne
l'algèbre, les indices, les statistiques focales et multirasters.

La calculatrice couvre les opérations exprimables dans cette syntaxe. Elle
ne prétend pas inclure tous les algorithmes SIG : hydrologie, classification
apprise, décomposition radar et autres traitements spécialisés nécessitent
leurs propres implémentations.
