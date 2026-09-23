import json
import threading
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm


def scenes(write_raster):
    result = []
    for ident, x, offset in [('A', 300000, 0), ('B', 300020, 20)]:
        bands = {}
        for index, name in enumerate(['blue', 'green', 'red', 'nir']):
            values = np.arange(4, dtype='float32').reshape(2, 2) + offset + index * 100
            bands[name] = write_raster(f'{ident}_{name}.tif', values, transform=from_origin(x, 9500000, 10, 10))
        result.append(cm.Scene(ident, bands, sensor='custom', acquired='2026-09-23'))
    return result


def test_mosaic_clip_split_and_explicit_channels(write_raster, tmp_path):
    source = scenes(write_raster)
    aoi = cm.GeoDataFrame(geometry=[box(300010, 9499980, 300030, 9500000).difference(box(300020, 9499980, 300030, 9499990))], crs=32733)
    result = cm.process_imagery(source, tmp_path/'result', aoi=aoi, separate_bands=True,
        composition=('nir', 'red', 'green'), mask_clouds=False)
    product = result.products[0]
    with rasterio.open(product['multiband']) as src:
        assert src.shape == (2, 2) and src.count == 4
        assert src.descriptions == ('blue', 'green', 'red', 'nir')
        assert src.read(1)[0].tolist() == [1, 20]
        assert src.read(1, masked=True).mask.tolist() == [[False, False], [False, True]]
        for index, record in product['bands'].items():
            with rasterio.open(record['path']) as band:
                assert band.count == 1 and band.transform == src.transform and band.crs == src.crs
                np.testing.assert_equal(band.read(1), src.read(int(index)))
                np.testing.assert_equal(band.read_masks(1), src.read_masks(int(index)))
    with rasterio.open(product['composition']) as display:
        assert display.tags()['source_bands'] == '(4, 3, 2)'
        assert display.count == 4 and display.dtypes == ('uint8',)*4
        assert display.read(4).tolist() == [[255, 255], [255, 0]]
    for path in (tmp_path/'result').rglob('*.json'):
        assert '.cartomize-' not in path.read_text()
    assert json.loads(result.manifest.read_text())['rgb_bands'] == ['nir', 'red', 'green']


@pytest.mark.parametrize('mosaic', [True, False])
@pytest.mark.parametrize('multiband,separate,colour', [(True,False,False), (True,True,False),
    (True,False,True), (True,True,True), (False,True,False), (False,False,True), (False,True,True)])
def test_each_output_selection_is_honoured(write_raster, tmp_path, mosaic, multiband, separate, colour):
    result = cm.process_imagery(scenes(write_raster), tmp_path/'results', mosaic=mosaic,
        multiband=multiband, separate_bands=separate, composition='natural' if colour else None, mask_clouds=False)
    assert len(result.products) == (1 if mosaic else 2)
    for product in result.products:
        assert bool(product['multiband']) == multiband
        assert bool(product['bands']) == separate
        assert bool(product['composition']) == colour
        folder = Path(product['report']).parent
        assert (folder/'multibande.tif').exists() == multiband
        assert (folder/'composition_coloree.tif').exists() == colour
        if not mosaic and multiband:
            with rasterio.open(product['multiband']) as src:
                assert src.width == 2  # No silent mosaicking of the adjacent scene.


def test_validation_and_failure_leave_no_partial_production(write_raster, tmp_path):
    source = scenes(write_raster)
    with pytest.raises(ValueError, match='Choisir'):
        cm.process_imagery(source, tmp_path/'none', multiband=False)
    with pytest.raises(ValueError, match='absente'):
        cm.process_imagery(source, tmp_path/'wrong_band', composition=('swir2', 'nir', 'red'), mask_clouds=False)
    # Failure during display occurs after actual preparation, but publishes nothing.
    with pytest.raises(ValueError, match='gamma'):
        cm.process_imagery(source, tmp_path/'failed', composition='natural', gamma=0, mask_clouds=False)
    assert not (tmp_path/'failed').exists()
    partial = cm.Scene('incomplete', {'red':source[1].bands['red']}, sensor='custom', acquired='2026-09-23')
    with pytest.raises(ValueError, match='mêmes bandes'):
        cm.process_imagery([source[0],partial], tmp_path/'missing', mask_clouds=False)
    existing = tmp_path/'existing'
    existing.mkdir()
    sentinel = existing/'preserve.txt'
    sentinel.write_text('source')
    with pytest.raises(FileExistsError):
        cm.process_imagery(source, existing, mask_clouds=False)
    assert sentinel.read_text() == 'source'


def test_cancellation_discards_all_products(write_raster, tmp_path):
    event = threading.Event()
    def progress(done, total):
        if done >= total // 2:
            event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.process_imagery(scenes(write_raster), tmp_path/'cancelled', separate_bands=True,
            mask_clouds=False, progress=progress, cancel=event)
    assert not (tmp_path/'cancelled').exists()


def test_standalone_split_retains_values_masks_and_calibration(write_raster, tmp_path):
    source = write_raster('source.tif', np.array([[[0,2],[3,4]], [[5,6],[7,8]]],dtype='uint16'), nodata=None)
    with rasterio.open(source, 'r+') as src:
        src.descriptions = ('same', 'same')
        src.scales = (.1, .2)
        src.offsets = (-1., -2.)
        src.write_mask(np.array([[255,0],[255,255]],dtype='uint8'))
    outputs = cm.split_bands(source, tmp_path/'bands')
    assert outputs[1] != outputs[2]
    with rasterio.open(source) as original:
        for index, path in outputs.items():
            with rasterio.open(path) as src:
                np.testing.assert_equal(src.read(1), original.read(index))
                np.testing.assert_equal(src.read_masks(1), original.read_masks(index))
                assert src.scales == (original.scales[index-1],)
                assert src.offsets == (original.offsets[index-1],)
                assert src.dtypes == ('uint16',)
