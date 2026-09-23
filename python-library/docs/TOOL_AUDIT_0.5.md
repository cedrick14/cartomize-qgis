# Audit des outils — Cartomize Python 0.5.0a1

22 septembre 2026 · Fondateur : ONDON NKOUA Cédrick Belmich.

**Conclusion : les outils exposés exécutent des traitements réels, mais l’ensemble des ambitions discutées et des fonctions natives n’est pas entièrement implémenté.** Cette version corrige des défauts de calcul, de conservation des paramètres et de connexion. Elle place l’examen du projet avant les traitements. Le terme « assistant cartographique intelligent » désigne ici des règles explicables et des recommandations fondées sur les données, pas un agent autonome capable de décider de leur validité scientifique.

L’audit porte sur les modules publics Python, les 14 rubriques de la fenêtre, leurs sélecteurs d’opérations, les transferts, la ligne de commande et les maquettes. Les dix modules historiques conservés dans `_core` ne signifient pas que tous les services ArcGIS Pro ont été portés. Une recherche de fonctions vides ne suffit pas : les vérifications ci-dessous exécutent les traitements et contrôlent leurs résultats.

## Logique de travail

Un cartographe commence par l’objectif, les données disponibles, l’emprise, la projection et la qualité des sources. Les indices ne constituent pas le point de départ obligatoire.

1. **Examen initial** : objectif général, administratif, occupation du sol ou atlas ; inventaire, géométries, systèmes de coordonnées, fonds périphériques et provenance spectrale.
2. **Préparation des données** : réparation si nécessaire ; calibration et qualité pour les scènes ; masques et nomenclature pour les couches déjà constituées.
3. **Traitements adaptés à l’objectif** : mosaïque, assemblage multibande et découpage ; analyses raster/vectorielles seulement si utiles. Une composition colorée ne remplace pas une classification.
4. **Composition cartographique** : ordre des couches, emprise, projection, symbologie et étiquettes.
5. **Mise en page** : maquette, cadres, titre, sources, légende, échelle, orientation et contenus.
6. **Contrôle et restitution** : contrôle technique, aperçu, examen visuel, export ou atlas.

Pour les scènes, les masques de qualité et la calibration sont appliqués **avant l’interpolation**. Mosaïque, assemblage et extraction sont réalisés par blocs sur une grille commune ; leur logique n’exige pas trois copies intégrales intermédiaires. Le multibande scientifique reste distinct du RGBA destiné à l’affichage.

## Inventaire des rubriques et connexions

« Implémenté » signifie que le traitement indiqué existe et a été exécuté dans le périmètre décrit. Il ne signifie pas absence de tout défaut possible ni compatibilité avec tous les jeux géographiques.

