# Implémentation des outils — Cartomize 0.8.1a1

23 septembre 2026. Les anciens constats sont conservés dans [l’audit 0.5](TOOL_AUDIT_0.5.md). Cette version raccorde les traitements et ajoute des algorithmes et leurs connexions effectives à l’API, à la fenêtre et à la ligne de commande.

## Outils et connexions

| Rubrique | Exécution réelle et sortie |
|---|---|
| Assistant cartographique | Examen, plan dépendant, variantes de maquettes, exécution jusqu’aux exports et reprise de mise en page |
| Analyse du projet | Copies masquées, fond périphérique, classes éditables, application à la carte, rétablissement des sources |
| Analyse des couches | Diagnostic raster et vectoriel |
| Prétraitement multispectral | Tableau des bandes par scène, correspondances manuelles, calibration, QA/SCL, mosaïque facultative, assemblage multibande, extraction par masque, canaux RVB et GeoTIFF monobandes séparés ; session persistante |
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
| Projets SIG | Inventaire QGS/QGZ, import des sous-couches et styles pris en charge ; passerelle native optionnelle pour copie et export |
| Chaîne de traitements | 34 opérateurs, références aux résultats et produits secondaires, paramètres moteur, exécution autonome ou intégrée à la carte |
| Révision cartographique | Instantanés, empreintes, comparaison, décision nominative et contrôle de la carte |

Les résultats raster/vectoriels sont transférables aux outils compatibles. Le plan et les recettes produisent des fichiers réels ; un bouton qui aboutit seulement à une proposition n’est pas compté comme traitement. Les sources restent protégées. Les nouveaux dossiers complets sont publiés après succès ; un lot peut conserver ses succès seulement si la poursuite sur erreur a été demandée.

## Vérifications ajoutées

Les tests comparent les classes prédites à des populations spectrales connues, vérifient la séparation des références avant échantillonnage, les masques, la classe zéro, les probabilités et la réutilisation du modèle. Les dérivées d’un plan incliné sont comparées à des valeurs analytiques, avec égalité entre tailles de blocs et nombre de travailleurs. Les tests de session suppriment les sources originales après création de l’archive, réouvrent les copies et comparent les paramètres de la fenêtre. Les recettes produisent deux cartes et exercent les erreurs, variables et protections de noms. La révision détecte une modification réelle de fichier.

Les nouveaux parcours graphiques utilisent le vrai travailleur Qt pour la classification, le plan exécuté, les recettes, le terrain, la révision et l’inventaire SIG. Les contrôles historiques, les 24 maquettes, les 18 indices et l’intégrité des ressources d’origine restent testés.

## Portée et validation externe restante

- **Passerelle native** : la commande `native-validate` exécute inventaire, copie et exports PDF/PNG/SVG dans le moteur installé. Un travail CI dédié utilise réellement QGIS ; ArcPy nécessite encore une validation sur un poste ArcGIS Pro licencié. La version autonome ne reconstitue pas intégralement tous les objets APRX/QGZ.
- **Cartographie** : les propositions et placements sont des heuristiques contrôlables. Les débordements textuels sont détectés, les légendes utilisent plusieurs colonnes et les étiquettes évitent les symboles ponctuels ; une lisibilité parfaite, l’exactitude thématique et tous les conflits visuels ne peuvent pas être certifiés automatiquement.
- **Couverture** : la reconnaissance par noms reste Landsat Collection 2 L2 SR et Sentinel-2 L2A. Les autres produits peuvent être décrits par STAC ou un manifeste de bandes explicite. Aucun catalogue fini ne couvre toutes les opérations raster. Le drainage D8, les bassins, le routage bidirectionnel et le téléchargement HTTP(S) STAC sont implémentés. Les modèles hydrauliques, MFD/D-infinity et les contraintes routières avancées ne sont pas implémentés. Dask exécute les traitements par blocs dans des processus séparés ou sur un cluster explicite. CUDA est implémenté pour l’algèbre, les indices et les réductions, mais nécessite encore une validation matérielle.
- **Publication** : paquet construit et code disponible sur la branche de travail ; pas de dépôt PyPI/TestPyPI ni fusion effectués par cette livraison.
- **Terrain** : les tests synthétiques et Qt hors écran ne remplacent pas une campagne sur des scènes réelles volumineuses et une validation manuelle des moteurs natifs.

Voir [le guide d’utilisation](AUTOMATION.md) et [la validation](VALIDATION.md).

## Corrections 0.7 vérifiées

Enchaînement terrain → calculatrice → statistiques → carte ; 13 opérateurs vectoriels et six opérateurs raster exécutés via le registre ; sorties secondaires hydrologiques ; import QGIS catégorisé avec sous-couche et groupe masqué ; zéro valide dans une emprise ; code raster rare absent de la nomenclature ; téléchargement STAC avec pagination, empreintes et annulation transactionnelle ; session STAC portable. Les formulaires exécutent les fonctions réelles et conservent les étapes après réouverture.

Voir [PROCESSING](PROCESSING.md) pour les paramètres, hypothèses et limites de chaque algorithme.

## Compléments 0.8

Les réglages d’exécution sont reliés à la CLI, aux outils concernés, à l’assistant et aux sessions. Les catégories masquées, classes graduées, traits, symboles simples et composites, palettes exactes/discrètes/interpolées et contrastes en niveaux de gris sont transférés. Les expressions QGIS, symboles SVG natifs, propriétés définies par les données et certains effets restent signalés comme non transférés ; leur rendu intégral se fait par le moteur QGIS. Le transfert ne revendique pas une reproduction universelle.
