# Validation de Cartomize 0.8.1a1

23 septembre 2026 · Linux x86_64 · Python 3.12.

## Résultat local

**315 tests réussis, 2 tests différés**, dont 38 cas Qt. Les tests de 0.7 et 0.8 sont conservés. La commande exécutée est `QT_QPA_PLATFORM=offscreen python -m pytest tests -q`.

Les 20 nouveaux tests de 0.8.1 couvrent les quatorze combinaisons de produits avec et sans mosaïque, le découpage polygonal et ses trous, les canaux RVB choisis, la conservation des valeurs/masques/calibrations lors de l’extraction des bandes, les erreurs et annulations sans dossier partiel. Deux parcours Qt exécutent les données sélectionnées, les correspondances manuelles, les sorties indépendantes par scène et la réouverture d’une session portable avec ses cases et canaux.

Les nouveaux tests comparent quarante expressions du calcul CUDA au moteur masqué de référence à travers une interface de tableaux NumPy. Cette vérification porte sur les règles numériques et les masques ; elle n’est pas une exécution CUDA.

Les tests Dask démarrent deux processus distincts, vérifient leurs identifiants, puis exécutent algèbre, indices, réductions, statistiques focales, terrain et convolution. Leurs sorties sont comparées pixel par pixel au CPU avec des marges de blocs. Un cluster local créé automatiquement, l’annulation, la CLI et un vrai travailleur Qt sont également exercés.

Les tests de styles vérifient les bornes des classes graduées, le masquage des catégories, les tailles de points en unités physiques, les symboles composites, les trois modes de rampe raster, le contraste en niveaux de gris et la persistance des projets.

## Tests différés et CI

- **CUDA matériel** : le test réel est présent et activé lorsqu’un GPU CUDA utilisable est détecté. Aucun périphérique CUDA n’est accessible dans l’environnement local ; ce test est donc explicitement ignoré. Un choix CUDA sans GPU provoque une erreur contrôlée.
- **QGIS natif** : le test nécessite `CARTOMIZE_QGIS_PYTHON`. Un travail CI `qgis` installe le vrai moteur QGIS, crée un projet synthétique et vérifie inventaire, styles gradués, import, copie et exports PDF/PNG/SVG. Ce test a réussi sur le commit `8ca5e45b3c8efd4012ed127f7ee76efbe6048428` : [exécution CI](https://github.com/cedrick14/cartomize-qgis/actions/runs/35898874111).
- **ArcGIS Pro** : la procédure de validation native est implémentée, mais elle reste à exécuter avec ArcGIS Pro/ArcPy et sa licence. Aucun succès simulé n’est comptabilisé.

La matrice principale exécute les tests, la construction et Twine sous Linux et Windows, Python 3.11 et 3.12, avec Dask installé. Les résultats du commit final sont joints à la livraison. Les avertissements de dépréciation Rasterio et les avertissements statistiques sur des ensembles entièrement masqués sont recensés dans les journaux.

## Distribution et portée

Le wheel et les sources sont construits par `python -m build`, puis contrôlés avec `python -m twine check dist/*`. Les sources d’origine et les 24 maquettes restent couvertes par les tests d’intégrité.

Les données de test sont synthétiques. Une campagne sur de grandes scènes réelles, un benchmark CUDA et une mesure sur plusieurs machines restent nécessaires avant toute promesse de performance. Le budget des tableaux n’est pas un plafond mémoire du processus. Les limitations détaillées figurent dans [EXECUTION](EXECUTION.md) et [TOOL_AUDIT](TOOL_AUDIT.md). Aucun paquet PyPI/TestPyPI n’est publié par cette livraison.