| Rubrique | Algorithme ou fonction | Connexion effective | État et limites |
|---|---|---|---|
| Assistant cartographique | `assess_project` : diagnostic, règles de priorité, motifs et proposition de maquette | Ouvre les étapes avec sources, titre et AOI ; signale les cadres à préciser | **Partiel** : recommandations explicables ; pas de planification spatiale universelle ni de validation scientifique autonome |
| Analyse du projet | `analyze_project`, `prepare_project`, `load_project`, détection et masquage du fond | Classes éditées et sources transmises à Mise en page ; rétablissement des sources ; résultats réutilisables | **Implémenté pour des fichiers sélectionnés** ; ne lit pas l’état complet APRX/QGZ |
| Analyse des couches | Profils d’attributs et audit géométrique ; diagnostic raster | Entrée directe ou résultat transféré, rapport JSON affiché | **Implémenté** ; géométries exhaustives, attributs et rasters échantillonnés |
| Prétraitement multispectral | Découverte, calibration, QA/SCL, grille commune, mosaïque, assemblage, masque polygonal | Répertoire ou fichiers ; sorties proposées aux outils suivants ; multibande prérempli pour Indices et Composition | **Implémenté pour produits reconnus** ; autres capteurs via `Scene`/`Band` explicites en Python |
| Composition colorée | Affectation RGB, étirement percentiles, alpha NoData | Multibande en entrée ; RGBA transférable à Mise en page | **Implémenté** ; produit de visualisation, pas de réflectance ni de classes |
| Traitements vectoriels | 13 opérations détaillées ci-dessous | Sources/résultats GeoPackage ou GeoJSON transférables | **Implémenté** ; calculs délégués à GeoPandas/Shapely, pas de moteur spatial universel nouveau |
| Traitements raster | 6 opérations détaillées ci-dessous | Raster, couche zonale ou CSV selon l’opération | **Implémenté dans ce périmètre** ; découpage/reprojection ici sur une bande choisie |
| Indices spectraux | 18 formules et registre extensible | Correspondance spectrale, paramètres, calibration ; GeoTIFF multibande de résultats | **Implémenté pour ces formules** ; tous les indices existants ne sont pas intégrés |
| Calculatrice raster | Analyse AST, fonctions autorisées, masques, calcul par blocs | Rasters produits ajoutables au tableau des variables | **Implémenté pour le langage documenté** ; pas de Python arbitraire ni de tout algorithme raster |
| Statistiques focales | Fenêtres carrées et marges entre blocs, 7 statistiques | Raster produit réutilisable | **Implémenté** ; pas de noyau de convolution arbitraire dans la fenêtre |
| Statistiques multirasters | Réduction pixel par pixel, 7 statistiques | Résultats ajoutables à la liste des sources | **Implémenté** ; grilles compatibles requises, pas de modèle temporel ni de détection causale |
| Mise en page | 24 maquettes, cadres, styles, contenus, contrôle, aperçu, export | Analyse → carte ; production complète → reprise ; carte → atlas avec configuration | **Partiel par rapport à l’édition native** ; pas d’éditeur libre de tous les objets ni d’optimisation avancée |
| Atlas cartographique | Emprise par entité, nom, marges et export | Reçoit couches et habillage ; demande la couche d’index | **Implémenté pour une page par entité** ; pages déjà terminées conservées si annulation |
| Production automatisée | `cartographic_workflow` : scènes → multibande → RGBA → superposition → exports | Rapports et produits enregistrés ; reprise de la mise en page avec couches/AOI/habillage dans la session | **Implémenté pour ce parcours** ; pas de choix automatique de toutes les analyses ni de classification |

Les résultats géographiques sont proposés dans **Résultats du projet**. Le transfert est explicite : il ne lance pas silencieusement une analyse et ne confond pas une image d’affichage avec un raster scientifique. Les CSV restent des fichiers de résultats : ils peuvent alimenter les tableaux/graphiques par sélection de fichier ; leur affectation automatique à une maquette n’est pas implémentée. Les transferts et configurations de fenêtre sont conservés pendant la session ; le plan `project.json` persiste l’analyse des couches, pas tout l’état de toutes les pages.

## Chaque opération vectorielle

| Outil | Exécution | Vérification |
|---|---|---|
| Découpage | `vector.clip`, reprojection du masque | Géométrie et superficie de l’intersection |
| Zone tampon | `vector.buffer`, distance en mètres, conversion des pieds | Superficie attendue et sources inchangées |
| Intersection | `overlay(how='intersection')` | Superficie commune |
| Union | `overlay(how='union')` | Couverture totale |
| Différence | `overlay(how='difference')` | Partie de gauche hors droite |
| Différence symétrique | `overlay(how='symmetric_difference')` | Parties non communes |
| Jointure spatiale | `sjoin`, prédicat et type de jointure | Attributs associés, alignement des CRS |
| Dissolution | `dissolve`, champ de regroupement | Géométrie regroupée |
| Reprojection | `to_crs` | CRS cible et géométrie |
| Réparation des géométries | `make_valid` | Géométries invalides corrigées |
| Superficies | Mesure plane, m²/ha/km² | Valeurs et conversion des unités |
| Longueurs | Mesure plane, m/km | Périmètre/longueur attendu |
| Proximité | `sjoin_nearest`, distance en mètres, seuil facultatif | Égalités conservées, conversion des pieds, absence de correspondance |

Les mesures nécessitent une projection appropriée. Les degrés ne sont pas traités comme des mètres. La réparation peut produire des géométries multiparties ou des collections : elle ne garantit pas la correction sémantique des objets. Les appels vectoriels ne sont pas interruptibles au milieu d’une opération GeoPandas.

## Chaque opération raster et spectrale

