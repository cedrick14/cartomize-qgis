# Cartomize 0.6 : traitement, session et production

Cartomize est un assistant cartographique fondé sur des règles explicables et des algorithmes géospatiaux. Il ne dépend pas d’un service conversationnel. La fenêtre s’ouvre avec `cm.launch()` ou `cartomize gui`.

## Parcours automatisé

1. Définir l’objectif, importer les couches ou les scènes, préciser la zone d’étude et les sources.
2. Pour des scènes, ajouter séparément les routes, limites et localités. Le plan prépare les bandes nécessaires aux indices demandés.
3. Choisir une classification seulement si elle est souhaitée. Fournir les références pour l’apprentissage supervisé ; les K-moyennes produisent des groupes à interpréter.
4. Cliquer sur **Établir le plan de traitement**, examiner les étapes et choisir une maquette proposée.
5. Indiquer un répertoire parent et un nouveau nom, puis **Exécuter le plan**.
6. Reprendre les résultats dans **Mise en page**, contrôler et exporter. Les données sources restent inchangées.

Le plan enchaîne les étapes applicables : calibration et masque de qualité, grille commune, mosaïque cohérente entre bandes, multibande, extraction, composition colorée, réparation géométrique, classification/indices facultatifs, analyse du projet, relations spatiales, habillage et atlas facultatif. Les calculs spectraux utilisent les valeurs scientifiques. Les relations sur raster concernent son emprise rectangulaire, pas une analyse exhaustive de ses pixels valides.

`plan_cartography()` crée un document JSON réutilisable ; `run_plan()` l’exécute dans un nouveau dossier publié après succès. Une modification des entrées dans la fenêtre oblige à régénérer le plan. Les propositions de maquettes sont classées par objectif, rapport de forme et place disponible ; ce classement ne remplace pas le jugement cartographique.

## Classification

```python
import cartomize as cm

classes = cm.classify_landcover(
    "multibande.tif", "echantillons.gpkg", "classification",
    class_column="code", label_column="libelle",
    validation="validation_independante.gpkg",
    algorithm="random_forest", n_estimators=100,
    sample_limit=50000, workers=4,
)
# Produits : classification.tif, confidence.tif, classification.json,
# model/model.json et model/model.npz.
modele = cm.load_classifier("classification/model")
cm.classify_landcover("autre_multibande.tif", None, "autre_resultat", model=modele)
```

Les bandes sont calibrées selon leurs métadonnées. Les descriptions et l’ordre spectral doivent correspondre au modèle. Une image RVB étirée n’est pas acceptée comme produit scientifique Cartomize.

Les données de validation sont séparées **avant** le prélèvement des pixels. Les recouvrements entre classes et entre apprentissage et validation sont contrôlés avant échantillonnage. Sans jeu indépendant, les entités ou groupes sont séparés lorsque toutes les classes peuvent figurer des deux côtés ; sinon le rapport indique que la validation est indisponible. La confiance est la probabilité estimée par l’ensemble d’arbres, sans garantie de calibration statistique. Les taux obtenus sur les jeux synthétiques de test ne décrivent pas la précision sur une zone réelle.

Les modèles sont des tableaux numériques NPZ chargés avec `allow_pickle=False`. Les classes égales à zéro restent valides. L’apprentissage et la prédiction sont annulables ; les arbres sont entraînés par lots de dix. K-moyennes : `cm.cluster_raster(..., clusters=6)`. Les groupes n’ont pas d’interprétation automatique d’occupation du sol.

## Sessions et mise en page

**Enregistrer** conserve les contrôles de toutes les rubriques, tables, choix, couches, cadres, paramètres, propositions et résultats. **Ouvrir** reprend cet état. **Projet portable** copie les dépendances dans une archive CMZ ; les répertoires de sortie non référencés ne sont pas copiés intégralement. Les fichiers externes de styles ou services propres aux moteurs natifs ne deviennent pas automatiquement portables.

```python
carte.save("carte.cartomize.json")
carte.save("carte.cmz", portable=True)
carte = cm.Map.load("carte.cmz")
# Pour des fichiers déplacés :
carte = cm.Map.load("carte.cartomize.json", relocate={"/ancien": "/nouveau"})
```

