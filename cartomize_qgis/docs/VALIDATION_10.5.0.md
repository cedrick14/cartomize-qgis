# Cartomize 10.5.0 validation record

## Scope

This package is the corrected QGIS plugin distribution. It contains **24 native bundled layout specifications**. The **58 resources shown on Cartomize Community are separate website records** and are not claimed as files embedded in this plugin.

## Automated checks completed

- all 54 Python sources parse and compile with Python 3.12;
- all 24 layout JSON files parse, use supported page formats and contain at least one map frame;
- all 24 layout identifiers are unique and declare application version 10.5.0;
- 23 pure unit tests cover mask/NoData exclusion, valid-population percentages, bounded value profiles, sampled quantiles, band semantics, spectral-index safety, secure catalogue fallback, guided-tour state and template-catalog integrity;
- no legacy enum access from the reported QGIS 3.40 scanner list remains;
- the exact release ZIP reports zero Bandit findings, zero detect-secrets findings and zero findings from the active QGIS Flake8 rule set;
- no embedded access key, private key or hard-coded password pattern was found;
- no non-local clear-text HTTP endpoint was found in Python sources.

## Expert-control acceptance criteria

- proposed vector thematic and label fields are editable before application;
- renderer, class count, palette, label state, font size, placement and opacity are editable;
- accepted vector settings are reused only while referenced fields still exist;
- proposed raster mode, band, palette, class count, method, bounds and RGB channels are editable;
- raster classes expose editable labels, colors, visibility and legend membership;
- continuous raster proposals use valid-sample quantiles and robust 2–98% bounds when available;
- low-confidence styling cannot be applied without explicit confirmation;
- layout template, title, subtitle, extent margin and grid are editable before production;
- existing project symbology is preserved unless harmonization is explicitly selected;
- source raster cells and vector geometry are never rewritten by a styling operation.

## Required QGIS smoke test before organizational rollout

The build environment used for this package does not include a QGIS desktop runtime. Before managed deployment, open the plugin in the target QGIS 3.40 LTR installation and verify:

1. plugin activation and Processing provider registration;
2. one point, line and polygon layer through vector analysis, edit, apply and undo;
3. one categorical raster with declared NoData and one continuous float raster through rapid/deep analysis, edit, apply and undo;
4. one multispectral raster whose band descriptions or wavelength metadata identify RGB/NIR/SWIR roles;
5. creation and QPT/PDF export of at least one A4 and one A3 native layout;
6. recipe replay, batch cancellation, MapOps change detection and human validation certificate;
7. project save, close and reopen to confirm persistence of accepted expert settings.

No software release can guarantee suitability for every CRS, provider, sensor or institutional schema. The human cartographer remains responsible for semantic validation, scale, source attribution and final publication approval.
