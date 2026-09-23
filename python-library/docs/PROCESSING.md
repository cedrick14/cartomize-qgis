# Chaînes de traitements — Cartomize 0.7

## Registre et dépendances

`operation_catalog()` décrit les 34 opérations, leurs paramètres, leur type de
sortie et leurs produits secondaires. `execute_operation()` exécute une opération
isolée. `processing_plan()` enchaîne des opérations sans imposer de carte finale.
`plan_cartography(..., processing_steps=...)` les insère avant l’analyse du projet
et la mise en page. La fenêtre utilise ces mêmes fonctions.

```python
import cartomize as cm

steps = [
    {"id": "pente", "operation": "terrain",
     "parameters": {"source": "mnt.tif", "products": ["slope"]}},
    {"id": "seuil", "operation": "calculate",
     "parameters": {"inputs": {"p": ["@pente", 1]},
                    "expression": "where(p >= 30, 1, 0)"},
     "map_layer": {"name": "Pentes fortes", "classes": {
         0: ["Moins de 30°", "#eeeeee"], 1: ["30° et plus", "#555555"]}}},
]
plan = cm.plan_cartography(["mnt.tif", "localites.gpkg"],
    processing_steps=steps, title="Contraintes topographiques", credits="Sources")
result = cm.run_plan(plan, "production", workers=4,
                     block_size=512, memory_limit_mb=512)
```

`@identifiant` désigne le produit principal. `@drainage:watersheds` sélectionne
les bassins ; `@classification:confidence` sélectionne la confiance. Dans
`map_layer`, `product` permet ce même choix. `@scientific` est remplacé par le
multibande scientifique dans un plan cartographique ; cette référence n’est pas
définie dans un plan de traitements indépendant.

Le graphe entier est vérifié avant écriture : noms uniques, opérateurs enregistrés,
paramètres connus et dépendances antérieures. Les arguments de sortie, fonctions
Python et options d’écrasement ne peuvent pas être fournis par le document.
Le nouveau dossier n’apparaît qu’après succès de l’ensemble. L’annulation reste
coopérative ; une opération GEOS/GDAL non interruptible doit se terminer.

Les paramètres de blocs, travailleurs et mémoire sont transmis aux opérateurs
compatibles. Un paramètre indiqué dans une étape prévaut sur le réglage global.
Le budget des tableaux ne constitue pas un plafond de mémoire du processus.

```bash
cartomize operations
cartomize process terrain parametres.json resultat --workers 4
cartomize plan plan.json mnt.tif --steps etapes.json --title "Relief"
cartomize run-plan plan.json production --workers 4 --block-size 512
```

## Hydrologie

`hydrology()` produit cinq GeoTIFF : MNT comblé, direction D8, accumulation,
réseau binaire défini par un seuil, et bassins. Le remplissage suit Priority-Flood.
Les cellules descendantes prennent la plus forte pente parmi huit voisins ; les
plats suivent l’arbre parent du remplissage pour garantir un drainage sans cycle.
Les directions sont codées E=1, SE=2, S=4, SO=8, O=16, NO=32, N=64, NE=128.
Zéro désigne un exutoire et 65535 le NoData dans le raster de directions.

L’accumulation inclut la cellule elle-même. La superficie contributive s’obtient
en la multipliant par la superficie du pixel. Les bords et les cellules adjacentes
au NoData sont ouverts. Les exutoires facultatifs sont des points dans le SCR du
fichier ; ils sont reprojetés mais ne sont pas déplacés automatiquement sur un cours
d’eau. Des exutoires imbriqués délimitent des bassins incrémentaux : chaque cellule
est affectée au premier exutoire rencontré en aval. Zéro désigne un bassin non
affecté à un exutoire fourni ; -1 le NoData.

Ce calcul utilise des tableaux globaux et une estimation de mémoire préalable.
Il faut augmenter explicitement le budget ou sélectionner un bassin complet si
le MNT est trop grand. Découper arbitrairement une zone modifie ses limites
hydrologiques. D8 n’est ni une simulation hydraulique ni un calcul de débit ; MFD,
D-infinity, incision des dépressions et Strahler ne sont pas inclus.

## Routage

