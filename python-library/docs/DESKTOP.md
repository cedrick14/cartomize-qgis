# Interface graphique Cartomize

## Installation et lancement

Depuis le dossier source :

```bash
python -m pip install ".[gui]"
cartomize gui
```

Depuis le wheel fourni :

```bash
python -m pip install "cartomize-0.3.0a1-py3-none-any.whl[gui]"
cartomize-desktop
```

Depuis un script ou une console Python :

```python
import cartomize as cm
cm.launch()
```

La fenêtre est une application Qt native, sans serveur web. Les dépendances
graphiques sont facultatives pour les traitements Python. L'importation de
`cartomize` n'ouvre pas de fenêtre : l'ouverture est demandée par `launch`,
`cartomize gui` ou `cartomize-desktop`. Sur Windows, l'entrée
`cartomize-desktop` est créée comme programme graphique par pip.

La commande est disponible dans l'environnement Python où le paquet a été
installé. Activer cet environnement si nécessaire. Cette livraison reste
une alpha distribuée par fichier wheel, sans publication PyPI effectuée.

## Outils

| Outil | Données et paramètres |
|---|---|
| Indices spectraux | Raster multibande, sélection des indices, correspondance des bandes, paramètres et calibration |
| Calculatrice raster | Import des rasters, noms des variables, numéros de bandes, facteurs/décalages et expression |
| Statistiques focales | Raster, bande, statistique, voisinage et conservation du NoData |
| Statistiques multirasters | Liste de rasters, statistique et nombre minimal d'observations |
| Prétraitement multispectral | Répertoire des scènes, zone d'étude, CRS, résolution, bandes, qualité et dates |
| Composition cartographique | Couches raster/vectorielles, rôles, étiquettes, titre, sources, emprise et export |

## Calcul d'un indice

1. Ouvrir **Indices spectraux** et sélectionner le raster multispectral.
2. Cocher les indices à calculer. La formule et la référence sont accessibles
   dans l'infobulle de chaque indice.
3. Vérifier les numéros dans **Correspondance spectrale**. Les descriptions
   reconnues sont renseignées automatiquement; les autres bandes sont à affecter.
4. Vérifier la calibration. Les indices avec constantes additives exigent
   une réflectance calibrée; un DN brut ne suffit pas.
5. Choisir un **Fichier de sortie** GeoTIFF et sélectionner **Exécuter**.

Plusieurs indices sélectionnés produisent un seul GeoTIFF à bandes nommées.
La calculatrice permet les formules absentes du catalogue. Les descriptions
des outils et les intitulés reprennent les opérations de géomatique.

## Traitement et résultats

Les calculs se déroulent en arrière-plan. La progression et l'état sont
affichés en bas de la fenêtre. **Annuler** interrompt les calculs raster entre
blocs; le prétraitement répond également entre blocs de calibration/mosaïque.
L'export cartographique se termine avant de pouvoir fermer la fenêtre.

Les paramètres de threads, blocs et mémoire s'appliquent aux quatre outils
de calcul. Ils sont désactivés pour les moteurs distincts de prétraitement et
de cartographie. Le remplacement des fichiers existants demande de cocher
explicitement l'option correspondante. **Ouvrir le répertoire de sortie**
donne accès aux résultats après réussite.

Dans une application possédant déjà un `QApplication`, utiliser
`cm.launch(block=False)` et conserver sa boucle d'événements Qt. Pour un
notebook sans intégration Qt, privilégier le lancement depuis un terminal.
L'application exige un environnement de bureau pour l'affichage normal.

## Périmètre de validation

Les contrôles automatisés utilisent les vrais widgets Qt et des traitements
réels en mode hors écran sous Linux. Ils vérifient les indices, la
calculatrice, la mosaïque et l'export cartographique, ainsi que la réactivité
de la boucle d'événements et l'annulation. Un aperçu PNG provient de cette
fenêtre, sans maquette illustrée.

Un essai manuel sous Windows sur les données de l'utilisateur reste utile
avant diffusion stable. La fenêtre ne constitue pas un éditeur SIG complet
et ne lit pas les projets QGIS ou ArcGIS Pro.
