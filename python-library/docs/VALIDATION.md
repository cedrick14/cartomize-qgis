# Validation de Cartomize Python 0.3.0a2

Validation locale du 22 septembre 2026, Linux x86_64, Python 3.12.14.

## Résultats

- **88 tests automatisés réussis**, dont cinq tests de l'interface Qt réelle
  en mode hors écran. Les 52 tests de la version 0.2 restent inclus.
- Vérification de l'algèbre, des indices, des masques, des statistiques et de
  l'égalité entre calcul séquentiel et calcul concurrent.
- Lancement par les widgets des indices, du calculateur, du prétraitement
  multiscène et de la composition cartographique; sortie raster/image vérifiée.
- Réactivité de la boucle d'événements Qt et annulation vérifiées.
- Benchmark reproductible : trois indices, quatre bandes, 2 048 × 2 048 pixels,
  trois répétitions; 2,55 s contre 1,37 s en médiane, sorties identiques.
- Wheel et archive source construits; métadonnées vérifiées avec Twine.
- Installation du wheel avec dépendances graphiques dans un environnement
  distinct du code source, calcul réel et ouverture de la fenêtre vérifiés.

## Parcours ajouté en 0.3.0a2

Le test graphique principal démarre sur Production automatisée, vérifie
l'icône embarquée, puis traite deux scènes Landsat synthétiques avec une zone
d'étude et des localités. Il contrôle le nombre et les valeurs des bandes,
le découpage, le GeoTIFF RGBA, les exports PDF/PNG, les chemins du rapport et
la conservation du rôle et des étiquettes des localités.

Trois tests supplémentaires couvrent la sélection de fichiers de bandes,
l'annulation après mosaïque, l'échec d'un export, la préservation d'un
répertoire existant et l'annulation de la composition colorée entre blocs.

Le benchmark de la version 0.3.0a1 n'a pas été réexécuté pour cette correction
d'interface et d'orchestration. Ses mesures sont conservées comme résultats
de cette version, sans nouvelle promesse de performance.

## Calculs contrôlés

Formules et paramètres NDVI/EVI/SAVI/NDMI; indice personnalisé; contrôle des
bandes; calibration GDAL et remplacement explicite; domaines mathématiques
invalides; divisions par zéro; débordement float32; zéro valide; sélection de
branche conditionnelle; complément de valeurs absentes; masque de qualité
par bits; logique et comparaisons chaînées; rejet de syntaxe Python exécutable.

Statistiques multirasters avec observations manquantes et effectif minimal;
sept statistiques focales comparées à des voisinages explicites, y compris
aux bords de l'image et aux limites des blocs; grilles incompatibles et
alignement explicite; paramètres de mémoire; expressions multibandes;
progression; annulation préservant un fichier existant; nettoyage temporaire.

Les tests antérieurs couvrent notamment les opérations GeoPandas, les mesures
projetées, les NDVI/reclassifications, statistiques zonales, surfaces et
changements, les mosaïques cohérentes, masques QA/SCL, calibration Sentinel,
compositions RGBA, l'ordre des couches et les maquettes héritées.

## Portée et limites

La suite produit 177 avertissements de dépréciation de l'opérateur Affine
employé par Rasterio; ils ne provoquent pas d'échec de test.

Le benchmark utilise des données synthétiques et un cache non purgé. Il ne
mesure pas la vitesse de tous les traitements. La consommation totale de
mémoire dépasse le budget des seuls tableaux de blocs. Voir le
[rapport de performances](PERFORMANCE.md) et ses données brutes.

Les contrôles Qt hors écran ne remplacent pas un essai manuel de bureau
Windows avec des scènes réelles. Le workflow prévoit Windows/Linux et
Python 3.11/3.12, y compris les dépendances graphiques; consulter ses résultats
avant de présenter ces autres environnements comme validés.

Cette livraison reste une alpha. La classification automatique d'occupation
du sol, les projets APRX/QGZ et les traitements spécialisés non implémentés
ne sont pas couverts. Aucune publication TestPyPI/PyPI n'a été effectuée.
