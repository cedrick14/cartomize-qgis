import hashlib
import json
import threading
import numpy as np
import pytest
import rasterio
from rasterio.enums import ColorInterp
from scipy.ndimage import binary_propagation
import cartomize as cm


def padded():
    a=np.zeros((103,119),dtype='int16');a[13:90,14:105]=2;a[40:75,48:84]=3
    a[50:53,55:58]=0
    return a


def test_detect_and_prepare_reversible_project(write_raster,tmp_path):
    a=padded();path=write_raster('occupation.tif',a,nodata=None)
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    assert cm.detect_background(path)['automatic_border_values']==[0]
    stages=[];progress=[]
    project=cm.prepare_project([path],tmp_path/'prepared',stage=stages.append,progress=lambda d,t:progress.append((d,t)))
    assert project.manifest.is_file() and stages[0]=='Analyse du projet' and progress[-1]==(100,100)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==checksum
    with rasterio.open(project.layers[0]['data']) as src:
        np.testing.assert_array_equal(src.read(1),a)
        assert not src.read_masks(1)[0,0] and src.read_masks(1)[51,56]==255
    assert set(project.layers[0]['classes'])=={0,2,3}
    restored=cm.load_project(project.manifest,original_sources=True)
    assert restored.layers[0]['data']==path and 'classes' not in restored.layers[0]
    mapped=project.compose(title='Occupation du sol')
    fig=mapped.render();image=fig.axes[0].images[0].get_array()
    assert np.ma.getmaskarray(image)[0,0] and not np.ma.getmaskarray(image)[51,56]
    from matplotlib import pyplot as plt
    plt.close(fig)


@pytest.mark.parametrize('shape',[(103,119),(97,65),(64,64)])
def test_block_connected_mask_matches_independent_flood_fill(write_raster,tmp_path,shape):
    rng=np.random.default_rng(16);a=np.where(rng.random(shape)>.53,2,0).astype('int16')
    # A long connected component crosses several blocks; a disconnected island remains.
    a[10:70,30]=0;a[10,:31]=0;a[35:42,40:47]=2;a[37:40,42:45]=0
    path=write_raster('maze.tif',a,nodata=None);out=tmp_path/'masked.tif'
    cm.mask_background(path,out,border_values=[0],block_size=32)
    seed=np.zeros(shape,bool);seed[0]=a[0]==0;seed[-1]=a[-1]==0;seed[:,0]=a[:,0]==0;seed[:,-1]=a[:,-1]==0
    removed=binary_propagation(seed,mask=a==0)
    with rasterio.open(out) as src:np.testing.assert_array_equal(src.read_masks(1)==0,removed)
    assert not (tmp_path/'masked.tif.msk').exists()


def test_declared_nodata_nan_and_provider_mask_preserved(write_raster,tmp_path):
    a=np.ones((65,65),dtype='float32');a[0]=np.nan;a[1,1]=0
    valid=np.ones_like(a,bool);valid[2,2]=False
    path=write_raster('provider.tif',a,nodata=np.nan,mask=valid);out=tmp_path/'copy.tif'
    cm.mask_background(path,out,keep_values=[0])
    with rasterio.open(out) as src:
        mask=src.read_masks(1);assert not mask[0].any() and not mask[2,2] and mask[1,1]
        np.testing.assert_array_equal(src.read(1),a)


@pytest.mark.parametrize('binary',[True,False])
def test_binary_and_uniform_zero_are_not_automatic_nodata(write_raster,tmp_path,binary):
    a=np.zeros((80,80),dtype='uint8')
    if binary:a[10:70,10:70]=1
    path=write_raster('valid_zero.tif',a,nodata=None)
    assert cm.detect_background(path)['automatic_border_values']==[]
    project=cm.prepare_project([path],tmp_path/'project')
    assert project.layers[0]['data']==path and 0 in project.layers[0]['classes']