L’historique garde au plus 20 états de session, enregistrés autour des actions principales. Annuler ne supprime pas les fichiers déjà produits. L’onglet **Géométrie des éléments** modifie X, Y, largeur, hauteur, rotation des textes, corps et ordre des éléments d’une maquette, avec schéma actualisé. Ces réglages passent dans les recettes et la sauvegarde. Les textes et légendes sont mesurés ; un débordement persistant bloque l’export avec le nom de l’élément à ajuster. Les étiquettes essaient plusieurs positions et deux corps ; celles qui ne trouvent pas de place sont signalées dans le contrôle visuel. La position géographique des objets reste inchangée.

## Recettes, séries et révision

`save_recipe(carte_ou_configuration, chemin)` conserve une mise en page. Les variables utilisent `${nom}` et sont remplacées explicitement. `run_recipe()` produit PDF et PNG par défaut. `run_batch()` accepte une recette et une liste de tâches :

```json
{
  "schema": "cartomize.batch.v1",
  "recipe_path": "recette.json",
  "dpi": 150,
  "jobs": [
    {"job_id": "nord", "title": "Secteur nord", "layer_bindings": {"Routes": "nord.gpkg"}, "output_formats": ["pdf", "png"]},
    {"job_id": "sud", "title": "Secteur sud", "layer_bindings": {"Routes": "sud.gpkg"}, "output_formats": ["pdf"]}
  ]
}
```

Les noms sont contrôlés avant traitement. L’échec annule la publication du dossier complet par défaut. `continue_on_error=True` conserve les tâches réussies et consigne les échecs explicitement. Les anciennes recettes QGIS/ArcGIS sont migrées avec des associations explicites entre identifiants et fichiers ; les options propres au moteur natif sont conservées dans la recette d’origine, sans promesse de rendu identique. Une recette PAGX est à ouvrir avec ArcGIS Pro. Si un manifeste impose `require_human_validation`, le plan doit être marqué vérifié avant son exécution.

La rubrique **Révision cartographique** calcule les SHA-256 des fichiers de la carte et l’empreinte des paramètres. Elle compare deux instantanés et enregistre une décision nominative. Une approbation est refusée en présence d’erreurs cartographiques bloquantes. Ce document est une révision locale, pas un certificat ni une signature électronique certifiée.

## Terrain et convolution

`cm.terrain(mnt, sortie, products=["slope", "aspect", "hillshade", "tpi", "tri", "roughness"])` utilise un MNT projeté sur une grille orientée au nord. Les unités horizontales sont converties en mètres ; `z_factor` convertit les altitudes calibrées en mètres. La pente est en degrés, l’exposition est l’azimut descendant par rapport au nord de la grille, les pixels plats ont la valeur −1. Les voisinages incomplets sont NoData.

`cm.convolve(source, sortie, kernel, normalize=False)` accepte un noyau impair jusqu’à 127 × 127. Les marges de lecture éliminent les ruptures aux frontières des blocs. Le moteur réutilise les lectures et limite les tâches simultanées et les tableaux selon le budget choisi. Ce budget n’est pas une limite de mémoire du processus entier.

## Projets natifs

`inspect_qgis_project()` lit les références locales QGS/QGZ sans QGIS, sans exécuter les macros du projet. Les services et sous-couches non directement importables sont signalés. Le bouton de transmission importe les sources compatibles, pas leur style natif complet.

`native_project(projet, python=chemin_python_sig, action="inspect"|"copy"|"export", ...)` utilise un processus séparé : ArcPy pour APRX/PAGX ; PyQGIS pour QGS/QGZ/QPT. Il modifie les textes par identifiant et les emprises de cadres, puis enregistre une copie ou exporte PDF/PNG/SVG. Le fichier source n’est jamais enregistré en place. Le nom de la mise en page doit être unique. La passerelle exige les modules et, pour ArcGIS Pro, les conditions de licence du moteur installé. Elle n’a pas été exécutée ici dans ces deux moteurs ; l’inventaire XML et les chemins d’échec sont testés.

Références des appels natifs : [QGIS, chargement des projets](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/loadproject.html), [QGIS, mises en page](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/composer.html), [Esri, Layout](https://doc.esri.com/en/arcgis-pro/latest/arcpy/mapping/layout-class.html). L’apprentissage utilise [RandomForestClassifier et ExtraTreesClassifier de scikit-learn](https://scikit-learn.org/stable/modules/ensemble.html#forests-of-randomized-trees).
