# Performances du calcul raster

Mesures locales effectuées le 22 septembre 2026. Elles décrivent ce benchmark,
sans garantir le même gain sur tous les rasters et matériels.

## Protocole

- Raster synthétique de 2 048 × 2 048 pixels (4 194 304 pixels), quatre bandes
  float32 de réflectance et 1,5 % de pixels NoData, source GeoTIFF LZW tuilée.
- Calcul de NDVI, NDMI et NBR. La référence utilise trois appels séparés à
  `normalized_difference`, fonction conservée du moteur 0.2.
- Le moteur 0.5.0a1 calcule les trois indices en un passage, sur un ou quatre threads.
- Trois répétitions par mode, ordre tournant, processus Python distincts.
- Chronométrage du calcul jusqu'à la fermeture/publication des fichiers;
  chargement de Python et vérification des résultats hors chronométrage.
- Cache système non purgé. Il s'agit d'un essai avec lectures répétées;
  la génération des données peut déjà alimenter le cache du système.
- Comparaison de toutes les valeurs et des masques par empreintes des bandes
  float32, après canonicalisation des NaN et des zéros signés. Égalité confirmée.
- Sorties LZW : trois fichiers dans le cas séparé; un fichier multibande dans
  le cas groupé, avec prédicteur flottant. Les modes mesurent les configurations
  réellement livrées, et pas seulement l'effet isolé du nombre de threads.

## Résultats

| Configuration | Médiane (s) | Facteur de vitesse relatif | Pic RSS maximal (Mio) |
|---|---:|---:|---:|
| Trois appels séparés | 2.713 | 1.00 | 268.0 |
| Trois indices groupés, un thread | 2.343 | 1.16 | 409.3 |
| Trois indices groupés, quatre threads | 1.750 | 1.55 | 417.6 |

Le traitement groupé avec quatre threads réduit ici la durée d'environ 35 %.
Il consomme davantage de mémoire que les appels séparés. Le budget de blocs
ne constitue pas un plafond de la mémoire du processus; caches GDAL, imports
Python et bibliothèques s'ajoutent aux tableaux de calcul. Les GeoTIFF de
sortie représentent environ 57,3 Mo en fichiers séparés et 58,6 Mo en multibande.

Environnement : Linux x86_64, Python 3.12.14, neuf processeurs logiques visibles,
NumPy 2.5.3, Rasterio 1.5.1. Le matériel réel, les quotas du conteneur, le cache
et les tâches concurrentes influencent les mesures. Aucun résultat GPU ou
Windows n'est déduit de cet essai.

## Reproduction

```bash
python examples/benchmark_raster.py --size 2048 --repeats 3
```

Le script génère les données fictives, vérifie les sorties et produit un rapport
JSON. Les résultats de cette livraison sont conservés dans
[BENCHMARK_0.5.0a1.json](BENCHMARK_0.5.0a1.json).

Les méthodes d'optimisation employées sont la vectorisation des calculs,
la lecture commune des bandes entre expressions, une file de travaux bornée
et la concurrence entre calculs et entrées/sorties. Les statistiques focales
utilisent les filtres compilés de SciPy avec gestion séparée du NoData.

Le nombre de threads doit être adapté aux données et au stockage. Un petit
raster ou une opération limitée par les écritures peut ne pas bénéficier du
parallélisme. Le moteur de mosaïque reste distinct et ce benchmark ne mesure
ni la mosaïque, ni le rendu cartographique, ni les performances d'affichage.
