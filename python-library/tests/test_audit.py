"""Independent numerical expectations and regressions from the 0.5 audit."""
import json
import threading
import numpy as np
import pytest
import rasterio
from shapely.geometry import Point,Polygon,box
import cartomize as cm


EXPECTED_INDICES={'NDVI':.5,'EVI':1/2.05,'EVI2':1/2.08,'SAVI':.6/1.3,'OSAVI':.4/.96,
    'MSAVI':(2.2-np.sqrt(1.64))/2,'GNDVI':1/3,'NDRE':.2,'NDWI':-1/3,'MNDWI':-.25,
    'NDMI':1/11,'NBR':.5,'NBR2':3/7,'NDBI':-1/11,'BSI':0.,'ARVI':5/7,'VARI':.25,'SR':3.}


@pytest.mark.parametrize('index,expected',EXPECTED_INDICES.items())
def test_each_published_index_numerically(write_raster,tmp_path,index,expected):
    # Fixed reflectances: blue=.1, green=.3, red=.2, nir=.6,
    # rededge1=.4, swir1=.5, swir2=.2. Expected numbers independent of registry.
    source=write_raster('spectrum.tif',np.array([[[v]] for v in [.1,.3,.2,.6,.4,.5,.2]],dtype='float64'))
    with rasterio.open(source,'r+') as src:src.descriptions=('blue','green','red','nir','rededge1','swir1','swir2')
    output=cm.spectral_indices(source,tmp_path/'index.tif',index)
    with rasterio.open(output) as src:assert src.read(1)[0,0]==pytest.approx(expected,abs=1e-6)


@pytest.mark.parametrize('statistic',['mean','sum','min','max','std','median','count'])
def test_every_temporal_statistic_against_numpy(write_raster,tmp_path,statistic):
    arrays=np.array([[[1,2],[4,-9999]],[[3,-9999],[8,-9999]],[[5,7],[12,-9999]]],dtype='float64')
    paths=[write_raster(f'{i}.tif',a) for i,a in enumerate(arrays)]
    out=cm.reduce_rasters(paths,tmp_path/'reduce.tif',statistic=statistic,dtype='float64')
    with rasterio.open(out) as src:
        result=src.read(1,masked=True)
        for y,x in [(0,0),(0,1),(1,0)]:
            values=arrays[:,y,x];values=values[values!=-9999]
            expected=len(values) if statistic=='count' else getattr(np,statistic)(values)
            assert result[y,x]==pytest.approx(expected)
        if statistic=='count':assert result[1,1]==0
        else:assert result.mask[1,1]


def test_calibration_survives_clip_and_reprojection(write_raster,tmp_path):
    source=write_raster('dn.tif',np.full((4,4),10000,dtype='int16'))
    with rasterio.open(source,'r+') as src:
        src.scales=(.0000275,);src.offsets=(-.2,);src.descriptions=('red',);src.set_band_unit(1,'reflectance')
    zone=cm.GeoDataFrame(geometry=[box(300000,9499960,300040,9500000)],crs=32733)
    clipped=cm.raster.clip(source,zone,tmp_path/'clip.tif')
    projected=cm.raster.reproject(clipped,tmp_path/'projected.tif',32733)
    for p in [clipped,projected]:
        with rasterio.open(p) as src:
            assert src.descriptions==('red',) and src.units==('reflectance',)
            assert src.scales==(.0000275,) and src.offsets==(-.2,)
        out=cm.calculate('red',{'red':p},tmp_path/(p.stem+'_calibrated.tif'))
        with rasterio.open(out) as src:np.testing.assert_allclose(src.read(1),.075,atol=1e-7)


def test_all_input_paths_protected_and_stale_sidecar_removed(write_raster,tmp_path):
    source=write_raster('source.tif',np.full((4,4),3,dtype='float32'))
    other=write_raster('other.tif',np.full((4,4),9,dtype='float32'));before=other.read_bytes()
    with pytest.raises(ValueError):cm.calculate('x',{'x':source,'unused':other},other,overwrite=True)
    assert other.read_bytes()==before
    mask=tmp_path/'mask.geojson';cm.GeoDataFrame(geometry=[box(300000,9499960,300040,9500000)],crs=32733).to_file(mask)
    original=mask.read_bytes()
    with pytest.raises(ValueError):cm.raster.clip(source,mask,mask,overwrite=True)
    assert mask.read_bytes()==original
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(other,'r+') as dst:dst.write_mask(np.zeros((4,4),dtype='uint8'))
    assert (tmp_path/'other.tif.msk').exists()
    cm.calculate('x*2',{'x':source},other,overwrite=True)
    assert not (tmp_path/'other.tif.msk').exists()
    with rasterio.open(other) as src:assert src.read(1,masked=True).count()==16


def test_display_product_and_duplicate_spectral_mapping_rejected(write_raster,tmp_path):
    source=write_raster('display.tif',np.ones((4,2,2),dtype='uint8'),nodata=None)
    with rasterio.open(source,'r+') as src:src.update_tags(CARTOMIZE_PRODUCT='display_rgba')
    with pytest.raises(ValueError,match='scientific'):cm.spectral_indices(source,tmp_path/'index.tif','NDVI',band_map={'red':1,'nir':2})
    source2=write_raster('science.tif',np.ones((2,2,2),dtype='float32'))
    with pytest.raises(ValueError,match='distinct'):cm.spectral_indices(source2,tmp_path/'index.tif','NDVI',band_map={'red':1,'nir':1})


