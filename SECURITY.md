# Security policy

## Supported release

Cartomize 10.5.x is the currently supported stable QGIS release. Security fixes
are published as a new signed-off ZIP through the official QGIS plugin page.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to
`support@cartomizeplugin.com`. Do not include passwords, API keys, private GIS
datasets or personal information in the initial report. Include the Cartomize
version, QGIS version, operating system and minimal reproduction steps.

## Data and network boundaries

Cartomize performs cartographic analysis locally and does not upload project
layers, geometries, raster values, attributes or project extents. The optional
community catalogue fetches bounded public metadata over HTTPS only after an
explicit user action. It stores no website password or authentication token and
falls back to the bundled offline catalogue whenever the portal is unavailable.
