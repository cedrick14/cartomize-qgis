"""Scientific and end-to-end checks for the 0.6 processing paths."""
import json
import threading
from pathlib import Path
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box,Point
import cartomize as cm


@pytest.fixture
def spectral(tmp_path):
    path=tmp_path/'scientific.tif';data=np.zeros((4,64,64),dtype='float32');rng=np.random.default_rng(6)
    for b in range(4):data[b]=rng.normal(.1+b*.03,.002,(64,64));data[b,:,32:]+=.55
    data[:,0,:]=-9999
    with rasterio.open(path,'w',driver='GTiff',width=64,height=64,count=4,dtype='float32',crs='EPSG:32631',transform=from_origin(500000,1000000,10,10),nodata=-9999) as dst:dst.write(data);dst.descriptions=('blue','green','red','nir')
    geometries=[];classes=[];labels=[]
    for code,x,name in [(0,500040,'Forêt'),(7,500380,'Cultures')]:
        for y in [999440,999580,999720,999860]:geometries.append(box(x,y,x+150,y+80));classes.append(code);labels.append(name)
    training=gpd.GeoDataFrame({'classe':classes,'nom':labels},geometry=geometries,crs=32631);training.to_file(tmp_path/'training.gpkg',driver='GPKG',index=False)
    return path,training


@pytest.mark.parametrize('method',['random_forest','extra_trees'])
def test_classification_holdout_model_mask_and_confidence(spectral,tmp_path,method):
    path,training=spectral
    output=cm.classify_landcover(path,training,tmp_path/method,class_column='classe',label_column='nom',n_estimators=20,algorithm=method,sample_limit=1000,block_size=32)
    with rasterio.open(output) as src:
        result=src.read(1,masked=True);assert result.mask[0,:].all();assert (result[1:,:32]==0).all();assert (result[1:,32:]==7).all()
        assert json.loads(src.tags()['CARTOMIZE_CLASSES'])['0'][0]=='Forêt'
    with rasterio.open(output.parent/'confidence.tif') as src:assert (src.read(1,masked=True).compressed()>=.5).all()
    report=json.loads((output.parent/'classification.json').read_text());assert report['validation']['accuracy']==1;assert report['validation_method']=='held_out_features'
    model=cm.load_classifier(output.parent/'model');other=cm.classify_landcover(path,None,tmp_path/(method+'-loaded'),model=model,block_size=32)
    with rasterio.open(other) as src:np.testing.assert_equal(src.read(1,masked=True),result)


def test_cluster_and_cancellation(spectral,tmp_path):
    path,_=spectral;out=cm.cluster_raster(path,tmp_path/'cluster',clusters=2,sample_limit=1000,block_size=32)
    with rasterio.open(out) as src:
        data=src.read(1,masked=True);assert np.unique(data[1:,:32]).size==1;assert np.unique(data[1:,32:]).size==1;assert data[1,1]!=data[1,50];assert data.mask[0,0]
    cancel=threading.Event();cancel.set()
    with pytest.raises(cm.ProcessingCancelled):cm.classify_landcover(path,None,tmp_path/'cancelled',cancel=cancel)
    assert not (tmp_path/'cancelled').exists()


def test_full_plan_produces_classified_map_and_reopenable_sources(spectral,tmp_path):
    path,training=spectral
    plan=cm.plan_cartography([path],goal='landcover',classification='supervised',training=tmp_path/'training.gpkg',title='Occupation du sol',credits='Données de test')
    assert any(n['operation']=='classify' for n in plan['nodes'])
    output=cm.run_plan(plan,tmp_path/'automatic',formats=['png'],dpi=72)
    report=json.loads(output.read_text());assert Path(report['outputs'][0]).stat().st_size>1000
    assert all(Path(layer['data']).exists() for layer in report['layers'])
    from cartomize.session import map_from_document
    mapping=map_from_document(json.loads(Path(report['map_file']).read_text()));assert mapping.layers
    assert all(s['status']=='completed' for s in report['steps'])


def test_map_portability_geometry_and_style(spectral,tmp_path):
    path,training=spectral;mapping=cm.Map(title='Carte',template=cm.list_templates()[0]['id']).add_layer(path).add_layer(training,name='Échantillons',column='classe')
    plan=mapping.plan;item=next(i for i in plan.items if i.kind=='title');mapping.set_item(item.item_id,style={**item.style,'fontSize':8})
    archive=mapping.save(tmp_path/'portable.cmz',portable=True)
    path.rename(tmp_path/'source-renamed.tif')
    reopened=cm.Map.load(archive);assert reopened.title=='Carte';assert len(reopened.layers[1].data)==8
    assert next(i for i in reopened.plan.items if i.item_id==item.item_id).style['fontSize']==8
    assert Path(reopened.layers[0].data).is_file()