def test_nearest_ties_limits_feet_and_sources_unchanged():
    left=cm.GeoDataFrame({'id':[1]},geometry=[Point(1000000,200000)],crs=2263)
    right=cm.GeoDataFrame({'target':['a','b']},geometry=[Point(1000100,200000),Point(999900,200000)],crs=2263)
    result=cm.nearest(left,right)
    assert set(result.target)=={'a','b'}
    np.testing.assert_allclose(result.distance_m,30.480060960121918)
    assert cm.nearest(left,right,max_distance=30).distance_m.isna().all()
    assert left.geometry.iloc[0].equals(Point(1000000,200000)) and left.columns.tolist()==['id','geometry']
    with pytest.raises(ValueError):cm.nearest(left.to_crs(4326),right)
    aligned=cm.nearest(left.to_crs(4326),right,metric_crs=2263)
    assert aligned.crs.to_epsg()==4326 and aligned.distance_m.iloc[0]==pytest.approx(30.48006,abs=.001)


def test_quality_gate_invalid_geometries_and_atomic_export(tmp_path,monkeypatch):
    bad=cm.GeoDataFrame(geometry=[Polygon([(0,0),(2,2),(2,0),(0,2),(0,0)])],crs=32733)
    m=cm.Map(title='Test').add_layer(bad)
    assert not m.audit()['valid']
    with pytest.raises(ValueError,match='invalides'):m.export(tmp_path/'bad.png')
    m=cm.Map(title='Test',credits='Source').add_layer(cm.make_valid(bad))
    assert m.audit()['valid']
    from matplotlib.figure import Figure
    destination=tmp_path/'existing.png';destination.write_bytes(b'original')
    def fail(*args,**kwargs):raise OSError('simulated disk error')
    monkeypatch.setattr(Figure,'savefig',fail)
    with pytest.raises(OSError):m.export(destination,overwrite=True)
    assert destination.read_bytes()==b'original'
    assert not list(tmp_path.glob('.cartomize-*'))


@pytest.mark.parametrize('template',cm.list_templates(),ids=lambda x:x['id'])
def test_each_template_renders_all_supported_item_types(tmp_path,template):
    frame=cm.GeoDataFrame({'code':[1,2]},geometry=[box(300000,9500000,301000,9501000),box(301000,9500000,302000,9501000)],crs=32733)
    m=cm.Map(template=template['id'],title='Contrôle',credits='Données synthétiques').add_layer(frame,column='code',classes={1:('A','#448844'),2:('B','#bbaa77')})
    assert m.layers[0].categorical
    for item in m.plan.items:
        if item.kind=='text':m.set_text(item.item_id,'Texte de contrôle')
        elif item.kind=='table':m.set_table(item.item_id,{'Classe':['A','B'],'Surface':[10,20]})
        elif item.kind=='chart':m.set_chart(item.item_id,['A','B'],[10,20])
    assert m.audit()['valid']
    assert m.export(tmp_path/'page.png',dpi=60).stat().st_size>1000
    with pytest.raises(KeyError):m.set_text('unknown_item','Silent no-op forbidden')


def test_assessment_order_geometry_findings_and_cli(write_raster,tmp_path,capsys):
    data=np.zeros((100,100),dtype='int16');data[20:80,20:80]=2
    source=write_raster('classes.tif',data,nodata=None)
    bad=tmp_path/'invalid.geojson';cm.GeoDataFrame(geometry=[Polygon([(0,0),(2,2),(2,0),(0,2),(0,0)])],crs=32733).to_file(bad)
    report=cm.assess_project([source,bad],goal='landcover')
    assert not report['ready'] and report['recommended_template']['category']=='occupation_sol'
    assert [s['tool'] for s in report['steps']]==['vector','project','mapping']
    assert {'background_candidate','classification_scope','invalid_geometry'}<={i['code'] for i in report['issues']}
    assert source.exists() and not list(tmp_path.glob('*.msk'))
    from cartomize.cli import main
    assert main(['assess',str(source),'--goal','atlas'])==0
    assert json.loads(capsys.readouterr().out)['steps'][-1]['tool']=='atlas'
    assert main(['project',str(tmp_path/'prepared'),str(source)])==0
    assert json.loads(capsys.readouterr().out)['sources_modified'] is False
    event=threading.Event();event.set()
    with pytest.raises(cm.ProcessingCancelled):cm.assess_project([source],cancel=event)


def test_assessment_scenes_before_indices(write_raster,tmp_path):
    prefix='LC08_L2SP_181063_20260817_20260820_02_T1'
    for index in [2,3,4,5]:write_raster(f'{prefix}_SR_B{index}.TIF',np.full((2,2),10000,dtype='uint16'),nodata=0)
    report=cm.assess_project(tmp_path,data_kind='scenes')
    assert report['ready']
    assert [s['tool'] for s in report['steps']]==['prepare','composite','project','mapping']
    assert report['issues'][0]['code']=='missing_quality'
    assert not cm.assess_project([tmp_path/'missing.tif'])['ready']
