# Changelog

## 10.5.1 — Basemap and legend isolation fix

- Detached each layout legend from the live QGIS project layer tree before
  removing web basemaps from legend contents.
- Added a fail-safe that skips legend-node removal when QGIS cannot isolate the
  legend model, preserving every user layer.
- Kept the selected context layer in the project and in every locked layout map
  stack while omitting it only from the printed legend.
- Made managed-basemap replacement transactional and repaired registered
  context layers whose layer-tree node was removed by an earlier build.
- Added regression tests for legend isolation and explicit basemap ordering.

## 10.5.0 — Expert Review, Offline Catalog and Guided Tour

- Restored the complete QGIS compatibility API used by layout rendering, preview export and project persistence, and added a release-time contract check to prevent incomplete packages.
- Curated 24 native QGIS layout specifications available offline.
- Added an eight-step first-use guided tour connected to the actual Cartomize controls.
- Added persistent completed/skipped state so the tour does not reappear at every launch.
- Added restart commands in the Cartomize menu and Preferences dialog.
- Added direct access to the native QGIS data source manager from the Project workflow.
- Kept every important styling and layout recommendation editable before application.
- Added editable vector recommendations for thematic field, label field, renderer, classes, palette, label size, placement and opacity.
- Persisted expert label decisions so Geo Intelligence and Autopilot do not silently replace them.
- Persisted the accepted vector renderer, thematic field, class count, palette and opacity while the layer schema remains compatible.
- Added editable raster rendering controls for mode, band, classes, palette, bounds and RGB band assignments.
- Added contextual raster-theme detection with confidence, evidence and explicit
  expert override across land-cover, forest, change, vegetation, terrain, climate,
  risk, probability and satellite use cases.
- Added live reversible raster previews, multi-value class merging, editable opacity
  and class order, duplicate-code validation and native QML style export.
- Ensured manual thematic choices alter only renderer mappings while preserving source
  pixels, masks, alpha and NoData semantics.
- Added valid-sample quantile classification with editable equal-interval fallback and robust 2–98% display bounds.
- Added strict mask and NoData accounting shared by rapid and deep raster analysis.
- Reworked raster frequency sampling to preserve the most frequent values and report bounded-profile limitations.
- Prevented continuous/high-cardinality rasters from triggering uncontrolled exact counts.
- Added explicit band semantics and correctly named NDVI, NDWI (McFeeters), NDMI, NDBI, SAVI and EVI proposals.
- Added wavelength-based spectral-role inference when source metadata provides a central wavelength.
- Added editable Autopilot layout variants and made project-wide style harmonization opt-in.
- Prevented categorical rendering from silently omitting values beyond the expert-defined class limit.
- Expanded multilingual vector field and layer-role heuristics.
- Updated QGIS scoped enum usage and Processing feedback handling.
- Updated production metadata, support address and documentation.

## 10.4.0

- Stable public baseline with 24 bundled native QGIS templates.
