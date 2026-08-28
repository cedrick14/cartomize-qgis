# Cartomize for QGIS

Fast map styling, layout automation, and batch map production for QGIS.

Cartomize is an open-source QGIS plugin for intelligent cartographic automation,
raster and vector analysis, native print layouts, reproducible map production
and cartographic quality control.

Current release: **10.5.1**  
Supported QGIS versions: **3.40 to 3.99**

## What is new in 10.5.1

- preserves OpenStreetMap, Terrain and Satellite context layers when a layout is created;
- keeps the selected basemap behind thematic data in native QGIS map frames;
- removes web basemaps from the printed legend without modifying the project layer tree;
- repairs context layers affected by the former legend synchronization defect;
- replaces managed basemaps transactionally and includes focused regression tests.

## Main capabilities

- fast editable vector and raster styling;
- explainable project, scale, label and cartographic intelligence;
- native QGIS layout automation with legends, scale bars and situation maps;
- reusable recipes and batch map production;
- MapOps change detection and targeted regeneration;
- PDF, SVG, PNG, JPEG, TIFF and QPT exports;
- local processing that preserves source raster pixels and vector geometries.

## Repository layout

- `cartomize_qgis/` — installable QGIS plugin source;
- `cartomize_qgis/tests/` — regression tests runnable without QGIS Desktop;
- `tools/validate_release.py` — source and metadata validation;
- `tools/build_plugin_zip.py` — reproducible QGIS plugin ZIP builder;
- `.github/workflows/validate.yml` — automated validation and release-package build.

## Install from ZIP

1. Download or build `Cartomize-10.5.1.zip`.
2. Open **QGIS → Plugins → Manage and Install Plugins**.
3. Choose **Install from ZIP** and select the archive without extracting it.
4. Restart QGIS after replacing an earlier development version.

## Build and validate

```bash
python tools/validate_release.py
python -m unittest discover -s cartomize_qgis/tests -v
python tools/build_plugin_zip.py --output dist/Cartomize-10.5.1.zip
```

## Privacy and data integrity

Cartomize runs locally in QGIS. It does not automatically upload project data,
and styling operations do not rewrite raster pixels or vector features.

## Support

- Website: <https://cartomizeplugin.com>
- Issues: <https://github.com/cedrick14/cartomize-qgis/issues>
- Author: ONDON NKOUA Cédrick Belmich

## License

Cartomize is licensed under GNU GPL v3. Bundled template definitions are covered
by their accompanying license file.
