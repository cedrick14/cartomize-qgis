"""Renderer transfer checks: class boundaries, symbol units and real exports."""
import json,xml.etree.ElementTree as ET
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box,Point,LineString
import cartomize as cm
from cartomize.native_styles import layer_style


def symbol(name,color,kind='SimpleFill',extra=''):
    return f'<symbol name="{name}"><layer class="{kind}"><Option name="color" value="{color}"/>{extra}</layer></symbol>'


def test_graduated_classes_boundaries_and_persistence(tmp_path):
    xml='<maplayer><renderer-v2 type="graduatedSymbol" attr="pop"><ranges><range lower="0" upper="100" symbol="0" label="Faible"/><range lower="100" upper="200" symbol="1" label="Élevée"/></ranges><symbols>'+symbol('0','0,100,0,255')+symbol('1','240,180,0,255')+'</symbols></renderer-v2></maplayer>'
    style,warnings=layer_style(ET.fromstring(xml));assert not warnings
    data=gpd.GeoDataFrame({'pop':[0,100,101,200,201]},geometry=[box(i,0,i+.8,.8) for i in range(5)],crs=32733)
    mapping=cm.Map(title='Classes graduées').add_layer(data,**style)
    fig=mapping.render(dpi=80);ax=next(a for a in fig.axes if len(a.collections)==2)
    assert [len(c.get_paths()) for c in ax.collections]==[2,2]
    mapping.save(tmp_path/'graduated.cmz',portable=True);restored=cm.Map.load(tmp_path/'graduated.cmz')
    assert restored.layers[0].ranges==mapping.layers[0].ranges
    restored.export(tmp_path/'graduated.png',dpi=80)


def test_category_visibility_and_marker_units(tmp_path):
    xml='<maplayer><renderer-v2 type="categorizedSymbol" attr="code"><categories><category value="1" type="int" symbol="0" label="Carré"/><category value="2" type="int" symbol="1" render="false" label="Masqué"/></categories><symbols>'+symbol('0','50,100,200,255','SimpleMarker','<Option name="name" value="square"/><Option name="size" value="2"/><Option name="size_unit" value="MM"/>')+symbol('1','200,50,50,255','SimpleMarker')+'</symbols></renderer-v2></maplayer>'
    style,warnings=layer_style(ET.fromstring(xml));assert style['hidden_categories']==[2]
    assert style['category_styles'][1]['marker']=='s'
    assert style['category_styles'][1]['markersize']==pytest.approx((2*72/25.4)**2)
    data=gpd.GeoDataFrame({'code':[1,2]},geometry=[Point(0,0),Point(1,1)],crs=32733)
    mapping=cm.Map().add_layer(data,**style);fig=mapping.render(dpi=80)
    ax=next(a for a in fig.axes if a.collections);assert len(ax.collections)==1 and len(ax.collections[0].get_offsets())==1
    mapping.save(tmp_path/'points.cmz',portable=True);cm.Map.load(tmp_path/'points.cmz').export(tmp_path/'points.png',dpi=80)


def test_composite_line_symbol_widths():
    xml='<maplayer><renderer-v2 type="singleSymbol"><symbols><symbol name="0">'
    for color,width in [('10,10,10,255','2'),('255,255,255,255','1')]:
        xml+=f'<layer class="SimpleLine"><Option name="line_color" value="{color}"/><Option name="line_width" value="{width}"/><Option name="line_width_unit" value="MM"/></layer>'
    xml+='</symbol></symbols></renderer-v2></maplayer>'
    style,warnings=layer_style(ET.fromstring(xml));assert len(style['symbol_layers'])==2 and warnings
    data=gpd.GeoDataFrame(geometry=[LineString([(0,0),(2,1)])],crs=32733)
    fig=cm.Map().add_layer(data,**style).render(dpi=80);ax=next(a for a in fig.axes if a.collections)
    np.testing.assert_allclose([c.get_linewidths()[0] for c in ax.collections],[2*72/25.4,72/25.4])


@pytest.mark.parametrize('mode',['INTERPOLATED','DISCRETE','EXACT'])
def test_raster_shader_transfer(mode,write_raster,tmp_path):
    source=write_raster('classes.tif',np.tile(np.arange(6,dtype='float32'),(6,1)))
    xml=f'<maplayer><pipe><rasterrenderer type="singlebandpseudocolor" band="1"><rastershader><colorrampshader colorRampType="{mode}"><item value="0" label="Bas" color="#0000ff" alpha="255"/><item value="2" label="Moyen" color="#00ff00" alpha="255"/><item value="4" label="Haut" color="#ff0000" alpha="255"/></colorrampshader></rastershader></rasterrenderer></pipe></maplayer>'
    style,warnings=layer_style(ET.fromstring(xml));assert not warnings
    mapping=cm.Map().add_layer(source,**style);fig=mapping.render(dpi=80);ax=next(a for a in fig.axes if a.images);display=ax.images[0].get_array()
    if mode=='EXACT':assert int(np.ma.getmaskarray(display).sum())>0
    elif mode=='DISCRETE':assert np.ma.max(display)==2
    else:assert ax.images[0].norm.vmin==0 and ax.images[0].norm.vmax==4
    mapping.save(tmp_path/'ramp.cmz',portable=True);cm.Map.load(tmp_path/'ramp.cmz').export(tmp_path/'ramp.png',dpi=80)


def test_grayscale_contrast_transfer(write_raster):
    style,warnings=layer_style(ET.fromstring('<maplayer><pipe><rasterrenderer type="singlebandgray" grayBand="1"><contrastEnhancement><minValue>0</minValue><maxValue>100</maxValue></contrastEnhancement></rasterrenderer></pipe></maplayer>'))
    assert style['raster_range']==[0,100]
    source=write_raster('gray.tif',np.arange(100,dtype='float32').reshape(10,10))
    fig=cm.Map().add_layer(source,**style).render(dpi=80);ax=next(a for a in fig.axes if a.images)
    assert ax.images[0].norm.vmax==100
