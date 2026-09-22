import math
import numpy as np
import pytest
from shapely.geometry import Point, box, Polygon
import cartomize as cm


def polygons(crs=32733):
    return cm.GeoDataFrame({"nom": ["A", "B"], "classe": [1, 2]},
                           geometry=[box(300000, 9500000, 300100, 9500100), box(300100, 9500000, 300200, 9500100)], crs=crs)


def test_geo_interface_and_area():
    data = polygons()
    assert isinstance(cm.read_file, object)
    assert cm.area(data).tolist() == [1, 1]
    assert cm.area(cm.dissolve(data)).iloc[0] == 2
    assert cm.length(data).tolist() == [400, 400]


def test_buffer_metres_preserves_input_and_crs():
    points = cm.GeoDataFrame({"name":["A"]}, geometry=[Point(15, -4)], crs=4326)
    original = points.copy()
    result = cm.buffer(points, 100, metric_crs=32733)
    assert result.crs == points.crs
    assert result.name.tolist() == ["A"]
    assert cm.area(result, unit="m2", metric_crs=32733).iloc[0] == pytest.approx(math.pi*100**2, rel=.003)
    assert points.equals(original)


def test_projected_feet_converted():
    data = cm.GeoDataFrame(geometry=[box(1000000, 200000, 1000100, 200100)], crs=2263)
    factor = data.crs.axis_info[0].unit_conversion_factor
    assert cm.area(data, "m2").iloc[0] == pytest.approx(10000*factor**2)


@pytest.mark.parametrize("fn", [cm.buffer, cm.area, cm.length])
def test_no_degrees_measurements(fn):
    data = cm.GeoDataFrame(geometry=[Point(15, -4)], crs=4326)
    with pytest.raises(ValueError, match="projected"):
        fn(data, 100) if fn is cm.buffer else fn(data)


def test_spatial_join_aligns_crs():
    zones = polygons()
    points = cm.GeoDataFrame({"id":[1]}, geometry=[Point(300050,9500050)], crs=32733).to_crs(4326)
    joined = cm.sjoin(points, zones, predicate="within")
    assert joined.nom.tolist() == ["A"]
    assert joined.crs == points.crs


def test_clip_overlay_align_crs():
    data = polygons()
    mask = cm.GeoDataFrame(geometry=[box(300050,9500000,300150,9500100)], crs=32733)
    clipped = cm.clip(data, mask.to_crs(4326))
    overlay = cm.overlay(data, mask.to_crs(4326))
    assert cm.area(clipped).sum() == pytest.approx(1, abs=1e-6)
    assert cm.area(overlay).sum() == pytest.approx(1, abs=1e-6)


def test_audit_and_repair():
    invalid = Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)])
    data = cm.GeoDataFrame(geometry=[invalid, None, Point(), invalid], crs=32733)
    report = cm.validate(data)
    assert report["invalid_geometries"] == 2
    assert report["missing_geometries"] == 1
    assert report["empty_geometries"] == 1
    assert report["duplicate_geometries"] == 1
    assert cm.validate(cm.make_valid(data))["invalid_geometries"] == 0


def test_original_profile_rules():
    data = polygons()
    data.loc[1, "nom"] = None
    report = cm.vector.analyze(data, name="Villages")
    assert report["label_field"] == "nom"
    assert report["thematic_field"] == "classe"
    assert report["fields"][0]["null_count"] == 1
    assert report["sampled_features"] == 2


def test_xy_roundtrip_and_missing_crs(tmp_path):
    data = cm.from_xy({"longitude":[15.0], "latitude":[-4.0], "nom":["A"]})
    path = tmp_path/"points.gpkg"
    data.to_file(path)
    assert cm.read_file(path).nom.tolist() == ["A"]
    with pytest.raises(ValueError, match="no CRS"):
        cm.validate(cm.GeoDataFrame(geometry=[Point(0,0)]))
    with pytest.raises(ValueError, match="finite"):
        cm.from_xy({"longitude":[np.inf], "latitude":[0]})