`shortest_path()` utilise Dijkstra sur un réseau de lignes, avec distances en mètres.
Les coordonnées de départ/arrivée sont rattachées aux **nœuds** les plus proches
dans `max_snap_m`. Les géométries sont segmentées aux sommets et, par défaut,
aux intersections. Les distances de rattachement figurent dans le résultat et
ne sont pas incluses dans la longueur du parcours sur le réseau.

Le graphe est bidirectionnel. Les sens uniques, restrictions de virage et vitesses
ne sont pas inférés. Pour les ponts et passages dénivelés, fournir un réseau déjà
préparé et désactiver `node_intersections`. Les composantes déconnectées et les
rattachements hors tolérance provoquent une erreur explicite.

## Scènes STAC et capteurs supplémentaires

`search_stac(endpoint, bbox=..., datetime_range=..., collections=..., limit=...)`
consulte un service STAC Item Search choisi par l’utilisateur. Les pages GET/POST
sont suivies jusqu’à la limite demandée ; les boucles et volumes excessifs sont
refusés. `download_stac()` télécharge les assets HTTP(S) sélectionnés dans un
nouveau dossier, conserve les métadonnées locales et calcule leurs empreintes.
Les empreintes SHA256 annoncées au format multihash sont vérifiées. Une limite
globale d’octets, un délai et l’annulation contrôlent le transfert. Les mécanismes
privés d’authentification ou de signature d’URL propres aux fournisseurs ne sont
pas fournis par la bibliothèque.

`discover_scenes()` accepte les fichiers STAC Item/FeatureCollection locaux et
les dossiers téléchargés contenant `scenes.json`. Les rôles spectraux et les
coefficients proviennent des métadonnées `bands`, `eo:bands` et `raster:bands`.
Une calibration absente est signalée ; les unités d’origine sont conservées.
Ne pas assimiler ces valeurs à une réflectance sans information du producteur.
Le masque QA/SCL reste explicite ; `mask_clouds=False` doit être demandé lorsque
le produit n’en possède pas.

Un manifeste `cartomize.scenes.v1` décrit aussi les données d’un capteur quelconque :

```json
{"schema":"cartomize.scenes.v1","scenes":[{
  "scene_id":"tuile_01","sensor":"capteur_declare","acquired":"2026-09-01",
  "bands":{"red":{"path":"rouge.tif","scale":0.0001,"unit":"reflectance"},
           "nir":{"path":"proche_infrarouge.tif","scale":0.0001,"unit":"reflectance"}}
}]}
```

Les coefficients de cet exemple sont illustratifs : employer ceux du produit.
Les bandes manquantes, capteurs incompatibles et dates mélangées ne sont pas
harmonisés silencieusement. Les sessions portables suivent les dépendances STAC.

## Reprise QGIS et contrôle cartographique

`import_native_project()` matérialise les sous-couches vectorielles locales,
conserve l’ordre, la visibilité des groupes, les styles simples/catégorisés,
la transparence, les palettes raster et les champs d’étiquettes pris en charge.
Les autres styles, services ou filtres figurent dans `transfer_warnings`.
La sortie `map.json` est directement réouvrable par `Map.load()`.

Les copies et exports natifs conservent leur rendu via le moteur ArcPy/PyQGIS
installé. Cette exécution reste à valider dans ces environnements ; l’import
autonome ne revendique pas la parité avec tous les objets natifs.

Le masquage par `valid_footprint` respecte les valeurs zéro valides dans l’emprise.
La nomenclature raster est vérifiée sur tous les blocs, et non uniquement sur
un échantillon. Les étiquettes évitent les symboles ponctuels et les autres
étiquettes placées ; les omissions sont rapportées. Les légendes essaient plusieurs
colonnes avant de signaler un débordement. L’exactitude thématique et tous les
conflits possibles avec les objets linéaires ou surfaciques nécessitent encore
une vérification cartographique.

## Références techniques

- Barnes, Lehman et Mulla, Priority-Flood : https://arxiv.org/abs/1511.04463
- Directions D8 : https://pro.arcgis.com/en/pro-app/3.3/tool-reference/spatial-analyst/how-flow-direction-works.htm
- STAC, métadonnées : https://github.com/radiantearth/stac-spec/blob/master/commons/common-metadata.md
- STAC Item Search : https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md
- QGIS, styles : https://docs.qgis.org/testing/en/docs/user_manual/working_with_vector/vector_properties.html