| Famille | Opérations réellement disponibles | Conditions |
|---|---|---|
| Extraction | `raster.clip` | Bande choisie, masque reprojeté ; données et calibration conservées ; emprise recoupante requise |
| Reprojection | `raster.reproject` | Bande choisie ; voisin proche par défaut, bilinéaire/cubique disponibles ; calibration conservée |
| Reclassification | `raster.reclassify` | Codes exacts ; conserver ou masquer les valeurs non répertoriées ; pas d’intervalles arbitraires dans ce sélecteur |
| Statistiques zonales | `raster.zonal_stats` | Valeurs valides de chaque zone ; zones chevauchantes calculées indépendamment |
| Superficies par classe | `raster.class_areas` | Comptage exact et aire du pixel via déterminant affine, unités projetées |
| Matrice de transition | `raster.change_matrix` | Paires de codes ; grilles identiques et masque valide commun |
| Différence normalisée | `raster.normalized_difference`, `raster.ndvi` | Deux bandes distinctes, calibration, masque et dénominateur nul |
| Indices | NDVI, EVI, EVI2, SAVI, OSAVI, MSAVI, GNDVI, NDRE, NDWI, MNDWI, NDMI, NBR, NBR2, NDBI, BSI, ARVI, VARI, SR | 18 attentes numériques indépendantes ; paramètres explicites ; aucune interprétation thématique automatique |
| Indices personnalisés | `register_index`, `calculate` | Toute formule exprimable dans le langage autorisé ; persistance du registre limitée au processus |
| Focales | Moyenne, somme, minimum, maximum, écart-type, étendue, nombre | Fenêtre carrée impaire ; gestion des bords, effectif minimal, conservation facultative du NoData central |
| Multirasters | Moyenne, somme, minimum, maximum, écart-type, médiane, nombre | Masques pris en compte ; nombre = zéro quand aucune observation ; seuil d’effectif désactivé pour ce comptage |
| Compositions | Couleurs naturelles, végétation, SWIR, agriculture ; RGB natif via API | Noms spectraux ou correspondance explicite ; affichage séparé des données scientifiques |

