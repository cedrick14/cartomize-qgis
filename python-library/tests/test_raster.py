import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, Affine
from shapely.geometry import box
import cartomize as cm


def test_ndvi_masks_zero_denominator_and_valid_zero(write_raster, tmp_path):
    source = write_raster("bands.tif", np.array([[[1,2,0,-9999]], [[3,2,0,3]]], dtype="float32"))
    out = cm.raster.ndvi(source, tmp_path/"ndvi.tif", red=1, nir=2)
    with rasterio.open(out) as src:
        values = src.read(1, masked=True)
        assert values[0,0] == .5
        assert values[0,1] == 0 and not values.mask[0,1]
        assert values.mask[0,2:].all()
    with pytest.raises(ValueError):
        cm.raster.ndvi(source, source, red=1, nir=2, overwrite=True)


def test_ndvi_scale_and_offset(write_raster, tmp_path):
    source = write_raster("bands.tif", np.array([[[10]], [[20]]], dtype="int16"))
    out = cm.raster.ndvi(source, tmp_path/"index.tif", red=1, nir=2, scale=.1, offset=-.5)
    with rasterio.open(out) as src:
        assert src.read(1)[0,0] == pytest.approx(.5)


def test_reclassify_keeps_masks_and_zero(write_raster, tmp_path):
    source = write_raster("classes.tif", np.array([[0,1,2,-9999]], dtype="int16"))
    out = cm.raster.reclassify(source, tmp_path/"binary.tif", {0:0,1:1})
    with rasterio.open(out) as src:
        v = src.read(1, masked=True)
        assert v[0,:2].tolist() == [0,1]
        assert v.mask[0,2:].all()
    with pytest.raises(FileExistsError):
        cm.raster.reclassify(source, out, {1:2})


def test_inspect_respects_external_mask_and_preserves_zero(write_raster):
    source = write_raster("mask.tif", np.array([[0,1],[255,2]], dtype="uint8"), nodata=None, mask=[[1,1],[0,1]])
    report = cm.raster.inspect(source)
    assert report["sample"]["valid_pixels"] == 3
    assert report["sample"]["nodata_pixels"] == 1
    assert {p["value"] for p in report["sample"]["profiles"]} == {0,1,2}


def test_zonal_stats_duplicate_indices_empty_and_nonoverlap(write_raster):
    source = write_raster("values.tif", np.array([[0,2],[4,-9999]], dtype="int16"))
    zones = cm.GeoDataFrame({"id":[1,2,3]}, geometry=[box(300000,9499980,300020,9500000), box(1,1,2,2), None], index=[0,0,1], crs=32733)
    stats = cm.raster.zonal_stats(source,zones)
    assert stats["count"].tolist() == [3,0,0]
    assert stats["mean"].iloc[0] == 2
    assert np.isnan(stats["mean"].iloc[1])
    assert list(stats.index) == [0,0,1]


def test_pixel_areas_rotated_grid(write_raster):
    transform = Affine(10,2,300000,3,-10,9500000)
    source = write_raster("classes.tif", np.array([[0,1],[1,-9999]], dtype="int16"), transform=transform)
    areas = cm.raster.class_areas(source, unit="m2").set_index("class")
    assert areas.loc[0,"area_m2"] == 106
    assert areas.loc[1,"pixels"] == 2
    assert areas.loc[1,"area_m2"] == 212


def test_change_matrix_both_masks_and_grid_guard(write_raster):
    a = write_raster("a.tif", np.array([[1,1],[2,-9999]], dtype="int16"))
    b = write_raster("b.tif", np.array([[1,2],[-9999,1]], dtype="int16"))
    result = cm.raster.change_matrix(a,b)
    assert result.to_dict("records") == [{"from":1.,"to":1.,"pixels":1},{"from":1.,"to":2.,"pixels":1}]
    c = write_raster("c.tif", np.array([[1,1],[2,1]], dtype="int16"), transform=from_origin(300005,9500000,10,10))
    with pytest.raises(ValueError,match="grids differ"):
        cm.raster.change_matrix(a,c)


def test_clip_aligns_zone_crs_and_reproject(write_raster,tmp_path):
    source = write_raster("grid.tif", np.array([[0,2],[4,-9999]], dtype="int16"))
    zones = cm.GeoDataFrame(geometry=[box(300000,9499980,300010,9500000)],crs=32733)
    out = cm.raster.clip(source,zones,tmp_path/"clip.tif")
    with rasterio.open(out) as src:
        assert src.shape == (2,1)
        assert src.read(1).tolist() == [[0],[4]]
    projected = cm.raster.reproject(source,tmp_path/"projected.tif",4326)
    with rasterio.open(projected) as src:
        assert src.crs.to_epsg() == 4326
        assert set(src.read(1,masked=True).compressed()) <= {0,2,4}


def test_all_nodata_and_geographic_area_rejected(write_raster):
    source = write_raster("empty.tif", np.full((2,2),-9999,dtype="int16"))
    assert cm.raster.inspect(source)["sample"]["valid_pixels"] == 0
    assert cm.raster.class_areas(source).empty
    geographic = write_raster("geo.tif", np.ones((2,2),dtype="int16"),crs=4326)
    with pytest.raises(ValueError,match="projected"):
        cm.raster.class_areas(geographic)
