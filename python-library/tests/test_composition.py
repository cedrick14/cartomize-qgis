import numpy as np
import pytest
from shapely.geometry import Point,LineString,box
import cartomize as cm


def layers(write_raster):
    source=write_raster("rgb.tif",np.ones((3,4,4),dtype="float32"))
    road=cm.GeoDataFrame(geometry=[LineString([(300000,9499960),(300040,9500000)])],crs=32733)
    points=cm.GeoDataFrame({"nom":["A"]},geometry=[Point(300020,9499980)],crs=32733)
    bounds=cm.GeoDataFrame(geometry=[box(300000,9499960,300040,9500000)],crs=32733)
    return source,road,points,bounds


def test_auto_order_arbitrary_input_and_boundary_transparency(write_raster):
    source,roads,points,bounds=layers(write_raster)
    m=cm.Map().add_layers([
        {"data":points,"name":"Localités"},
        {"data":bounds,"name":"Limites district"},
        {"data":roads,"name":"Routes"},
        {"data":source,"name":"Satellite","rgb":(1,2,3)},
    ])
    assert [r["name"] for r in m.layer_plan()]==["Satellite","Routes","Limites district","Localités"]
    assert next(l for l in m.layers if l.role=="boundaries").color=="none"
    assert next(l for l in m.layers if l.role=="localities").labels=="nom"
    fig=m.render(dpi=60)
    ax=fig.axes[0]
    assert ax.images[0].get_zorder()==0
    assert max(c.get_zorder() for c in ax.collections)==60
    assert all(t.get_zorder()>60 for t in ax.texts if t.get_text()=="A")
    fig.clear()


def test_explicit_order_and_role_override(write_raster):
    source,roads,points,bounds=layers(write_raster)
    m=cm.Map(auto_order=False).add_layer(points,name="first").add_layer(source,name="last")
    assert [r["name"] for r in m.layer_plan()]==["first","last"]
    m=cm.Map().add_layer(bounds,name="unknown",role="boundaries",zorder=100)
    assert m.layer_plan()[0]["role"]=="boundaries" and m.layer_plan()[0]["zorder"]==100
    with pytest.raises(ValueError,match="role"):
        cm.Map().add_layer(points,role="invented")


def test_composer_clips_vectors_and_reprojects_aoi(write_raster):
    source,roads,points,bounds=layers(write_raster)
    aoi=cm.GeoDataFrame(geometry=[box(300000,9499960,300020,9500000)],crs=32733).to_crs(4326)
    m=cm.compose_map([{"data":roads,"name":"Routes"},{"data":source,"rgb":(1,2,3)}],aoi=aoi,crs=32733)
    assert m.extent[2]==pytest.approx(300020,abs=.001)
    assert m.layers[0].data.total_bounds[2]<=300020.001
