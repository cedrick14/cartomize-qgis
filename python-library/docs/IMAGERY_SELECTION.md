# Prétraitement multispectral à options — 0.8.1a1

La rubrique **Prétraitement multispectral** permet de sélectionner les étapes et les produits. Elle fonctionne avec les dépendances Python de Cartomize, sans QGIS ni ArcGIS Pro.

## Parcours dans la fenêtre

1. Cliquer sur **Sélectionner les bandes…**, ou choisir un répertoire puis **Analyser les bandes**. Les noms Landsat Collection 2 L2 et Sentinel-2 L2A sont reconnus avec leurs métadonnées d’origine. Les manifestes de scènes Cartomize sont également acceptés. Conserver les masques QA/SCL et les métadonnées Sentinel dans le produit d’origine.
2. Vérifier le tableau : scène, bande spectrale, fichier, numéro interne, échelle, décalage et date. Cocher les bandes à traiter. L’ordre du tableau détermine l’ordre des bandes dans le GeoTIFF scientifique.
3. Charger le shapefile de délimitation, ou une autre couche polygonale prise en charge. **Extraction par masque** s’active lors de cette sélection ; la décocher pour conserver l’emprise complète.
4. Cocher les opérations et produits souhaités selon le tableau ci-dessous.
5. Pour une composition colorée, choisir explicitement les bandes affectées aux **canaux rouge, vert et bleu**. Exemple : `red / green / blue` pour les couleurs naturelles ; `nir / red / green` pour une représentation de la végétation en fausses couleurs.
6. Choisir le répertoire de sortie, donner un **nouveau nom de dossier**, puis **Exécuter**. Les produits apparaissent dans **Résultats du projet** et peuvent être transmis à la mise en page et aux autres traitements.

| Option | Résultat |
|---|---|
| Mosaïque des scènes cochée | Les scènes sont assemblées spatialement ; les mêmes bandes doivent être sélectionnées dans chaque scène. |
| Mosaïque décochée | Chaque scène produit son propre dossier ; aucune fusion entre scènes. |
| Assemblage multibande coché | Le GeoTIFF scientifique `multibande.tif` est conservé. |
| Composition colorée cochée | Un fichier `composition_coloree.tif` distinct contient trois canaux de visualisation et un canal alpha de transparence. |
| Extraction des bandes cochée | Un GeoTIFF monobande est enregistré pour chaque bande, avec la même grille, les masques et les métadonnées. |

Au moins un produit doit être demandé : multibande, bandes séparées ou composition colorée. Si l’assemblage multibande n’est pas conservé, le fichier intermédiaire nécessaire aux autres produits est supprimé après traitement. Le rapport `imagery.json` indique les sorties effectivement présentes et la correspondance des canaux.

## Bandes personnalisées

Choisir **Bandes personnalisées : correspondance manuelle** pour des fichiers renommés ou un autre capteur. Cartomize n’invente pas leur identité spectrale. Les noms de bandes et les facteurs inscrits dans les fichiers sont repris lorsqu’ils existent ; les autres noms doivent être corrigés dans le tableau.

Les fichiers sont initialement rattachés à `scene_1`. Donner le même identifiant aux bandes d’une acquisition, et des identifiants différents aux acquisitions distinctes. Utiliser les mêmes noms spectraux entre scènes. Deux bandes portant le même nom dans la même scène sont refusées. Le numéro indique la bande à lire à l’intérieur du fichier source. Les facteurs de calibration proviennent des métadonnées du fichier, avec les valeurs usuelles 1 et 0 lorsque rien n’est déclaré ; renseigner les facteurs documentés du produit si nécessaire.

Pour les données personnalisées, le masque QA/SCL est désactivé initialement : aucun masque nuageux n’est inventé. Pour fournir des masques et métadonnées explicites, utiliser un manifeste de scènes ou l’API `Scene`/`Band`. Une mosaïque à dates différentes ou inconnues exige l’option explicite correspondante.

## Valeurs et contrôles

La calibration et le masque de qualité précèdent le rééchantillonnage. La mosaïque, l’assemblage et le découpage utilisent une grille commune. Dans les recouvrements, une seule scène valide fournit toutes les bandes d’un pixel. La résolution par défaut est la plus grossière des bandes sélectionnées. Pour des entrées en coordonnées géographiques, renseigner un système projeté adapté.

Le multibande scientifique conserve les valeurs calibrées en `float32`, sans étirement de visualisation. La composition colorée est en `uint8` avec transparence ; elle ne doit pas remplacer le multibande pour les indices. Les valeurs zéro valides restent valides. L’étirement par défaut utilise les percentiles 2 et 98 estimés sur un aperçu borné.

Le traitement s’exécute en arrière-plan et peut être annulé. Une erreur ou une annulation ne publie pas de dossier partiel. Les sources restent intactes. Les sélections, correspondances, cases et canaux sont conservés dans la session et le projet portable.

## Utilisation Python

```python
import cartomize as cm

resultat = cm.process_imagery(
    ["scene_A", "scene_B"],
    "resultats/pretraitement",  # nouveau dossier
    aoi="limites.shp",
    mosaic=True,
    multiband=True,
    separate_bands=True,
    composition=("nir", "red", "green"),
)
print(resultat.manifest)

# Extraction ultérieure d’un multibande existant :
fichiers = cm.split_bands("multibande.tif", "resultats/bandes_extraites")
```

`mosaic=False` conserve les acquisitions séparées. `composition=None` désactive la composition colorée. `prepare_imagery` et `cartographic_workflow` conservent leurs contrats précédents ; `process_imagery` fournit le parcours à options.
