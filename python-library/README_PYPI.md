# Cartomize

**Cartographic assistant for Python — Assistant cartographique pour Python**

Cartomize combines satellite image preparation, raster and vector processing,
and cartographic layouts in a Python library with an optional desktop interface.
It is developed by **ONDON NKOUA Cédrick Belmich**, founder of Cartomize.

The standalone library and its desktop interface work **without QGIS or ArcGIS Pro**.
Optional native project bridges require the corresponding installed GIS software.

## Installation

Python 3.11 or newer is required. Version **0.8.1a1 is an alpha release**.
Linux and Windows have been tested with Python 3.11 and 3.12.

```bash
python -m pip install "cartomize==0.8.1a1"
```

For the desktop interface and optional Dask execution:

```bash
python -m pip install "cartomize[gui,distributed]==0.8.1a1"
python -m cartomize gui
```

Or open the interface from Python:

```python
import cartomize as cm
cm.launch()
```

Importing the library does not open a window automatically.

## Satellite image preparation

Select spectral bands and a polygonal area of interest, then choose mosaicking,
multiband assembly, clipping, RGB composition and separate band exports.
Landsat Collection 2 Level 2 and Sentinel-2 Level 2A products are recognized
from their original filenames and metadata. Other inputs use explicit band
and scene mappings.

```python
import cartomize as cm

result = cm.process_imagery(
    ["scene_A", "scene_B"],
    "outputs/preparation",  # a new directory
    aoi="study_area.shp",
    mosaic=True,
    multiband=True,
    separate_bands=True,
    composition=("nir", "red", "green"),
)
print(result.manifest)
```

Calibration and quality masking precede resampling. Scientific multiband values
remain separate from stretched display values. Turning off mosaicking processes
each scene independently. For an existing multiband file:

```python
band_files = cm.split_bands("multiband.tif", "outputs/separate_bands")
```

## Capabilities

- Multiscene preparation, NoData masks, RGB composites and spectral indices.
- Raster algebra, focal statistics, multiraster reductions and terrain derivatives.
- Vector overlay, spatial joins, buffers, clipping and geometry repair.
- Supervised and unsupervised classification with explicit training inputs where required.
- Cartographic layouts, legends, scale bars, labels, 24 templates and PDF/PNG/SVG exports.
- Optional desktop workflows, saved sessions and portable projects.
- Dask execution for supported raster operators; optional CUDA for algebra, indices and reductions.

## Utilisation en français

Cartomize permet de préparer les images satellitaires, traiter les couches et
produire les cartes dans Python ou dans une fenêtre dédiée. Dans
**Prétraitement multispectral**, charger les bandes, vérifier les scènes, importer
la délimitation, cocher les opérations et choisir les bandes des canaux rouge,
vert et bleu. Les GeoTIFF scientifiques, les compositions colorées et les bandes
extraites sont enregistrés séparément.

L’interface conserve l’icône Cartomize en couleur et utilise des intitulés
techniques. Les indices et la mise en page restent accessibles à partir des
résultats de préparation.

## Documentation and support

- [Website](https://cartomizeplugin.com/)
- [Source code](https://github.com/cedrick14/cartomize-qgis/tree/feat/cartomize-python-library/python-library)
- [Desktop guide](https://github.com/cedrick14/cartomize-qgis/blob/feat/cartomize-python-library/python-library/docs/DESKTOP.md)
- [Image preparation guide](https://github.com/cedrick14/cartomize-qgis/blob/feat/cartomize-python-library/python-library/docs/IMAGERY_SELECTION.md)
- [Execution engines](https://github.com/cedrick14/cartomize-qgis/blob/feat/cartomize-python-library/python-library/docs/EXECUTION.md)
- [Issue tracker](https://github.com/cedrick14/cartomize-qgis/issues)

## Validation and scope

The 0.8.1 code passed 315 tests in each Linux/Windows and Python 3.11/3.12
configuration, including 38 Qt cases. QGIS native integration was tested
separately in a real QGIS runtime. CUDA hardware execution and ArcGIS Pro
integration still require validation on suitable licensed/equipped machines.
Tests use synthetic data; no universal performance gain is claimed.

The library uses GeoPandas, Rasterio, NumPy, SciPy, Matplotlib and scikit-learn.
PySide6, Dask and CuPy are optional dependencies. This alpha does not reproduce
every native GIS rendering effect and is not endorsed by QGIS, Esri or GeoPandas.

## License

Source code: **GNU GPL v3 only**. The original layout templates are **CC BY 4.0**,
attributed to Cartomize / ONDON NKOUA Cédrick Belmich. License notices are included
in the distribution.
