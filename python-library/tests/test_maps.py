import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest
from shapely.geometry import box, Point
from PIL import Image
import cartomize as cm


def data():
    return cm.GeoDataFrame({"nom":["Zone A","Zone B"],"classe":["A","B"]},geometry=[box(300000,9500000,301000,9501000),box(301000,9500000,302000,9501000)],crs=32733)


def test_original_sources_preserved():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/"docs/PROVENANCE.json").read_text())
    for relative, record in manifest["files"].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == record["sha256"]
    assert "arcpy" not in sys.modules and "qgis" not in sys.modules


def test_all_24_templates_valid():
    templates = cm.list_templates()
    assert len(templates) == 24
    for item in templates:
        plan = cm.layout_plan(item["id"])
        assert plan.map_items
        for element in plan.items:
            assert element.x_mm + element.width_mm <= plan.page_width_mm + .001


@pytest.mark.parametrize("extension",["png","pdf","svg"])
def test_real_exports_and_physical_dimensions(tmp_path, extension):
    m = cm.Map(title="Cartomize test",crs=32733).add_layer(data(),column="classe",labels="nom",cmap="Set2")
    out = m.export(tmp_path/f"map.{extension}",dpi=80)
    assert out.stat().st_size > 1000
    if extension == "png":
        with Image.open(out) as image:
            assert image.size == (int(297/25.4*80),int(210/25.4*80))
    if extension == "pdf":
        assert out.read_bytes().startswith(b"%PDF")
    if extension == "svg":
        assert "<svg" in out.read_text()


def test_template_frames_independent(tmp_path):
    item = next(t for t in cm.list_templates() if t["map_frames"] >= 3)
    m = cm.Map(template=item["id"],title="Multi-cadres").add_layer(data())
    m.set_frame(m.frame_ids[0],extent=(299000,9499000,303000,9502000))
    m.set_frame(m.frame_ids[1],extent=(300000,9500000,301000,9501000))
    fig = m.render(dpi=60)
    assert fig.axes[0].get_xlim() == (299000,303000)
    assert fig.axes[1].get_xlim() == (300000,301000)
    fig.clear()


def test_raster_classes_zero_and_missing_classes(write_raster):
    source = write_raster("classes.tif",np.array([[0,1],[2,-9999]],dtype="int16"))
    m = cm.Map().add_layer(source,classes={0:("Zero","white"),1:("Forest","green"),2:("Other","tan")})
    fig = m.render(dpi=70)
    image = fig.axes[0].images[0].get_array()
    assert image.count() == 3
    assert image[0,0] == 0
    fig.clear()
    with pytest.raises(ValueError,match="missing"):
        cm.Map().add_layer(source,classes={1:("Forest","green")}).render()


def test_scale_length_matches_geodesic():
    from pyproj import Transformer,Geod
    m = cm.Map().add_layer(data())
    fig = m.render(dpi=80)
    ax = fig.axes[0]
    scale = next(line for line in ax.lines if line.get_marker() == "|")
    xs,ys=scale.get_data()
    tr=Transformer.from_crs(32733,4326,always_xy=True)
    p,q=tr.transform(xs[0],ys[0]),tr.transform(xs[1],ys[1])
    distance=Geod(ellps="WGS84").inv(*p,*q)[2]
    assert any(text.get_text() == f"{round(distance):g} m" for text in ax.texts)
    fig.clear()


def test_atlas_no_mutation_and_duplicate_names(tmp_path):
    zones=data()
    m=cm.Map(title="Atlas").add_layer(zones)
    paths=cm.atlas(m,zones,tmp_path,name_column="nom",format="png",dpi=50)
    assert len(paths)==2 and all(p.exists() for p in paths)
    assert m.title=="Atlas" and m.extent is None
    zones["nom"]=["a/b","a b"]
    with pytest.raises(ValueError,match="unique"):
        cm.atlas(m,zones,tmp_path/"duplicate",name_column="nom")
    assert not (tmp_path/"duplicate").exists()


def test_cli_templates(capsys):
    from cartomize.cli import main
    assert main(["templates"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 24
