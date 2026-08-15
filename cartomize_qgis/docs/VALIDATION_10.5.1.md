# Cartomize 10.5.1 validation record

## Corrected defect

Creating a layout previously removed a web basemap from the live QGIS layer
tree while trying to omit that same basemap from the printed legend. The legend
model was still synchronized with the project when `removeChildNode()` ran.

Version 10.5.1 disables automatic legend-model synchronization before any
legend-node customization. If detachment is unavailable or fails, Cartomize
skips node removal and preserves the user's project. The selected basemap stays
in the project and in the locked layer stack of every relevant map frame.

Managed-basemap replacement is also transactional: the previous background is
removed only after the requested XYZ layer is valid and registered. An existing
context layer whose tree node is missing is reattached automatically.

## Automated checks completed

- all 61 Python sources parse and compile;
- 6 focused regression tests pass without a QGIS runtime;
- the tests verify legend detachment, fail-safe behavior, explicit and automatic
  basemap inclusion, bottom-of-stack ordering and thematic-only mode;
- an AST regression check verifies that legend isolation occurs before model
  access and before `removeChildNode()`;
- the plugin metadata and runtime version both report 10.5.1.

## Required QGIS 3.40 smoke test

1. Load a thematic vector or raster layer.
2. Select OpenStreetMap, Terrain or Satellite as the Cartomize context.
3. Confirm that the context appears at the bottom of the QGIS layer panel.
4. Click **Créer la mise en page**.
5. Confirm that the context remains in the layer panel and is visible behind the
   thematic data in the main map frame.
6. Confirm that the context is omitted from the printed legend only.
7. Save, close and reopen the QGZ project, then confirm persistence.

The build environment used for this correction does not include QGIS Desktop,
so the final interactive smoke test must be run in the target QGIS 3.40 LTR
installation.