def test_class_labels_and_keep_values_protect_real_classes(write_raster,tmp_path):
    path=write_raster('classes.tif',padded(),nodata=None)
    with rasterio.open(path,'r+') as src:
        src.update_tags(CARTOMIZE_CLASSES=json.dumps({'0':['Eau','#176dad'],'2':['Forêt primaire','#256f3b'],'3':['Forêt secondaire','#8ead49']}))
    project=cm.prepare_project([path],tmp_path/'classified')
    assert project.layers[0]['data']==path
    assert project.layers[0]['classes'][0]==('Eau','#176dad')
    assert project.layers[0]['classes'][2][0]=='Forêt primaire'
    # Explicit user NoData overrides class metadata, unless keep_values says otherwise.
    project2=cm.prepare_project([dict(data=path,nodata_values=[0])],tmp_path/'explicit')
    assert 0 not in project2.layers[0]['classes']
    project3=cm.prepare_project([dict(data=path,nodata_values=[0],keep_values=[0])],tmp_path/'keep')
    assert project3.layers[0]['data']==path


def test_rgb_border_transparency_preserves_interior_black(write_raster,tmp_path):
    a=padded().astype('uint8');rgb=np.stack([a*30,a*50,a*20])
    path=write_raster('rgb.tif',rgb,nodata=None)
    with rasterio.open(path,'r+') as src:src.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue)
    project=cm.prepare_project([path],tmp_path/'rgb_project')
    rgba,_,_=cm.read_rgb(project.layers[0]['data'],bands='native')
    assert rgba[0,0,3]==0 and rgba[51,56,3]>0 and (rgba[51,56,:3]==0).all()


def test_cancelled_or_invalid_preparation_publishes_nothing(write_raster,tmp_path):
    path=write_raster('source.tif',padded(),nodata=None);event=threading.Event()
    def stop(done,total):
        if done>=25:event.set()
    with pytest.raises(cm.ProcessingCancelled):cm.prepare_project([path],tmp_path/'cancelled',cancel=event,progress=stop)
    assert not (tmp_path/'cancelled').exists() and not list(tmp_path.glob('.cartomize-project-*'))
    with pytest.raises(ValueError,match='Aucun pixel valide'):
        cm.prepare_project([dict(data=path,nodata_values=[0,2,3])],tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()
    with pytest.raises(ValueError):cm.mask_background(path,path,border_values=[0],overwrite=True)


def test_project_combines_vector_roles_and_reprojects_for_rendering(write_raster,tmp_path):
    from shapely.geometry import Point,LineString
    from matplotlib import pyplot as plt
    raster=write_raster('occupation.tif',padded(),nodata=None)
    localities=tmp_path/'localites.geojson';roads=tmp_path/'routes.geojson'
    cm.GeoDataFrame({'nom':['Site A']},geometry=[Point(300500,9499500)],crs=32733).to_crs(4326).to_file(localities)
    cm.GeoDataFrame(geometry=[LineString([(300100,9499900),(300900,9499200)])],crs=32733).to_file(roads)
    project=cm.prepare_project([localities,raster,roads],tmp_path/'mixed')
    assert project.report['reprojection_required']
    mapped=project.compose(title='Projet de contrôle')
    assert [layer['role'] for layer in mapped.layer_plan()]==['landcover','roads','localities']
    assert next(layer for layer in mapped.layers if layer.role=='localities').labels=='nom'
    fig=mapped.render();plt.close(fig)


def test_mask_cancellation_preserves_existing_destination(write_raster,tmp_path):
    path=write_raster('source.tif',padded(),nodata=None);out=tmp_path/'existing.tif';out.write_bytes(b'previous output')
    event=threading.Event()
    def stop(done,total):
        if done>total//2:event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.mask_background(path,out,border_values=[0],block_size=32,overwrite=True,cancel=event,progress=stop)
    assert out.read_bytes()==b'previous output' and not list(tmp_path.glob('.cartomize-*.tif'))
