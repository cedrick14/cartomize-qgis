# Interface graphique Cartomize

## Installation et lancement

Depuis le wheel fourni, avec Python 3.11 ou plus récent :

```bash
python -m pip install "cartomize-0.3.0a3-py3-none-any.whl[gui]"
cartomize-desktop
```

Depuis les sources : `python -m pip install ".[gui]"`, puis `cartomize gui`.
Depuis Python :

```python
import cartomize as cm
cm.launch()
```

La fenêtre Qt est indépendante d'ArcGIS Pro et de QGIS. Les dépendances
graphiques sont facultatives pour les scripts. L'importation de `cartomize`
n'ouvre pas de fenêtre. Cette alpha est distribuée par wheel; aucune
publication PyPI n'a été effectuée.

## Production cartographique automatisée

L'écran d'ouverture est **Production automatisée**. Le bouton **Exécuter la
chaîne** réalise le parcours suivant dans une seule opération :

1. Identification des scènes et des bandes spectrales.
2. Calibration radiométrique et masque de qualité avant rééchantillonnage.
3. Alignement des grilles, mosaïque des scènes et assemblage multibande.
4. Extraction selon la zone d'étude sur la grille de sortie.
5. Composition colorée enregistrée séparément du produit scientifique.
6. Superposition des couches vectorielles, mise en page et export.

La mosaïque, l'assemblage et l'extraction sont intégrés au même traitement
par blocs; ils n'imposent pas des copies intermédiaires de toute la zone.

### Données

- Sélectionner un **Répertoire des scènes**, ou **Sélectionner les bandes**.
  La reconnaissance automatique couvre Landsat Collection 2 L2 Surface
  Reflectance et Sentinel-2 L2A avec leurs noms de fichiers et métadonnées
  d'origine. Conserver les fichiers QA/SCL et les métadonnées du produit.
- Indiquer une **Zone d'étude** polygonale, si un découpage est nécessaire.
- Importer les **Couches à superposer** : routes, hydrographie, limites,
  localités, occupation du sol vectorielle, etc. Vérifier les rôles dans le
  tableau et préciser les champs d'étiquette si nécessaire. Les noms et
  géométries servent à proposer un rôle; cette inférence n'est pas une
  interprétation sémantique garantie. Les localités peuvent utiliser leur
  champ `nom` ou `name` automatiquement.
- Choisir le **Répertoire de sortie** et un nouveau **Nom de la production**.
  Une production existante n'est jamais remplacée par ce parcours.

### Prétraitement

Le système de coordonnées, la résolution et les bandes sont réglables dans
l'onglet **Prétraitement**. Les valeurs par défaut utilisent le système
projeté approprié aux données et la résolution native la plus grossière des
bandes retenues. Les bandes nécessaires à la composition colorée sont
ajoutées à la sélection. Le masque de qualité est activé par défaut;
l'autorisation d'une mosaïque multitemporelle est explicite.

### Restitution cartographique

Choisir la composition colorée, le titre, le sous-titre, les sources et l’auteur,
la maquette et les éléments d’habillage, puis le format
(PDF, PNG, SVG ou PDF et PNG) et la résolution d'export. La mise en page
comporte légende, échelle et orientation. L'ordre des couches découle de leur
rôle cartographique; la zone d'étude contrôle l'emprise et le découpage
vectoriel. Le GeoTIFF multibande conserve les valeurs de réflectance.

Les sorties comprennent `multibande.tif`, `multibande_source_index.tif`,
`multibande.json`, `composition_coloree.tif`, les cartes et `production.json`.
Les produits sont préparés dans un répertoire temporaire puis rendus
accessibles ensemble après réussite. Une erreur ou une annulation avant
l'enregistrement final ne laisse pas de production partielle publiée.

## Outils complémentaires

| Outil | Usage |
|---|---|
| Prétraitement multispectral | Produire seulement le GeoTIFF multibande et le rapport de mosaïque |
| Composition colorée | Produire une visualisation RVB à partir d'un composite multibande nommé |
| Mise en page | Maquettes, cadres, symbologie, étiquettes, contenus, aperçu et export |
| Atlas cartographique | Une carte par entité d’une couche d’index |
| Analyse des couches | Profils raster/vectoriels et rapport JSON |
| Traitements vectoriels | Découpage, tampon, superpositions, jointures, dissolution, reprojection, réparation et mesures |
| Traitements raster | Extraction, reprojection, reclassification, statistiques zonales, superficies et transitions |
| Indices spectraux | Calculer un ou plusieurs indices sur les bandes préparées |
| Calculatrice raster | Exécuter une expression algébrique ou conditionnelle |
| Statistiques focales | Analyser le voisinage spatial |
| Statistiques multirasters | Synthétiser des rasters superposés ou une série temporelle |

Les indices constituent une analyse complémentaire. Ils ne sont pas une
étape obligatoire de la production cartographique. La classification
supervisée d'occupation du sol n'est pas implémentée; une composition
colorée ne constitue pas une classification.