def test_recipe_batch_variables_bindings_and_protection(spectral,tmp_path):
    path,training=spectral
    config=dict(layers=[dict(data=str(tmp_path/'training.gpkg'))],options=dict(title='${title}'))
    recipe=cm.save_recipe(config,tmp_path/'recipe.json')
    manifest=dict(schema='cartomize.batch.v1',recipe_path=str(recipe),dpi=72,jobs=[dict(job_id='one',variables={'title':'Première carte'},output_formats=['png']),dict(job_id='two',variables={'title':'Deuxième carte'},output_formats=['png'])])
    out=cm.run_batch(manifest,tmp_path/'series');report=json.loads(out.read_text());assert report['complete'];assert len(report['jobs'])==2
    assert all(Path(x['outputs'][0]).is_file() for x in report['jobs'])
    manifest['jobs'][0]['output_name']='../escape'
    with pytest.raises(ValueError):cm.run_batch(manifest,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_terrain_horn_convolution_block_boundaries_and_units(tmp_path):
    y,x=np.mgrid[0:80,0:80];z=(x*10.).astype('float32');source=tmp_path/'dem.tif'
    with rasterio.open(source,'w',driver='GTiff',width=80,height=80,count=1,dtype='float32',crs='EPSG:32631',transform=from_origin(500000,1000000,10,10)) as dst:dst.write(z,1)
    products=['slope','aspect','hillshade','tpi','tri','roughness']
    small=cm.terrain(source,tmp_path/'small.tif',products=products,block_size=32,workers=2)
    large=cm.terrain(source,tmp_path/'large.tif',products=products,block_size=256)
    with rasterio.open(small) as a,rasterio.open(large) as b:
        np.testing.assert_equal(a.read(),b.read());values=a.read();np.testing.assert_allclose(values[0,1:-1,1:-1],45);np.testing.assert_allclose(values[1,1:-1,1:-1],270)
        np.testing.assert_allclose(values[3,1:-1,1:-1],0,atol=1e-7);np.testing.assert_allclose(values[4,1:-1,1:-1],np.sqrt(600),rtol=1e-6);np.testing.assert_allclose(values[5,1:-1,1:-1],20)
        assert np.isnan(values[:,0,:]).all()
    out=cm.convolve(source,tmp_path/'smooth.tif',np.ones((3,3)),normalize=True,block_size=32)
    with rasterio.open(out) as src:np.testing.assert_allclose(src.read(1)[1:-1,1:-1],z[1:-1,1:-1])
    with pytest.raises(ValueError):cm.convolve(source,tmp_path/'bad.tif',[[1,-1]],normalize=True)


def test_training_conflicts_validation_leakage_and_unavailable(spectral,tmp_path):
    source,training=spectral
    overlap=training.copy();overlap.loc[4,'geometry']=overlap.loc[0,'geometry']
    with pytest.raises(ValueError,match='même pixel|partagent des pixels'):cm.fit_classifier(source,overlap,'classe',sample_limit=20,n_estimators=10)
    with pytest.raises(ValueError,match='partagent des pixels'):cm.fit_classifier(source,training,'classe',validation=training,sample_limit=20,n_estimators=10)
    model=cm.fit_classifier(source,training.iloc[[0,4]],'classe',n_estimators=10)
    assert model.report['validation'] is None and model.report['validation_method']=='unavailable'
    with pytest.raises(ValueError,match='Groupes'):cm.fit_classifier(source,training,'classe',group_column='absent')
    with pytest.raises(ValueError,match='libellés'):cm.fit_classifier(source,training,'classe',label_column='absent')


def test_portable_prepared_project_and_unrelated_output_exclusion(spectral,tmp_path):
    import zipfile
    source,_=spectral;prepared=cm.prepare_project([source],tmp_path/'prepared')
    unrelated=tmp_path/'other.txt';unrelated.write_text('not a source')
    state=dict(input_directories=[],output_directory=str(tmp_path),manifest=str(prepared.manifest))
    out=cm.save_session(state,tmp_path/'session.cmz',portable=True)
    with zipfile.ZipFile(out) as archive:assert not any(name.endswith('other.txt') for name in archive.namelist())
    import shutil
    shutil.rmtree(prepared.directory);source.unlink()
    loaded=cm.load_session(out);assert not loaded.missing
    project=cm.load_project(loaded.state['manifest']);assert all(Path(layer['data']).is_file() for layer in project.layers)
    with zipfile.ZipFile(tmp_path/'bad.cmz','w') as archive:archive.writestr('../escape','bad')
    with pytest.raises(ValueError):cm.load_session(tmp_path/'bad.cmz')


def test_native_qgis_inventory_and_runtime_failure(tmp_path):
    import sys,zipfile
    source=tmp_path/'data.geojson';gpd.GeoDataFrame({'nom':['A']},geometry=[Point(1,2)],crs=4326).to_file(source)
    xml='<qgis><projectlayers><maplayer type="vector"><id>points</id><layername>Localités</layername><provider>ogr</provider><datasource>./data.geojson</datasource><srs><spatialrefsys><authid>EPSG:4326</authid></spatialrefsys></srs></maplayer></projectlayers><Layouts><Layout name="Carte"/></Layouts></qgis>'
    project=tmp_path/'project.qgz'
    with zipfile.ZipFile(project,'w') as archive:archive.writestr('project.qgs',xml)
    result=cm.native_project(project);assert result['layers'][0]['source']==str(source);assert result['layouts'][0]['name']=='Carte'
    with pytest.raises(RuntimeError,match='qgis'):cm.native_project(project,python=sys.executable,action='copy',destination=tmp_path/'copy.qgz')
    assert not (tmp_path/'copy.qgz').exists()


def test_mapops_actual_file_changes_and_review_fingerprint(tmp_path):
    source=tmp_path/'data.txt';source.write_text('one');state={'data':str(source)};old=cm.snapshot_project(state)
    review=cm.record_review(old,tmp_path/'review.json',reviewer='Cartographe',quality={'valid':True})
    assert cm.verify_review(review,old)
    source.write_text('two');current=cm.snapshot_project(state);assert not cm.verify_review(review,current)
    change=cm.compare_snapshots(old,current);assert change['changed'] and change['files'][0]['kind']=='modified'
    old['state']['title']='tampered';assert not cm.verify_review(review,old)
    with pytest.raises(ValueError):cm.record_review(current,tmp_path/'invalid.json',reviewer='Cartographe',quality={'valid':False})


def test_failed_batch_is_atomic_and_continuation_is_explicit(spectral,tmp_path):
    path,_=spectral;recipe={'schema':'cartomize.recipe.v1','config':{'layers':[{'data':str(path)}],'options':{'title':'${title}'}}}
    manifest=dict(recipe=recipe,dpi=72,jobs=[dict(job_id='good',variables={'title':'Carte'}),dict(job_id='failed',variables={})])
    with pytest.raises(ValueError):cm.run_batch(manifest,tmp_path/'strict')
    assert not (tmp_path/'strict').exists()
    output=cm.run_batch(manifest,tmp_path/'continue',continue_on_error=True);record=json.loads(output.read_text());assert not record['complete'];assert [j['status'] for j in record['jobs']]==['completed','failed']


def test_plan_rejects_output_traversal(tmp_path):
    plan=dict(schema='cartomize.automation.v1',nodes=[dict(id='../escape',requires=[],operation='repair',parameters={})])
    with pytest.raises(ValueError):cm.run_plan(plan,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_spatial_relations_measure_actual_geometries():
    left=gpd.GeoDataFrame(geometry=[box(500000,1000000,500100,1000100)],crs=32631)
    right=gpd.GeoDataFrame(geometry=[box(500050,1000000,500150,1000100)],crs=32631)
    distant=gpd.GeoDataFrame(geometry=[box(500200,1000000,500300,1000100)],crs=32631)
    report=cm.analyze_relations([{'data':left,'name':'A'},{'data':right,'name':'B'},{'data':distant,'name':'C'}],metric_crs=32631)
    assert report['pairs'][0]['relation']=='intersects' and report['pairs'][0]['intersection_m2']==5000
    assert report['pairs'][1]['distance_m']==100


def test_scenes_plan_discovers_mosaics_and_applies_supplemental_layers(write_raster,tmp_path):
    prefix='LC08_L2SP_181063_20260817_20260820_02_T1'
    files=[write_raster(f'{prefix}_SR_B{index}.TIF',np.full((12,12),10000+index*1000,dtype='uint16'),nodata=0) for index in [2,3,4,5]]
    files.append(write_raster(f'{prefix}_QA_PIXEL.TIF',np.full((12,12),64,dtype='uint16'),nodata=0))
    with rasterio.open(files[0]) as src:bounds=src.bounds;crs=src.crs
    vector=tmp_path/'localites.geojson';gpd.GeoDataFrame({'nom':['Localité']},geometry=[Point((bounds.left+bounds.right)/2,(bounds.top+bounds.bottom)/2)],crs=crs).to_file(vector)
    plan=cm.plan_cartography(files,data_kind='scenes',layers=[vector],indices=['NDVI'],title='Image satellite',credits='Test')
    output=cm.run_plan(plan,tmp_path/'scenes-production',formats=['png'],dpi=72)
    record=json.loads(output.read_text());assert Path(record['outputs'][0]).is_file()
    assert any(layer['data'].endswith('localites.geojson') for layer in record['layers'])
    assert any(node['operation']=='indices' for node in record['steps'])
