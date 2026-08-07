# Cartomize for QGIS

Cartomize is an open-source QGIS plugin for intelligent cartographic automation, raster and vector analysis, native print layouts, reproducible map production and cartographic quality control.

> Status: experimental beta. Supported QGIS versions: 3.40 to 3.99.

## Overview

Cartomize helps GIS professionals and cartographers transform QGIS projects into publication-ready maps. It works directly with native QGIS layers and print layouts, while keeping the cartographer in control of final validation.

## Main features

- Raster Intelligence for metadata, NoData, masks, alpha, class frequencies, categorical/continuous detection, anomalies, class editing and native QGIS raster renderers
- Vector Intelligence for geometry quality, semantic field profiling, likely label fields and thematic variables
- Geo Intelligence for project-wide layer relationships and visual hierarchy
- Autopilot for map-intent detection, template selection and ranked layout proposals
- Native QGIS print layouts with legends, scale bars, grids, inset maps and readability optimization
- Scale and Label Intelligence for scale-aware visibility and label-density diagnostics
- Batch Production using reusable Cartomize recipes
- MapOps for project-change detection and targeted regeneration
- Human Validation with explicit cartographer approval and traceable validation records

## Privacy and data integrity

Cartomize runs locally inside QGIS. It does not automatically transmit project data, and its analysis and styling workflows do not modify original raster pixel values or vector features.

## Requirements

- QGIS 3.40 to 3.99
- Python, PyQGIS, GDAL and NumPy components distributed with QGIS
- no additional third-party Python installation is required

## Installation from ZIP

1. Open QGIS.
2. Go to **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the Cartomize plugin ZIP.
4. Restart QGIS after replacing an earlier development version.

## Quick test

Small synthetic test datasets are available in `tests/data` so the plugin can be evaluated without downloading external data.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Testing](docs/TESTING.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [QGIS submission notes](docs/QGIS_SUBMISSION.md)

## Reporting issues

Please report reproducible problems through GitHub Issues:

https://github.com/cedrick14/cartomize-qgis/issues

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Please see [SECURITY.md](SECURITY.md) for responsible disclosure guidance.

## License

Cartomize plugin source code is licensed under GNU GPL v3. Bundled map template definitions are licensed separately under CC BY 4.0 where indicated in the package.
