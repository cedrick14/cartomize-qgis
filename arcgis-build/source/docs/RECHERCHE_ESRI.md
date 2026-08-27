# Recherche technique officielle Esri

Recherche effectuée le 26 août 2026, sur la documentation officielle Esri et le paquet NuGet officiel.

## Version cible

ArcGIS Pro 3.7 est la version actuelle documentée. Le SDK 3.7 cible Windows 11, .NET 10 et Visual Studio 2026 18.4.1 ou plus récent. Le paquet de compilation officiel est `Esri.ArcGISPro.Extensions30` 3.7.0.1901.

Sources :

- [ArcGIS Pro 3.7 SDK requirements](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/topic1.html)
- [Installation and Upgrade ProGuide](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/conceptdocs/docs/ProGuide-Installation-and-Upgrade.html)
- [Esri.ArcGISPro.Extensions30 sur NuGet](https://www.nuget.org/packages/Esri.ArcGISPro.Extensions30)

## Modèle d'extension retenu

Esri décrit les add-ins avec deux couches : DAML pour déclarer les contrôles et classes .NET pour leur comportement. Les DockPanes sont des panneaux non modaux persistants. L'automatisation et les outils personnalisés de géotraitement restent appropriés en Python.

Sources :

- [ProConcepts Framework](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/conceptdocs/docs/ProConcepts-Framework.html)
- [DockPane API](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/topic10409.html)
- [ProConcepts Geoprocessing](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/conceptdocs/docs/ProConcepts-Geoprocessing.html)
- [Python Toolboxes](https://pro.arcgis.com/en/pro-app/latest/arcpy/geoprocessing_and_python/a-quick-tour-of-python-toolboxes.htm)

Conclusion : l'architecture hybride C#/WPF + `.pyt` est l'équivalent Esri correct du plugin QGIS.

## Création native des mises en page

Depuis ArcGIS Pro 3.2, `arcpy.mp` permet de créer un Layout, des MapFrames, des textes, des graphiques et des entourages de carte. ArcGIS Pro 3.7 permet aussi l'export moderne via `CreateExportFormat` et `Layout.export`.

Sources :

- [ArcGISProject.createLayout et createTextElement](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/arcgisproject-class.htm)
- [Layout.createMapFrame et createMapSurroundElement](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/layout-class.htm)
- [Migration arcpy.mapping vers arcpy.mp](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/migratingfrom10xarcpymapping.htm)
- [Tutoriel d'export arcpy.mp](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/tutorial-getting-started-with-arcpy-mp.htm)

Conclusion : les maquettes Cartomize peuvent devenir de vrais éléments ArcGIS Pro, sans image aplatie ni dépendance QGIS.

## Symbologie

`arcpy.mp.Symbology` expose les renderers de couches vectorielles et les colorizers raster. Les modifications doivent être réaffectées à la couche. Les rendus supplémentaires peuvent être traités par CIM, mais Cartomize se limite par défaut aux types documentés et réversibles.

Sources :

- [Symbology](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/symbology-class.htm)
- [GraduatedColorsRenderer](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/graduatedcolorsrenderer-class.htm)
- [RasterClassifyColorizer](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/rasterclassifycolorizer-class.htm)
- [Python CIM access](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/python-cim-access.htm)

## Fond de carte et légende

`LegendElement.removeItem()` supprime un item de légende. Il n'est donc pas nécessaire de retirer la couche de la carte ou de modifier sa visibilité. C'est la correction structurante retenue pour éviter le défaut rencontré dans la version QGIS antérieure.

Source : [LegendElement.removeItem](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/legendelement-class.htm)

## Packaging, installation et signature

Les add-ins sont distribués en fichiers `.esriAddInX`. L'installation peut utiliser l'utilitaire Esri ou un dossier approuvé. Esri avertit qu'un add-in doit provenir d'une source de confiance. Pour la diffusion professionnelle, `ArcGISSignAddIn.exe` permet la signature numérique.

Sources :

- [Manage add-ins](https://pro.arcgis.com/en/pro-app/latest/get-started/manage-add-ins.htm)
- [Digitally signed add-ins](https://pro.arcgis.com/en/pro-app/latest/sdk/api-reference/conceptdocs/docs/ProGuide-Digitally-signed-add-ins-and-configurations.html)

## Décisions finales

1. Cibler ArcGIS Pro 3.7 et .NET 10.
2. Conserver un fonctionnement local et hors ligne.
3. Livrer d'abord la boîte `.pyt` directement utilisable, puis compiler l'interface sur Windows.
4. Créer des éléments de mise en page natifs.
5. Ne jamais modifier les géométries ou pixels sources pour une recommandation visuelle.
6. Exclure les fonds de carte seulement de la légende.
7. Garder les décisions importantes visibles et modifiables par l'expert.
