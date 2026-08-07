# Security Policy

## Reporting a vulnerability

Please do not publish exploitable security details in a public issue before a fix is available. Contact the maintainer using the email configured in `cartomize_qgis/metadata.txt` and provide a minimal reproduction, affected version and expected impact.

## Security design

Cartomize runs locally inside QGIS. It does not automatically upload project geometries, raster values or attributes. Optional Community access is user-initiated.

The project aims to avoid unsafe dynamic execution, shell execution, embedded credentials and bundled binary executables.

## QGIS repository scanning

Official QGIS plugin uploads are scanned with Bandit and detect-secrets as blocking security checks, with Flake8 and file analysis used for additional quality reporting. The GitHub workflow in this repository runs the same tool families before packaging.