## Traitement et résultats

La fenêtre reste disponible pendant les traitements en arrière-plan. Le nom
de l'étape et la progression apparaissent en bas. **Annuler** interrompt les
opérations raster entre blocs; un export cartographique en cours doit se
terminer avant l'interruption. **Ouvrir le répertoire de sortie** donne accès
aux résultats après réussite.

Les réglages de threads, blocs et mémoire apparaissent pour les outils de
calcul qui les utilisent. La chaîne de production utilise les moteurs de
prétraitement et de rendu; ces paramètres de calcul n'y sont pas proposés.
Les outils individuels demandent de cocher **Remplacer les fichiers
existants** avant un remplacement.

Dans une application possédant déjà un `QApplication`, utiliser
`cm.launch(block=False)` avec sa boucle Qt. Pour un notebook sans intégration
Qt, lancer la fenêtre depuis un terminal. Un environnement de bureau est
nécessaire pour l'affichage normal.

## Mise en page et atlas

**Mise en page** est accessible directement sous Production automatisée.

1. Dans **Couches et symbologie**, importer les rasters et les données
   vectorielles. Renseigner les rôles, les champs d’étiquette et les champs
   thématiques; ajuster la bande, l’opacité et la palette. Pour un raster
   multispectral scientifique, choisir une bande unique ou une composition
   colorée. Les couleurs des données cartographiques restent réglables.
2. Dans **Maquette et habillage**, choisir l’une des 24 maquettes ou la mise en
   page standard. Le format et l’orientation sont libres pour le modèle
   standard et déterminés par la maquette pour les autres. Renseigner le
   titre, le sous-titre et les sources. Activer la légende, l’échelle et
   l’orientation selon le besoin. Le dessin affiché représente la structure
   de la maquette, pas encore son contenu géographique.
3. Dans **Cadres et contenus**, affecter si nécessaire une emprise, un système
   de coordonnées et une liste de couches à chaque cadre. Les noms des couches
   sont leurs noms de fichiers sans extension. Une liste vide utilise toutes
   les couches. Renseigner les emplacements de texte, tableau CSV ou graphique
   présents dans la maquette. Pour un graphique, préciser les colonnes de
   libellés et de valeurs du CSV.
4. Utiliser **Aperçu cartographique** pour contrôler le rendu réel dans une
   fenêtre séparée. L’aperçu s’exécute en arrière-plan, sans demander de nom
   de fichier définitif.
5. Choisir le fichier de sortie et cliquer sur **Exporter la carte**.

**Atlas cartographique** reprend les mêmes réglages. L’onglet **Index de
l’atlas** demande la couche d’index, le champ des noms de pages, le format et
la marge de cadrage. Les noms doivent être uniques. Chaque page est exportée
séparément dans le répertoire choisi. Une annulation intervient entre les
pages; les pages déjà terminées sont conservées. Les emprises explicitement
affectées aux cadres restent fixes d’une page à l’autre.

## Analyse et traitements

**Analyse des couches** produit et affiche un rapport JSON : géométries,
attributs et proposition de champs pour le vecteur; métadonnées, bandes,
échantillon de valeurs et diagnostic NoData pour le raster. Ce diagnostic
ne constitue pas l’audit complet d’un projet SIG.

**Traitements vectoriels** propose 12 opérations. Les distances de tampon
sont en mètres. Les mesures demandent un système projeté adapté; les résultats
sont enregistrés dans de nouveaux champs. Les sorties sont des GeoPackage ou
GeoJSON et ne remplacent jamais un fichier source.

**Traitements raster** propose l’extraction par masque, la reprojection, la
reclassification, les statistiques zonales, les superficies par classe et
la matrice de transition. Les trois premières opérations portent sur la
bande choisie. La mosaïque multibande reste dans Prétraitement multispectral.
La reclassification utilise une correspondance par ligne, par exemple
`1 = 10`. Les statistiques zonales produisent une couche vectorielle;
les superficies et transitions produisent un CSV. Les rasters de transition
doivent être alignés. Ces opérations se terminent avant la fermeture de
la fenêtre et n’exposent pas d’annulation en cours d’opération.

## Identité visuelle et validation

Tous les contrôles de l’interface, l’icône et les titres utilisent le noir,
le blanc et les gris. L’icône originale est rendue en noir à l’affichage.
Les informations de provenance du code et les attributions sont conservées
dans les documents techniques.

Les tests utilisent de vrais widgets Qt en mode hors écran sous Linux et de
véritables traitements. Ils vérifient la chaîne automatisée avec maquette,
les cadres indépendants, l’aperçu, l’atlas, les diagnostics, les traitements
vectoriels/raster et les outils de calcul. Un essai manuel Windows reste à
réaliser. Le [tableau des fonctionnalités](FUNCTIONAL_COVERAGE.md) indique
précisément ce qui est disponible et les fonctions natives non transposées.
