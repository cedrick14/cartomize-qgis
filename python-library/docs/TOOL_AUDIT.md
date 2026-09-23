# Implémentation des outils — Cartomize 0.6.0a1

22 septembre 2026. Les anciens constats sont conservés dans [l’audit 0.5](TOOL_AUDIT_0.5.md). Cette version ajoute des algorithmes et leurs connexions effectives à l’API, à la fenêtre et à la ligne de commande.

## Outils et connexions

| Rubrique | Exécution réelle et sortie |
|---|---|
| Assistant cartographique | Examen, plan dépendant, variantes de maquettes, exécution jusqu’aux exports et reprise de mise en page |
| Analyse du projet | Copies masquées, fond périphérique, classes éditables, application à la carte, rétablissement des sources |
| Analyse des couches | Diagnostic raster et vectoriel |
| Prétraitement multispectral | Calibration, QA/SCL, mosaïque, assemblage multibande, extraction ; sortie scientifique |
| Composition colorée | Quatre compositions spectrales et RVB natif ; sortie RGBA |
| Classification | Forêt aléatoire, arbres extrêmement aléatoires, K-moyennes ; classes, confiance, validation et modèle |
| Traitements vectoriels | 13 opérations GeoPandas, dont superposition, jointure, tampon, dissolution et réparation |
| Traitements raster | Inspection, découpage, reprojection, reclassification, statistiques zonales, surfaces et changements selon le sélecteur |
| Analyse de terrain | Pente, exposition, ombrage, TPI, TRI, rugosité et convolution par blocs |
| Indices spectraux | 18 indices intégrés, paramètres, calibration et correspondances ; registre extensible |
| Calculatrice raster | Expressions analysées sans eval, conditions, fonctions mathématiques et alignement explicite |
| Statistiques focales | Sept statistiques, voisinages complets entre blocs et comptage du NoData |
| Statistiques multirasters | Sept réductions pixel par pixel |
| Mise en page | 24 maquettes, cadres, textes mesurés, étiquettes, tableaux, graphiques, géométrie éditable, aperçu, contrôle et exports |
| Atlas cartographique | Une carte par entité, paramètres transmis depuis la mise en page |
| Production automatisée | Parcours direct scènes → multibande → composition → couches → carte |
| Recettes et production en série | Recettes réutilisables, variables, associations, migration historique, manifestes jusqu’à 5 000 tâches |
| Projets SIG | Inventaire QGS/QGZ, transmission des sources locales ; passerelle native optionnelle pour copie et export |
| Révision cartographique | Instantanés, empreintes, comparaison, décision nominative et contrôle de la carte |

Les résultats raster/vectoriels sont transférables aux outils compatibles. Le plan et les recettes produisent des fichiers réels ; un bouton qui aboutit seulement à une proposition n’est pas compté comme traitement. Les sources restent protégées. Les nouveaux dossiers complets sont publiés après succès ; un lot peut conserver ses succès seulement si la poursuite sur erreur a été demandée.

## Vérifications ajoutées

Les tests comparent les classes prédites à des populations spectrales connues, vérifient la séparation des références avant échantillonnage, les masques, la classe zéro, les probabilités et la réutilisation du modèle. Les dérivées d’un plan incliné sont comparées à des valeurs analytiques, avec égalité entre tailles de blocs et nombre de travailleurs. Les tests de session suppriment les sources originales après création de l’archive, réouvrent les copies et comparent les paramètres de la fenêtre. Les recettes produisent deux cartes et exercent les erreurs, variables et protections de noms. La révision détecte une modification réelle de fichier.

Les nouveaux parcours graphiques utilisent le vrai travailleur Qt pour la classification, le plan exécuté, les recettes, le terrain, la révision et l’inventaire SIG. Les contrôles historiques, les 24 maquettes, les 18 indices et l’intégrité des ressources d’origine restent testés.

## Portée et validation externe restante

- **Passerelle native** : le code des appels ArcPy/PyQGIS est présent et raccordé ; leur exécution doit être validée avec les moteurs installés. La version autonome ne reconstitue pas intégralement tous les objets APRX/QGZ.
- **Cartographie** : les propositions et placements sont des heuristiques contrôlables. Les débordements textuels sont détectés ; une lisibilité parfaite, l’exactitude thématique et tous les conflits visuels ne peuvent pas être certifiés automatiquement.
- **Couverture** : les capteurs reconnus restent Landsat Collection 2 L2 SR et Sentinel-2 L2A, avec correspondances explicites pour les autres. Aucun catalogue fini ne couvre toutes les opérations raster. Hydrologie complète, routage, GPU, calcul distribué et téléchargement de scènes ne sont pas implémentés ici.
- **Publication** : paquet construit et code disponible sur la branche de travail ; pas de dépôt PyPI/TestPyPI ni fusion effectués par cette livraison.
- **Terrain** : les tests synthétiques et Qt hors écran ne remplacent pas une campagne sur des scènes réelles volumineuses et une validation manuelle des moteurs natifs.

Voir [le guide d’utilisation](AUTOMATION.md) et [la validation](VALIDATION.md).
