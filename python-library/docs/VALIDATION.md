# Validation de Cartomize Python 0.7.0a1

23 septembre 2026 · Linux x86_64 · Python 3.12.14.

## Résultat local

**236 tests automatisés réussis**, dont 34 cas utilisant les classes et widgets Qt réels, en mode hors écran. Les 198 tests de la version 0.6 sont conservés.

- Classification : deux algorithmes supervisés, K-moyennes, validation séparée, conflits de référence, persistance du modèle, NoData et probabilités.
- Sessions : paramètres de la fenêtre réouverts, projet portable avec fichiers d’origine supprimés, protection contre les chemins d’archive invalides.
- Plans, recettes et lots : produits réels, sorties réouvrables, variables, erreurs et poursuite explicite.
- Terrain : résultats analytiques sur un plan incliné, convolution et égalité entre blocs/threads.
- Inventaire QGZ, échecs du moteur absent, empreintes et modification réelle de fichier.
- Les 18 indices intégrés sont confrontés à des valeurs numériques indépendantes du registre de formules.
- Les 7 statistiques multirasters et les 7 statistiques focales sont comparées à des attentes NumPy ou à des voisinages explicites.
- Chacune des 13 opérations vectorielles et des 6 opérations raster est exécutée depuis son sélecteur graphique, avec contrôle du résultat.
- Les 24 maquettes sont chacune exportées, en renseignant leurs textes, tableaux et graphiques.
- Les tests de parcours utilisent le véritable travailleur Qt : scènes → multibande/RGBA/cartes ; analyse du projet → nomenclature → export/rétablissement ; assistant → projet → mise en page → contrôle → atlas ; raster → indices → calculatrice.
- Calibration après découpage/reprojection, sources protégées, masques auxiliaires, sorties préservées en cas d’échec, géométries invalides, réglages de cadres, produits scientifiques et produits d’affichage sont vérifiés.
- Empreintes des modules et ressources d’origine vérifiées ; aucun import ArcPy ou QGIS requis.

Commande : `python -m pytest tests -q` depuis `python-library`.

Les avertissements locaux proviennent de la dépréciation de l’opérateur de multiplication affine employé par Rasterio. Aucun échec n’en résulte. Le nombre peut varier avec les versions des dépendances.

## Distribution

Le wheel et la distribution source sont construits avec `python -m build`, puis contrôlés avec `python -m twine check`. Un environnement distinct du code source sert à vérifier l’import du paquet installé, l’ouverture de la fenêtre, l’examen du projet, le masquage, la composition, le contrôle et l’export de données synthétiques. Les captures de livraison proviennent de cette fenêtre réelle.

Le workflow `python-library.yml` exécute les tests et la construction sur Linux et Windows, Python 3.11 et 3.12. Le résultat d’un commit est consultable dans GitHub Actions ; un résultat ancien ne prouve pas la réussite d’un nouveau commit.

## Performances mesurées

Mesure historique de 0.5.0a1, conservée sans extrapolation aux nouveaux algorithmes : 2 048 × 2 048 pixels, quatre bandes, trois indices, trois répétitions dans des processus distincts, ordre tournant et cache non purgé. Médianes : 2,713 s pour trois calculs séparés ; 2,343 s pour le calcul groupé à un thread ; 1,750 s à quatre threads. Les sorties sont identiques selon les empreintes de toutes les bandes, après normalisation des NaN et des zéros signés.

Le gain mesuré de 1,55 fois concerne ce scénario, pas tous les traitements. Les tâches concurrentes, le stockage et les caches influencent les mesures. Le budget des tableaux n’est pas un plafond de mémoire du processus. Voir [PERFORMANCE](PERFORMANCE.md) et [les mesures brutes](BENCHMARK_0.5.0a1.json).

## Limites de la validation

Les données sont synthétiques. Les contrôles Qt hors écran ne remplacent pas un essai manuel sous Windows avec de grandes scènes réelles. Les diagnostics raster utilisent des échantillons ; le contrôle cartographique ne certifie ni la vérité thématique, ni l’absence de toutes les collisions d’étiquettes, ni la lisibilité parfaite.

Le détail des fonctions implémentées, partielles et absentes figure dans [TOOL_AUDIT](TOOL_AUDIT.md). La bibliothèque reste alpha. La classification est implémentée et testée. Les appels natifs ArcPy/PyQGIS restent à valider dans les moteurs installés ; la lecture autonome intégrale APRX/QGZ et la couverture de tous les algorithmes raster ne sont pas revendiquées. Aucun paquet n’a été publié sur PyPI/TestPyPI dans cette livraison.

## Validation des corrections 0.7

Les 38 nouveaux cas vérifient les opérations enregistrées, la topologie du plan avant écriture, la conservation des sources, les produits secondaires, les paramètres, les empreintes de téléchargement, la pagination STAC et les références de session. Les valeurs de pente, d’accumulation et de longueur sont comparées à des résultats analytiques. Les téléchargements sont exercés contre un véritable serveur HTTP local contrôlé ; aucun accès à un fournisseur privé n’est revendiqué. Trois cas Qt supplémentaires utilisent les vrais formulaires et travailleurs.

La construction et Twine sont vérifiés sur le paquet 0.7. Les passerelles natives nécessitent encore des tests dans les moteurs installés ; la tentative d’installation de PyQGIS dans l’environnement local n’a pas abouti en raison des restrictions du gestionnaire système.
