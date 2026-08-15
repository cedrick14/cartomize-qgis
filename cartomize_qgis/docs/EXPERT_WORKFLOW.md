# Cartomize expert workflow

## Decision ownership

Cartomize is an assistant, not an autonomous cartographer. A recommendation contains evidence and a confidence score. It becomes a project decision only after the user applies it. Low-confidence decisions cannot be applied until the expert explicitly confirms them.

## Vector layers

Open **Project**, select a vector layer, then review the expert editor below the recommendation. The expert can change:

- rendering mode: single symbol, categorized or graduated quantiles;
- thematic field and maximum number of classes;
- qualitative, sequential or diverging palette;
- label field, enabled state, font size and placement;
- layer opacity.

Cartomize saves the accepted renderer, thematic field, class count, palette, opacity and label settings as layer custom properties. Later Geo Intelligence or Autopilot analyses reuse them instead of silently selecting a different field. Choosing **No labels** is also preserved as an explicit decision. If a stored field disappears after a schema change, Cartomize discards that invalid reference and proposes a new reviewable plan.

The categorized renderer refuses to hide excess values silently. If the field exceeds the selected class limit, Cartomize asks the expert to increase the limit or choose a more suitable representation.

## Raster layers

Open **Raster Engine** to review:

- declared NoData, mask and alpha information;
- valid and invalid pixel estimates;
- sampled versus exact counts;
- detected classes, anomalous values and missing-code hypotheses;
- band descriptions, color interpretations and spectral roles;
- spectral-index proposals with exact formula and band mapping.

The **Classes** table edits source-value mappings, names, colors, opacity, order,
visibility and legend membership. Several source codes can be merged into one visual
class. One source code cannot belong to two visible mappings at the same time. Adding,
deleting or editing a row changes only the QGIS renderer: Cartomize does not rewrite or
reclassify source pixels.

The **Symbology** tab first proposes a thematic profile with its confidence and
supporting evidence. The expert may keep automatic detection or select a manual profile:
land cover, forest dynamics, deforestation, forest degradation, land-cover change,
NDVI, elevation, slope, temperature, precipitation, risk, probability, generic
classification, RGB or false-color composition. Selecting a profile refreshes the
native QGIS preview and legend immediately. **Cancel preview** restores the preceding
style, **Undo** restores the previous committed style and **Save QML** exports the
accepted QGIS style.

For a continuous raster, a categorical profile is not applied unless reliable discrete
codes were detected. Continuous rasters initially use valid-sample quantiles and robust
2–98% bounds when available; the expert can switch to equal intervals or replace the
limits. NoData, masks and alpha pixels remain outside thematic class assignment.

Deep exact counts are limited to local categorical rasters of at most 25 million pixels and at most 4,096 observed values. Other datasets use a bounded sample and are marked accordingly.

## Layout proposals

After **Analyze project**, select a proposal and edit its template, title, subtitle, extent margin and coordinate grid. Existing layer styles are preserved unless **Harmonize project symbology** is explicitly enabled.

Every generated layout is a native `QgsPrintLayout`. Titles, maps, legends, scale bars, north arrows, sources, tables and frames remain editable in the QGIS Layout Designer. The 24 bundled layouts are plugin assets; Community resources are separate.

## Validation and reproducibility

Use the Quality tab before export. Production approval requires the named reviewer, organization, checklist and notes. Recipes record chosen layout parameters and can be replayed against updated layers. MapOps identifies dependent layouts after a source change, but the human approval must be renewed.

## Operational limits

- Always verify CRS, units, scale, data lineage and legal attribution.
- A semantic hint based on a field name is evidence, not proof.
- A spectral index is proposed only when required band roles are identified from descriptions, color interpretation, metadata or wavelength.
- Test this release with the target QGIS build and representative organizational datasets before managed deployment.
