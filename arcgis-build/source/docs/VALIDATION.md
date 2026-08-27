# Validation 10.5.1

## Contrôles exécutés dans l'environnement de construction

- 21 sources Python, y compris `Cartomize.pyt`, analysées syntaxiquement ;
- `Config.daml` et le panneau XAML analysés comme XML ;
- exactement 24 maquettes chargées depuis le manifeste ;
- chaque maquette possède au moins un cadre cartographique ;
- chaque élément est ramené dans les limites de sa page A4/A3 ;
- création simulée d'une mise en page complète ;
- non-régression fond de carte : le nettoyage de la légende ne modifie jamais la liste des couches de la carte ;
- sérialisation et relecture des recettes ;
- déterminisme des empreintes MapOps.
- identité SHA-256 des trois modules purs du Raster Engine avec l’archive QGIS
  10.5.1 fournie ;
- résolution d’une couche raster ArcGIS en nom ou chemin avant appel à
  `arcpy.Raster` ;
- conservation du contrat de diagnostic Raster Engine QGIS et de la garantie
  de non-modification de la source.
- identité SHA-256 de la bibliothèque thématique raster, de la pile de couches
  et des 24 maquettes avec le ZIP QGIS 10.5.1 ;
- lecture des recettes et manifestes QGIS v1 ;
- conservation d’un fond de carte visible au bas de la pile principale.

Résultat : 16 tests réussis.

## Limite explicite

L'environnement de validation n'inclut pas une session Windows ArcGIS Pro.
Le paquet `.esriAddInX` est reconstruit avec les nouveaux modules, mais les
interactions réelles avec `arcpy`, les styles installés et l’export doivent
être confirmés dans ArcGIS Pro 3.7.

## Test interactif obligatoire dans ArcGIS Pro 3.7

1. Ouvrir un APRX avec une couche thématique et un fond Esri.
2. Ajouter `Cartomize.pyt` au projet.
3. Lancer **Auditer le projet** et vérifier le rapport JSON.
4. Lancer **Analyser une couche vectorielle** sur une couche de polygones.
5. Lancer **Analyser un raster** sur un raster continu puis un raster classifié.
6. Lancer **Créer une mise en page** sur au moins une maquette A4 et une A3.
7. Vérifier que le fond reste visible dans la carte et le MapFrame, mais absent de la légende.
8. Vérifier le titre, les encarts, l'échelle, la flèche nord et les limites de page.
9. Exporter en PDF 600 DPI et PNG 300 DPI.
10. Enregistrer, fermer et rouvrir l'APRX.
11. Compiler l'add-in, l'installer, relancer ArcGIS Pro et tester toutes les commandes du ruban.
12. Signer le binaire avant toute diffusion publique.

## Critères de sortie de préversion

- zéro exception non gérée sur les neuf outils ;
- vingt-quatre maquettes testées au moins une fois ;
- fonds de carte préservés dans tous les projets d'essai ;
- export PDF et image conforme ;
- add-in installé, désinstallé et mis à jour proprement ;
- signature numérique vérifiée par le gestionnaire d'add-ins.
