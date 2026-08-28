# Cartomize 10.5.1 for QGIS

Fast map styling, layout automation, and batch map production for QGIS.

Cartomize is a professional cartographic-assistance plugin for QGIS. It profiles a project, proposes explainable styling and layout decisions, and keeps the GIS expert in control before anything is applied.

## Expert-first workflow

1. **Inspect** — Vector Intelligence and Raster Engine profile structure, semantics, quality, NoData, band roles and likely cartographic uses.
2. **Review** — every consequential proposal remains visible: thematic field, label field, renderer, class count, palette, label placement, raster band, display bounds, RGB composition, layout template, title, margin and grid.
3. **Edit** — the expert may replace any proposed value in the Cartomize panel before application.
4. **Apply reversibly** — styles use native QGIS renderers and labeling. Previous styles can be restored; source raster pixels and vector geometries are not rewritten.
5. **Validate** — production layouts remain pending until a named cartographer completes the quality checklist and issues the validation certificate.

Low-confidence styling and layout decisions require explicit expert confirmation. Existing project symbology is preserved by default; project-wide harmonization is opt-in.

## Main capabilities

- explainable vector profiling with multilingual field-name heuristics;
- categorical, quantitative and label-field proposals editable before use;
- strict raster mask/NoData handling and bounded sampling for large datasets;
- categorical/continuous/multiband detection, band semantics and explicit spectral-index formulas;
- contextual raster-theme detection with an evidence trail and confidence score;
- manual thematic profiles for land cover, forest dynamics, change, NDVI, terrain,
  climate, risk, probability, classification and satellite compositions;
- editable raster value-to-class mappings, labels, colors, order, opacity, display
  bounds, palettes and RGB assignments, with live native-QGIS preview and QML export;
- project relationship, scale and labeling intelligence;
- 24 native, bundled QGIS layout templates available without a network connection;
- safe basemap/context synchronization: web backgrounds stay in the QGIS layer
  panel and layout map frames while remaining excluded from printed legends;
- editable layout variants, reusable recipes and batch production;
- MapOps change detection, quality checks and human approval;
- native PDF, SVG, PNG, JPEG, TIFF and QPT exports;
- QGIS Processing algorithms for repeatable workflows.

The 24 templates packaged inside the plugin are validated declarative QGIS layout sources. Every selected composition contains a situation or detail map frame. They are converted locally into editable `QgsPrintLayout` compositions; website thumbnails are never used as substitutes for QGIS templates.

The public portal can expose a broader collection (currently 58 official resources). Its catalogue is optional: Cartomize reads public metadata only after the user presses **Refresh online catalogue**, keeps the last successful response in a bounded local cache and opens authentication/download pages in the system browser. A portal, API or Internet outage never disables the 24 bundled templates or any local cartographic operation.

New users receive an eight-step native QGIS guided tour. Completion or dismissal is stored locally and the tour can be restarted from **Cartomize → Relancer la visite guidée** or **Préférences → Aide**.

## Requirements

- QGIS 3.40 to 3.99;
- the Python, PyQGIS, GDAL/OGR, PROJ, GEOS and NumPy versions distributed with QGIS;
- no additional `pip` installation.

QGIS 4 compatibility is not declared by this release.

## Data protection

Cartomize runs locally in QGIS. It does not upload geometries, raster values, attributes, credentials or project extents automatically. The official HTTPS portal is built in and opens only after an explicit user action. The plugin does not store the website password or an API token; account authentication and protected downloads remain in the browser.

Raster thematic changes are renderer mappings only. Adding, removing or merging a
visual class never reclassifies the raster and never changes a source pixel value.
NoData, masks and alpha bands remain excluded from thematic color assignment.

## Documentation and support

- Expert workflow: `docs/EXPERT_WORKFLOW.md`
- Release changes: `CHANGELOG.md`
- Current validation and QGIS smoke-test checklist: `docs/VALIDATION_10.5.1.md`
- Baseline 10.5.0 validation record: `docs/VALIDATION_10.5.0.md`
- Offline catalog: `docs/OFFLINE_CATALOG.md`
- Administration and support: <https://cartomizeplugin.com>
- Technical issues: <https://github.com/cedrick14/cartomize-qgis/issues>

## License

The plugin is released under GNU GPL version 3. Bundled templates are covered by `templates_library/LICENSE.txt`.
