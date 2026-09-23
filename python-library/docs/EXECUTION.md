# Moteurs de calcul et styles SIG — 0.8

## Installation

`python -m pip install "cartomize[gui,distributed]"` installe la fenêtre et Dask lorsque le paquet est disponible sur votre index. Pour le wheel livré : `python -m pip install "cartomize-0.8.0a1-py3-none-any.whl[gui,distributed]"`. Aucune publication PyPI n’est effectuée par cette livraison.

Le moteur GPU est facultatif : extra `gpu`, fondé sur `cupy-cuda12x[ctk]>=14,<15`. Il installe les composants CUDA 12 ; un pilote NVIDIA compatible et un GPU restent indispensables. Une installation CUDA 13 utilise un environnement distinct avec la distribution CuPy appropriée, sans installer simultanément plusieurs distributions CuPy. Exécuter `python -m cartomize engines` pour le diagnostic.

## Portée

| Famille | CPU threads | Dask processus/cluster | CUDA |
|---|---|---|---|
| Algèbre raster | Oui | Oui | Implémenté, validation matérielle requise |
| Indices spectraux | Oui | Oui | Implémenté, validation matérielle requise |
| Réductions multirasters | Oui | Oui | Implémenté, validation matérielle requise |
| Statistiques focales | Oui | Oui | Non |
| Dérivées du terrain et convolution | Oui | Oui | Non |
| Préparation des scènes, classification, vecteurs, hydrologie, cartographie | Moteurs existants | Exécution habituelle dans le processus principal | Non |

Les réglages globaux des plans s’appliquent aux familles prises en charge ; les paramètres de chaque étape sont prioritaires. Un réglage CUDA explicite dans une opération incompatible est refusé. Un GPU absent provoque une erreur, jamais un résultat CPU présenté comme un calcul GPU.

## API

```python
import cartomize as cm

cm.calculate('(nir-red)/(nir+red)',
             {'nir': ('composite.tif', 4), 'red': ('composite.tif', 3)},
             'ndvi.tif', execution='distributed', workers=4,
             block_size=512, memory_limit_mb=512)

cm.spectral_indices('composite.tif', 'indices.tif', ['NDVI', 'NDMI'],
                    device='cuda', workers=1)
```

Un script créant des processus locaux doit placer son appel dans `if __name__ == '__main__':`, particulièrement sous Windows. La fenêtre et la CLI le prennent en charge.

Sans adresse, Dask crée des processus sur la machine locale. Avec `scheduler_address='tcp://serveur:8786'`, il se connecte au cluster choisi. Utiliser uniquement une infrastructure de confiance ; les tableaux raster et les fonctions sont transmis aux travailleurs. Chaque travailleur doit disposer des mêmes versions de Cartomize et de ses dépendances. Aucun dossier de données partagé n’est requis : le coordinateur lit les blocs, les travailleurs calculent, puis le coordinateur écrit le GeoTIFF. Pour une connexion protégée, utiliser une infrastructure Dask sécurisée selon sa documentation ; Cartomize ne provisionne ni cluster ni certificats.

Le nombre de blocs en vol est borné par `workers`. Le budget estime les tableaux, sans plafonner le processus, les bibliothèques natives, le cache GDAL, les copies réseau ou la mémoire GPU. Les marges des blocs sont conservées pour les filtres de voisinage. Les échecs et annulations préservent les sources et empêchent la publication du résultat incomplet.

Les transferts, la création des processus, la compilation CUDA et le stockage peuvent rendre un petit traitement plus lent. Aucun gain universel n’est annoncé. Les mesures historiques CPU de 0.5 ne constituent pas une mesure du GPU ou du calcul distribué.

## Fenêtre et ligne de commande

Les outils concernés proposent l’exécution CPU ou Dask, l’adresse facultative du cluster et le choix CPU/CUDA pour les familles compatibles. L’assistant possède les mêmes réglages ; les sessions les conservent. « Vérifier les moteurs de calcul » examine les dépendances et le matériel accessibles.

`python -m cartomize calculate "a*2" sortie.tif --input a entree.tif 1 --execution distributed --workers 4`

Les commandes `index`, `reduce`, `focal`, `terrain`, `convolve`, `process` et `run-plan` exposent les choix applicables. `--device cuda` est disponible pour l’algèbre, les indices, les réductions et les plans.

## Transfert des styles

Sont pris en charge : symboles simples, couleurs et opacités, largeur de trait en millimètres/points/pixels/pouces, formes ponctuelles usuelles, catégories et catégories masquées, classes graduées numériques, symboles composites simples, contrastes en niveaux de gris et rampes raster interpolées/discrètes/exactes. Les traits et tailles sont convertis en points typographiques ; les pixels de symbologie utilisent 96 ppp. Les bornes communes des classes graduées sont attribuées à la première classe rencontrée, sans double dessin. Les classes non représentées sont omises du dessin.

La légende d’un symbole composite représente son composant supérieur. Les symboles dépendant d’unités cartographiques, expressions, rotations, SVG, motifs complexes, propriétés définies par les données et certains contrastes natifs restent signalés dans `transfer_warnings`. Copier/exporter avec le moteur natif préserve son propre rendu.

## Validation native

Dans « Projets SIG », sélectionner le projet, le Python SIG installé, « Valider le moteur natif », une mise en page unique et un nouveau dossier de résultat.

```text
python -m cartomize native-validate projet.qgz validation --python /usr/bin/python3 --layout Validation
python -m cartomize native-validate projet.aprx validation --python CHEMIN_VERS_PYTHON_ARCGIS --layout Carte
```

La procédure ouvre réellement le projet, réalise une copie, exporte PDF/PNG/SVG, vérifie les signatures, puis compare l’empreinte du projet source. Elle produit un rapport ; les objets, mises en page et données de tous les projets possibles ne sont pas pour autant certifiés. QGIS est exercé dans un travail CI dédié. ArcGIS Pro ne peut être validé sans son moteur installé et une licence utilisable.

## Références techniques

- CuPy : https://docs.cupy.dev/en/stable/install.html et https://docs.cupy.dev/en/stable/user_guide/basic.html
- Dask Distributed : https://distributed.dask.org/en/latest/client.html
- QGIS : https://docs.qgis.org/latest/en/docs/user_manual/working_with_vector/vector_properties.html
