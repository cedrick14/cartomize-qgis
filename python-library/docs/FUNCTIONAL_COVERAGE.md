# Fonctions cartographiques disponibles

La version 0.5.0a1 ajoute un examen initial, des transferts de résultats et un contrôle cartographique, en complément
des fonctions cartographiques déjà accessibles dans la fenêtre. La comparaison ci-dessous s’appuie sur les
commandes de l’extension et sa boîte à outils, présentes dans le dépôt source.

| Fonction | Bibliothèque Python et fenêtre 0.5.0a1 |
|---|---|
| Assistant cartographique | Examen des données, motifs et étapes proposées ; règles explicables |
| Connexions | Résultats transférables ; reprise de production ; configuration carte vers atlas |
| Contrôle de la carte | Géométries, champs, classes échantillonnées et éléments à renseigner |
| Maquettes de mise en page | 24 maquettes disponibles, sélection dans Mise en page et Production automatisée |
| Format et orientation | A4/A3, portrait/paysage pour le modèle standard; dimensions fixées par les autres maquettes |
| Titre, sous-titre, sources | Réglables dans la fenêtre |
| Légende, échelle, orientation | Activation indépendante dans la fenêtre |
| Cadres multiples et encarts | Emprise, système de coordonnées et couches par cadre |
| Texte, tableaux et graphiques | Contenus des emplacements existants, avec fichiers CSV pour tableaux et graphiques |
| Symbologie et étiquettes | Rôles, champs, palettes, opacité, bande et composition colorée |
| Aperçu de mise en page | Rendu réel dans une fenêtre séparée |
| Exports PDF, PNG, SVG | Disponibles |
| Atlas | Une carte par entité, champ de nom, marge, format, progression et annulation entre pages |
| Analyse vectorielle | Audit géométrique, profil des attributs, propositions de champs |
| Analyse du projet | Analyse de plusieurs fichiers, copies masquées, classes, plan JSON et application à la mise en page |
| NoData périphérique | Masquage connexe en périphérie, protection des classes binaires/documentées, règles explicites et rétablissement des sources |
| Nomenclature | Libellés et couleurs éditables ; métadonnées ou saisie utilisateur, sans invention sémantique |
| Analyse raster | Métadonnées, NoData, profil et inférence à partir d’un échantillon |
| Traitements vectoriels | 13 opérations exposées dans la fenêtre |
| Traitements raster | 6 opérations supplémentaires, en plus des calculs et du prétraitement |
| Production depuis les scènes | Mosaïque, composite multibande, masque, composition colorée, couches et mise en page |
| Algèbre, indices et statistiques | Conservés dans des rubriques complémentaires |
| Édition native d’un projet APRX, synchronisation d’une mise en page existante | Non transposées dans cette bibliothèque autonome |
| Export PAGX et commandes de l’interface Esri | Non disponibles |
| Recettes JSON de l’extension et manifeste batch jusqu’à 5 000 cartes | Non compatibles automatiquement; l’atlas Python couvre un autre mode de production en série |
| Audit complet du projet, contrôle des changements MapOps, certificat d’approbation | Non transposés intégralement; Analyse du projet prépare les fichiers sélectionnés, sans lire l’état complet d’un projet natif |
| Choix automatique de variantes et optimisation native des éléments | Non transposés intégralement; choix manuel des maquettes et ordre automatique des couches disponibles |
| Portail et ressources communautaires intégrés | Non intégrés dans la fenêtre Python |

Les moteurs C#/ArcPy et les fichiers de projet natifs n’ont pas été transformés
automatiquement en code Python autonome. Le tableau précise cette limite
pour distinguer les accès ajoutés des fonctions qui nécessitent encore un
portage. Les informations de provenance ne sont pas utilisées comme intitulés
ou slogans dans la fenêtre.

Le [bilan des demandes](REQUEST_AUDIT.md) distingue les réalisations, les
limites partielles et les fonctionnalités absentes.
