# Analyse du projet et préparation du NoData

Version 0.5.0a1. Le projet est une liste de fichiers raster/vectoriels.
Les projets natifs APRX et QGZ ne sont pas lus.

## Chaîne effective

`analyze_project` diagnostique les fichiers sans les modifier.
`prepare_project` effectue le diagnostic, applique les masques supplémentaires
dans des copies GeoTIFF, dénombre les classes, propose la symbologie et
enregistre `project.json`. La fenêtre utilise cette deuxième fonction.
`PreparedProject.compose` ou **Appliquer à la mise en page** utilise le plan
pour la superposition et le rendu. Le répertoire de préparation doit être neuf.

Les fichiers qui n’exigent pas de masque supplémentaire sont référencés sans
copie. Le projet dépend donc encore de ces sources : conserver leur emplacement.
Les copies modifiées sont référencées relativement au plan JSON.

## Règles de masquage

1. Les masques du fournisseur, NoData déclarés et valeurs non finies restent
   invalides. Une valeur valide égale à zéro n’est pas supprimée par principe.
2. La détection examine un échantillon d’au plus 1 024 × 1 024 pixels. Pour un
   raster monobande à 2–65 valeurs entières, elle examine les codes de remplissage
   possibles : 0, 255, valeurs inférieures ou égales à −999 et supérieures ou
   égales à 9 999. Pour un RVB natif uint8, elle examine le noir et le blanc
   communs aux trois canaux. Les autres multibandes ne reçoivent pas cette
   inférence automatique.
3. Un candidat doit couvrir au moins 80 % du périmètre et 90 % des coins,
   au plus 35 % de la zone centrale, avec un écart périmètre/centre d’au moins
   50 points. Ce sont des seuils heuristiques, sans garantie sémantique.
4. Les rasters uniformes, binaires 0/1 et codes dotés d’une nomenclature
   renseignée sont protégés de cette inférence. `keep_values` protège d’autres
   codes. Ces protections n’annulent pas les NoData déclarés par le fichier.
5. Le masque supplémentaire retient seulement les composantes connexes à
   quatre voisins qui touchent le bord du raster. Les îlots intérieurs de même
   valeur restent valides. L’étiquetage est réalisé sur les pixels originaux,
   par tuiles avec raccordement de leurs composantes.
6. `nodata_values` correspond à une décision explicite : ces valeurs sont
   masquées dans toute l’image. Sur un multibande, tous les canaux de données
   doivent correspondre à la même valeur. Une valeur explicitement conservée
   par `keep_values` reste protégée. Une instruction NoData explicite prime
   sur une nomenclature, sauf protection explicite de la valeur.

Une classe valide touchant les bords peut satisfaire ces seuils. Contrôler le
rapport et la carte ; désactiver l’inférence ou renseigner `keep_values` dans
ce cas. La procédure ne prétend pas reconnaître la signification d’un code.

## Conservation et réversibilité

Les valeurs des bandes ne sont pas réécrites en zéro ni effacées. Le résultat
contient un masque interne de validité : les pixels invalides deviennent
transparents à l’affichage et sont exclus des lectures masquées. La validité
commune exige la validité de toutes les bandes de données. Les descriptions,
échelles, décalages, unités, interprétations colorées et métadonnées courantes
sont conservés ; les aperçus et métadonnées auxiliaires ne sont pas reproduits.

`load_project(manifest, original_sources=True)` rétablit les chemins des
sources et retire les classes préparées. La fenêtre propose **Rétablir les
sources**. Les fichiers d’entrée sont protégés contre leur remplacement.
Une erreur ou une annulation avant publication du nouveau répertoire nettoie
les produits temporaires.

## Classes et nomenclature

Les classes monobandes sont dénombrées exactement par blocs, jusqu’à 64 codes
entiers distincts. Au-delà, ou en présence de valeurs fractionnaires, la
préparation conserve un rendu continu. Une variable entière continue à peu de
valeurs peut être proposée comme classes : le rôle reste réglable en mise en page.

Les libellés viennent de `classes={code: (libellé, couleur)}` ou de la balise
JSON `CARTOMIZE_CLASSES`. Les tables de couleurs raster existantes sont
utilisées si aucune couleur explicite n’est fournie. À défaut, les noms
restent « Classe 2 », « Classe 3 », etc. La fenêtre permet de corriger libellés
et couleurs avant application. Le code 2 ne signifie pas universellement
« forêt primaire ». L’analyse ne réalise pas une classification supervisée.

## Limites de performance

Le diagnostic est échantillonné ; l’application et le comptage sont exacts.
Le masquage connexe lit deux fois les tuiles, puis le comptage des classes
effectue une lecture supplémentaire. Les identifiants de composantes et les
informations par tuile occupent de la mémoire. `max_components` borne leur
nombre ; il ne borne pas la mémoire totale du processus. Aucun gain de vitesse
mesuré n’est revendiqué pour ce nouveau parcours.

La préparation vectorielle propose rôle et étiquettes et réalise l’audit des
géométries. Elle ne lance pas automatiquement toutes les intersections,
analyses de proximité ou corrections topologiques possibles entre couches.
