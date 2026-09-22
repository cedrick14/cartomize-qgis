# Interface graphique Cartomize

## Installation et lancement

Depuis le wheel fourni, avec Python 3.11 ou plus récent :

```bash
python -m pip install "cartomize-0.3.0a2-py3-none-any.whl[gui]"
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

Choisir la composition colorée, le titre, les sources et l'auteur, le format
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
| Composition cartographique | Assembler des couches raster et vectorielles existantes et exporter une carte |
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

## Identité visuelle et validation

L'icône est celle du dépôt Cartomize original, conservée sans modification.
La fenêtre emploie le bleu foncé `#142D68` et le bleu `#2F5597` de cette icône,
avec des fonds blancs et gris. Voir [la provenance visuelle](BRANDING.md).

Les tests locaux utilisent les vrais widgets Qt en mode hors écran sous
Linux, avec de véritables sorties raster et cartographiques. Ils couvrent
la chaîne multiscène, les outils de calcul, la réactivité et l'annulation.
Un essai manuel de bureau sous Windows sur les données de l'utilisateur
reste à réaliser. La fenêtre ne lit pas les projets QGZ/APRX.
