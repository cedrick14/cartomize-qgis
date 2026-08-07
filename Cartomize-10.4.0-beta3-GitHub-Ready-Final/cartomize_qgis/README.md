# Cartomize

Cartomize is an experimental QGIS plugin for intelligent cartographic automation and native print-layout production.

## What it does

Cartomize analyses a QGIS project before building a map. It combines raster intelligence, vector intelligence, project-wide layer relationships, scale-aware labeling, automated symbology, native QGIS print layouts, reusable map recipes, batch production, MapOps change detection, and human cartographic validation.

The plugin works with native QGIS layers, renderers, labeling and `QgsPrintLayout` objects. Styling and analysis are non-destructive: Cartomize does not rewrite source raster pixels or vector geometries unless the user explicitly runs a separate data-processing operation.

## Main features

- Raster Intelligence for categorical, continuous, multiband and classified rasters
- Vector Intelligence for geometry, fields, thematic variables and probable cartographic roles
- Geo Intelligence for project-wide layer hierarchy and relationships
- Autopilot for template selection and automated layout creation
- Scale and Label Intelligence
- 24 bundled Cartomize layout templates
- high-resolution QGIS layout preview
- native PDF, SVG, PNG, JPEG, TIFF and QPT exports
- reusable map recipes and batch map production
- MapOps change detection and targeted regeneration
- quality checks and explicit human cartographer approval
- Processing algorithms for automation workflows

## Requirements

- QGIS 3.40 to 3.99
- Python, PyQGIS, GDAL/OGR, PROJ, GEOS and NumPy as distributed with QGIS
- no additional pip installation is required

QGIS 4 support is not declared by this release.

## Privacy

Cartomize runs locally inside QGIS. Project geometries, raster values and attributes are not uploaded automatically. Community integration is optional and must be explicitly configured by the user.

## License

Plugin code is released under GNU GPL version 3. The bundled Cartomize templates are separately documented in `templates_library/LICENSE.txt`.

## Support

Use the public issue tracker declared in `metadata.txt` after the repository has been configured.
