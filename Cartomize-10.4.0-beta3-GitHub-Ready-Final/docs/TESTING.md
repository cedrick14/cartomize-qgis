# Testing Cartomize

## Minimal manual smoke test

1. Start QGIS 3.40 or later.
2. Load `tests/data/admin_units.geojson`, `roads.geojson`, `settlements.geojson` and `landcover.asc`.
3. Open Cartomize.
4. Run project diagnostics.
5. Run Vector Intelligence on the administrative layer.
6. Run Raster Intelligence on `landcover.asc`.
7. Run Autopilot and create a native QGIS print layout.
8. Open the layout and verify map frame, legend, scale bar and title.
9. Export a PDF or PNG.
10. Run MapOps after changing one layer style.

## Security preflight

The official QGIS repository performs blocking Bandit and detect-secrets checks. The included GitHub workflow runs these tools before building the package.
