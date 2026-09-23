# Prise en compte des demandes — version 0.6.0a1

La version 0.6 implémente les principaux manques du précédent audit : plan exécutable, classification supervisée et non supervisée, persistance de session et archives portables, réglages géométriques des maquettes, mesures typographiques, recettes, séries, contrôle des changements et passerelle native optionnelle.

Le parcours commence par l’objectif et les données. Les scènes sont préparées avant les indices ; les couches raster et vectorielles sont superposées selon leurs rôles, puis habillées. Les fonctions de mise en page restent présentes et raccordées. L’icône conserve la ressource originale en couleur. Les titres et contrôles restent sobres, sans slogan « ADN ArcGIS Pro ».

- [Inventaire des outils et algorithmes](TOOL_AUDIT.md)
- [Guide de l’assistant, classification, sauvegarde, recettes et révision](AUTOMATION.md)
- [Couverture des demandes](FUNCTIONAL_COVERAGE.md)
- [Tests et portée de la validation](VALIDATION.md)
- [Audit historique 0.5](TOOL_AUDIT_0.5.md)

Les appels aux moteurs ArcGIS Pro et QGIS sont écrits mais restent à vérifier dans leurs environnements. Les tests sur données synthétiques ne constituent pas une validation terrain, ni une preuve de parité avec l’ensemble des fonctions natives. La publication PyPI n’a pas été effectuée.
