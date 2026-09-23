# Couverture fonctionnelle 0.8.0a1

La [liste actuelle des 20 rubriques](TOOL_AUDIT.md) présente leurs algorithmes, sorties et connexions. Le [guide des nouvelles fonctions](AUTOMATION.md) fournit les paramètres et formats de documents.

| Attente | Réalisation |
|---|---|
| Bibliothèque Python et fenêtre pour débutants | API indépendante, 20 rubriques, traitements en arrière-plan |
| Assistant cartographique intelligent | Règles explicables, plan exécutable, propositions de maquettes et reprise de la carte |
| Scènes jusqu’à la carte | Calibration, QA/SCL, mosaïque, multibande, extraction, composition, couches et export |
| NoData et bordures noires | Détection conservatrice, masquage des composantes périphériques, protection des classes et des sources |
| Traitements vectoriels | GeoPandas, superpositions, jointures, proximités, mesures et réparations |
| Raster et indices | Algèbre extensible, 18 indices, statistiques, classification, terrain et convolution |
| Rapidité | Calcul par blocs, lectures partagées, files bornées, échantillonnage borné, arbres parallèles |
| Mise en page | 24 maquettes d’origine, cadres, habillage, dimensions éditables, textes mesurés, étiquettes, aperçu et export |
| Persistance | État des outils, couches, résultats et maquettes ; JSON et archive CMZ ; historique des actions principales |
| Recettes, lots et révision | Variables, associations réelles, journaux, migration, empreintes et décision nominative |
| Chaînes de traitements | 34 opérateurs, dépendances vérifiées, produits secondaires et paramètres moteur transmis |
| Hydrologie, routage et STAC | Drainage D8, bassins, plus court chemin, recherche et téléchargement de scènes |
| Projets natifs | Inventaire QGS/QGZ et import des styles pris en charge opérationnels ; passerelle QGIS testée dans le moteur réel ; validation ArcPy encore requise |
| Identité visuelle | Icône originale en couleur ; titre et contrôles en noir, blanc et gris |
| Publication Python | Wheel, distribution source, métadonnées et documentation ; PyPI non publié |

Les limites restantes sont détaillées dans l’inventaire des outils : parité native complète, couverture universelle des capteurs/algorithmes et performances garanties sur tous les volumes ne sont pas revendiquées.

## Compléments 0.8

Moteurs d’exécution, transfert des styles et validation native : voir [EXECUTION](EXECUTION.md). Les choix Dask/CUDA sont persistés avec la session et transmis aux traitements compatibles. Le calcul distribué utilise des processus réels ; le GPU reste à valider sur le matériel approprié.