Les références des indices figurent dans leur catalogue. La convention OSAVI intégrée est `(NIR − rouge)/(NIR + rouge + 0,16)`, comme dans le [catalogue Awesome Spectral Indices](https://github.com/awesome-spectral-indices/awesome-spectral-indices/blob/main/output/spectral-indices-dict.json). Une variante avec facteur 1,16 peut être enregistrée sous un nom distinct. Le choix de convention ne doit pas rester implicite.

L’algèbre gère arithmétique, comparaisons, logique, conditions, remplacement des valeurs absentes, fonctions mathématiques et réductions du catalogue. La syntaxe est analysée sans `eval` Python. Les expressions trop longues et les appels non autorisés sont refusés. Un alignement éventuel doit être demandé explicitement. Voir [les calculs raster](RASTER_CALCULATIONS.md).

## NoData et bordures noires

- Les masques et NoData déclarés sont prioritaires. Un zéro valide ne devient pas automatiquement NoData.
- Les candidats non déclarés sont inférés sur un échantillon. Leur application parcourt réellement les pixels et les composantes à quatre voisins touchant les bords.
- Les rasters binaires 0/1, les classes documentées et les valeurs protégées ne sont pas éliminés par défaut.
- Les îlots intérieurs de la même valeur sont conservés lors du seul masquage périphérique. Les valeurs NoData supplémentaires saisies explicitement s’appliquent globalement.
- Les sources restent intactes ; les masques sont écrits dans des copies. Libellés et couleurs passent dans le plan et la légende.
- **Limite :** toute bordure noire n’est pas forcément du NoData. Le diagnostic ne connaît pas la vérité terrain ; l’utilisateur doit vérifier les propositions et la nomenclature.

## Défauts corrigés par cet audit

1. Découpage et reprojection pouvaient perdre facteurs/offsets, noms et unités des bandes. Leur conservation est désormais testée jusqu’au calcul suivant.
2. Certaines protections de sortie omettaient un masque vectoriel ou une entrée non utilisée par la formule. Les sources fournies sont protégées.
3. Des anciens fichiers auxiliaires GDAL pouvaient imposer un masque ou une géoréférence à un nouveau raster. Ils sont invalidés après remplacement réussi.
4. Des paramètres de style et RGB n’étaient pas transmis pendant l’analyse ; les transferts conservent maintenant ces options.
5. Une nomenclature numérique vectorielle ne forçait pas toujours un rendu catégoriel. Elle est prise en compte.
6. Les exports cartographiques écrivaient directement la destination. Ils sont désormais préparés dans un fichier temporaire, contrôlés et remplacés après réussite.
7. Des identifiants de textes/tableaux/graphiques inexistants étaient acceptés sans effet. Ils sont refusés.
8. Des réglages de cadres disparaissaient au rafraîchissement du panneau. Ils sont conservés et transférés à l’atlas.
9. Les résultats de nombreux outils étaient isolés. Le registre de résultats, les transferts, la reprise de production et le passage carte → atlas sont raccordés.
10. Une composition d’affichage pouvait être utilisée pour calculer un indice. Les produits RGBA Cartomize sont maintenant refusés par l’outil spectral ; les correspondances spectrales dupliquées sont également refusées.
11. Le seuil d’effectif du comptage multiraster pouvait être ignoré silencieusement. Le réglage est désactivé pour ce mode et un seuil incompatible est refusé par l’API.
12. L’atlas ne vérifiait pas les noms de fichiers réservés sous Windows ni la validité de toutes les géométries d’index. Ces contrôles sont ajoutés.

## Ce qui manque encore

| Demande large ou fonction native | État réel |
|---|---|
| Lecture/édition intégrale APRX/QGZ, synchronisation native, export PAGX | Absent |
| Ensemble des recettes et manifestes batch historiques, services C#/ArcPy, workflow MapOps et certificat d’approbation | Non porté intégralement |
| Choix autonome de toutes les relations spatiales, styles, analyses et variantes de maquette | Partiel : rôles, priorités, catégories et opérations explicites ; pas de planificateur général |
| Placement optimal de toutes les étiquettes, contrôle des débordements et lisibilité parfaite | Partiel : heuristique simple et aperçu ; vérification visuelle requise |
| Classification supervisée/non supervisée d’occupation du sol | Absente ; indices et compositions ne la remplacent pas |
| Tous les capteurs, tous les indices et toute opération raster possible | Non ; produits reconnus et catalogue extensible, sans couverture universelle |
| Hydrologie complète, classification apprentissage automatique, réseaux routiers, GPU, calcul distribué | Non implémentés dans cette livraison |
| Téléchargement automatique des scènes/fonds, catalogue distant et portail communautaire | Absents ; traitement de fichiers locaux |
| Projet persistant contenant l’état intégral de tous les outils et dépendances | Partiel : plan d’analyse persistant et manifestes de production ; transferts graphiques en session |
| Publication PyPI/TestPyPI et adoption communautaire | Non effectuées ; paquet, métadonnées et procédure disponibles |
| Validation manuelle sur bureau Windows et campagnes sur grands jeux réels | À effectuer ; tests automatisés et jeux synthétiques ne la remplacent pas |

## Preuves et portée

Les **181 tests** couvrent valeurs, masques, unités, erreurs, annulation, protection des sources, scènes, superposition, widgets réels, transferts et exports. Les 24 maquettes ont chacune été rendues avec données synthétiques et contenus de leurs emplacements. Les 18 indices sont confrontés à des résultats numériques fixés indépendamment du registre de formules. Les 13 sélecteurs vectoriels et 6 sélecteurs raster exécutent chacun leur algorithme depuis les classes de la fenêtre, avec résultats contrôlés. Les parcours principaux passent aussi par le véritable travailleur Qt.

Tests concernés : `test_audit.py`, `test_desktop.py`, `test_project.py`, `test_imagery.py`, `test_algebra.py`, `test_vector.py`, `test_raster.py`, `test_maps.py`, `test_composition.py`, `test_workflow.py`.

La réussite des tests ne démontre pas une complétude universelle. Les rasters des diagnostics et du rendu sont échantillonnés, certaines opérations chargent une emprise entière, et les écritures des trois fichiers d’un produit multispectral ne constituent pas une transaction atomique unique en cas de panne système. Les limites sont détaillées dans [VALIDATION](VALIDATION.md), [ARCHITECTURE](ARCHITECTURE.md) et [PERFORMANCE](PERFORMANCE.md).
