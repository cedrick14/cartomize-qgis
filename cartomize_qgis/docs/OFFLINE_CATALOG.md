# Offline layout catalog

Cartomize 10.5.0 embeds 24 declarative QGIS layout specifications selected by
`templates_library/offline_catalog.json`. The catalog is loaded from the
installed plugin directory and does not require the Cartomize portal or any
other network service.

Each specification is validated before use, then converted into native QGIS
layout objects. Map frames, legends, titles, sources, scale bars, north arrows,
tables, shapes and other supported elements remain editable in the QGIS Layout
Designer. The files contain no executable code and cannot modify source vector
geometries or raster pixels.

Selection principles:

- exactly 24 distinct offline compositions;
- every bundled template contains a situation or detail map frame;
- the selection covers institutional, thematic, territorial, analytical and
  multi-inset publication needs;
- every composition remains editable as native QGIS layout objects.

The website keeps the complete 58-resource official collection and may publish
additional community resources. Public metadata can be refreshed manually in
the plugin and is cached locally. It is never required to run Cartomize. A
resource belongs to the offline plugin only when it is listed in the validated
manifest and included in the QGIS release ZIP.
