"""Independent expected results and complete workflows for the completion patch."""
import hashlib
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import numpy as np
import geopandas as gpd
import rasterio
import pytest
from shapely.geometry import Point,LineString,box
import cartomize as cm


def test_registered_chain_terrain_algebra_focal_and_map(write_raster,tmp_path):
    y,x=np.mgrid[:48,:48];source=write_raster('dem.tif',(x*10.).astype('float32'))
    steps=[dict(id='slope',operation='terrain',parameters={'source':str(source),'products':['slope']}),
           dict(id='threshold',operation='calculate',parameters={'inputs':{'a':['@slope',1]},'expression':'where(a >= 40, 1, 0)'},map_layer={'name':'Pentes fortes','classes':{1:['Pente ≥ 40°','#333333']}}),
           dict(id='smooth',operation='focal',parameters={'source':'@threshold','size':3,'statistic':'mean'})]
    plan=cm.plan_cartography([{'data':str(source),'legend':False}],processing_steps=steps,title='Relief',credits='Test')
    report=json.loads(cm.run_plan(plan,tmp_path/'production',dpi=72,formats=['png']).read_text())
    with rasterio.open(report['results']['smooth']) as src:np.testing.assert_allclose(src.read(1,masked=True).compressed(),1)
    assert Path(report['outputs'][0]).is_file()
    mapping=cm.Map.load(report['map_file']);assert any(l.name=='Pentes fortes' for l in mapping.layers)
    assert all('.cartomize-' not in str(v) for v in report['results'].values())


def test_graph_validation_precedes_all_writes(write_raster,tmp_path):
    source=write_raster('a.tif',np.ones((10,10),dtype='float32'));original=source.read_bytes()
    with pytest.raises(ValueError,match='dépendances'):
        cm.run_plan({'schema':'cartomize.automation.v1','nodes':[{'id':'a','operation':'process','parameters':{'operator':'terrain','arguments':{'source':'@missing'}},'requires':[]}]},tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()
    with pytest.raises(ValueError,match='réservés'):
        cm.execute_operation('terrain',{'source':str(source),'destination':str(source)},tmp_path/'overwrite')
    assert source.read_bytes()==original
    with pytest.raises(ValueError):cm.processing_plan([{'id':'one','operation':'terrain','parameters':{'source':'@two'}},{'id':'two','operation':'terrain','parameters':{'source':str(source)}}])


@pytest.mark.parametrize('operation,parameters,expected',[
    ('vector.buffer',{'distance':10},None),('vector.dissolve',{},1),('vector.make_valid',{},2),
    ('vector.reproject',{'crs':'EPSG:32732'},2),('vector.area',{'unit':'m2'},2),('vector.length',{},2),
    ('vector.clip',{},2),('vector.intersection',{},2),('vector.union',{},3),('vector.difference',{},0),
    ('vector.symmetric_difference',{},1),('vector.sjoin',{},2),('vector.nearest',{},2)])
def test_each_registered_vector_operation(tmp_path,operation,parameters,expected):
    source=tmp_path/'left.gpkg';other=tmp_path/'right.gpkg'
    data=gpd.GeoDataFrame({'id':[1,2]},geometry=[box(0,0,10,10),box(20,0,30,10)],crs=32733);data.to_file(source)
    gpd.GeoDataFrame({'zone':['Z']},geometry=[box(-1,-1,31,11)],crs=32733).to_file(other)
    spec=next(s for s in cm.operation_catalog() if s['id']==operation);names={p['name'] for p in spec['parameters']}
    p=dict(parameters)
    if 'data' in names:p['data']=str(source)
    elif 'left' in names:p['left']=str(source)
    else:p['source']=str(source)
    if 'mask' in names:p['mask']=str(other)
    if 'right' in names:p['right']=str(other)
    result=cm.execute_operation(operation,p,tmp_path/'out');output=gpd.read_file(result['primary'])
    if expected is not None:assert len(output)==expected
    if operation=='vector.area':np.testing.assert_allclose(output.area_m2,100)
    if operation=='vector.length':np.testing.assert_allclose(output.length_m,40)
    assert gpd.read_file(source).equals(data)


def test_full_raster_audit_detects_a_single_unmapped_pixel(write_raster):
    a=np.ones((1100,1100),dtype='int16');a[333,717]=9;source=write_raster('classes.tif',a)
    m=cm.Map(title='Classes').add_layer(source,classes={1:['Forêt','green']})
    assert any(i['code']=='unmapped_classes' for i in m.audit()['issues'])


def test_valid_footprint_preserves_real_zero_inside(write_raster,tmp_path):
    data=np.zeros((2,40,40),dtype='int16');data[:,10:30,10:30]=10;data[:,15:20,15:20]=0
    source=write_raster('valid-zero.tif',data,nodata=-9999)
    with rasterio.open(source) as src:
        transform=src.transform;a=transform*(10,10);b=transform*(30,30);crs=src.crs
    footprint=tmp_path/'footprint.geojson';gpd.GeoDataFrame(geometry=[box(a[0],b[1],b[0],a[1])],crs=crs).to_file(footprint)
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    output=cm.mask_background(source,tmp_path/'masked.tif',valid_footprint=footprint)
    with rasterio.open(output['path']) as src:
        values=src.read(masked=True);assert values.mask[:,0,:].all();assert not values.mask[:,15:20,15:20].any();assert (values[:,15:20,15:20]==0).all()
    assert output['outside_footprint_masked']==1200 and hashlib.sha256(source.read_bytes()).hexdigest()==original


def test_qgis_style_sublayer_order_and_group_visibility(tmp_path):
    package=tmp_path/'features.gpkg';gpd.GeoDataFrame({'classe':[1,2],'nom':['A','B']},geometry=[Point(0,0),Point(30,30)],crs=32733).to_file(package,layer='localites')
    project=tmp_path/'project.qgs'
    project.write_text('''<qgis><layer-tree-group checked="Qt::Checked"><layer-tree-layer id="a" checked="Qt::Checked"/><layer-tree-group checked="Qt::Unchecked"><layer-tree-layer id="b" checked="Qt::Checked"/></layer-tree-group></layer-tree-group><projectlayers>
    <maplayer type="vector" labelsEnabled="1"><id>a</id><layername>Localités</layername><provider>ogr</provider><datasource>./features.gpkg|layername=localites</datasource><layerOpacity>0.8</layerOpacity><renderer-v2 type="categorizedSymbol" attr="classe"><categories><category value="1" type="int" symbol="0" label="Village"/><category value="2" type="int" symbol="1" label="Ville"/></categories><symbols><symbol name="0"><layer class="SimpleMarker"><Option><Option name="color" value="255,0,0,255"/></Option></layer></symbol><symbol name="1"><layer class="SimpleMarker"><prop k="color" v="0,0,255,255"/></layer></symbol></symbols></renderer-v2><labeling><settings><text-style fieldName="nom" isExpression="0"/></settings></labeling></maplayer>
    <maplayer type="vector"><id>b</id><layername>Masquée</layername><provider>ogr</provider><datasource>./missing.gpkg</datasource></maplayer></projectlayers></qgis>''',encoding='utf-8')
    inventory=cm.inspect_qgis_project(project);assert not inventory['layers'][1]['visible']
    transfer=cm.import_native_project(project,tmp_path/'imported');assert not transfer['transfer_warnings']
    mapping=cm.Map.load(transfer['map_file']);assert len(mapping.layers)==1
    layer=mapping.layers[0];assert layer.labels=='nom' and layer.alpha==.8 and layer.classes[1][0]=='Village' and layer.classes[2][1]=='#0000ffff'
    mapping.export(tmp_path/'native.png',dpi=72)
    assert 'layername=localites' in project.read_text()


def test_hydrology_plane_accumulation_and_watershed(write_raster,tmp_path):
    y,x=np.mgrid[:7,:7];source=write_raster('dem.tif',(70-y*10).astype('float32'))
    result=cm.hydrology(source,tmp_path/'hydro',stream_threshold=5)
    with rasterio.open(result) as src:
        a=src.read(1);np.testing.assert_array_equal(a[:,3],np.arange(1,8))
        point=Point(*rasterio.transform.xy(src.transform,5,3))
    outlets=tmp_path/'outlet.gpkg';gpd.GeoDataFrame(geometry=[point],crs=32733).to_file(outlets)
    cm.hydrology(source,tmp_path/'basin',outlets=outlets)
    with rasterio.open(tmp_path/'basin/watersheds.tif') as src:
        b=src.read(1);assert (b[:6,3]==1).all();assert b[6,3]==0


def test_hydrology_fills_sink_no_cycles_budget_and_cancel(write_raster,tmp_path):
    z=np.full((7,7),10.,dtype='float32');z[1:-1,1:-1]=2
    source=write_raster('sink.tif',z);cm.hydrology(source,tmp_path/'filled')
    with rasterio.open(tmp_path/'filled/filled.tif') as src:np.testing.assert_array_equal(src.read(1),10)
    with rasterio.open(tmp_path/'filled/direction.tif') as src:d=src.read(1)
    with rasterio.open(tmp_path/'filled/accumulation.tif') as src:a=src.read(1)
    assert a[d==0].sum()==49
    event=threading.Event();event.set()
    with pytest.raises(cm.ProcessingCancelled):cm.hydrology(source,tmp_path/'cancelled',cancel=event)
    assert not (tmp_path/'cancelled').exists()


def test_routing_intersections_length_disconnection_and_snap(tmp_path):
    network=gpd.GeoDataFrame(geometry=[LineString([(0,0),(100,0)]),LineString([(50,-50),(50,50)])],crs=32733)
    file=tmp_path/'roads.gpkg';network.to_file(file)
    result=cm.execute_operation('routing',{'source':str(file),'start':[0,0],'end':[50,50],'max_snap_m':0},tmp_path/'route')
    route=gpd.read_file(result['primary'])
    assert route.distance_m.iloc[0]==100 and list(route.geometry.iloc[0].coords)==[(0,0),(50,0),(50,50)]
    with pytest.raises(ValueError,match='déconnectées'):cm.shortest_path(network,[0,0],[50,50],max_snap_m=0,node_intersections=False)
    with pytest.raises(ValueError,match='rattachement'):cm.shortest_path(network,[0,5000],[50,50],max_snap_m=10)


def test_stac_metadata_calibration_and_manifest_discovery(write_raster,tmp_path):
    source=write_raster('foreign.tif',np.full((4,12,12),1000,dtype='int16'))
    item={'type':'Feature','stac_version':'1.1.0','id':'custom','properties':{'platform':'test-sensor','datetime':'2026-01-01T00:00:00Z'},'assets':{'image':{'href':source.name,'bands':[{'name':role,'eo:common_name':role,'scale':.001,'offset':-.1,'unit':'reflectance','nodata':-9999} for role in ['blue','green','red','nir']]}},'links':[]}
    path=tmp_path/'item.json';path.write_text(json.dumps(item))
    scene=cm.discover_scenes(path)[0];assert scene.bands['nir'].index==4 and scene.bands['red'].scale==.001
    output=cm.execute_operation('prepare',{'sources':str(path),'band_order':['red','nir'],'mask_clouds':False},tmp_path/'prepared')
    with rasterio.open(output['primary']) as src:np.testing.assert_allclose(src.read(masked=True).compressed(),.9,rtol=1e-5)


def test_stac_http_download_hash_limit_and_pagination(tmp_path):
    data=b'geospatial-test-data';digest=hashlib.sha256(data).hexdigest();host={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/asset.tif':body=data
            elif self.path.startswith('/search'):
                page=2 if 'page=2' in self.path else 1
                item={'type':'Feature','stac_version':'1.0.0','id':str(page),'properties':{'datetime':'2026-01-01T00:00:00Z'},'assets':{'red':{'href':host['url']+'/asset.tif','file:checksum':'1220'+digest,'eo:bands':[{'common_name':'red'}]}},'links':[]}
                body=json.dumps({'type':'FeatureCollection','features':[item],'links':[{'rel':'next','href':host['url']+'/search?page=2'}] if page==1 else []}).encode()
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);host['url']=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        search=cm.execute_operation('stac.search',{'endpoint':host['url'],'bbox':[10,-5,11,-4],'limit':2},tmp_path/'search');found=json.loads(Path(search['primary']).read_text());assert [i['id'] for i in found['features']]==['1','2']
        path=tmp_path/'found.json';path.write_text(json.dumps(found))
        downloaded=Path(cm.execute_operation('stac.download',{'source':str(path),'assets':['red']},tmp_path/'download')['primary'])
        local=json.loads(downloaded.read_text());assert all((downloaded.parent/i['assets']['red']['href']).read_bytes()==data for i in local['features'])
        assert len(cm.discover_scenes(downloaded))==2
        plan=cm.processing_plan([dict(id='assets',operation='stac.download',parameters={'source':str(path),'assets':['red']})])
        production=json.loads(cm.run_plan(plan,tmp_path/'production').read_text())
        manifest=Path(production['results']['assets']);nested=json.loads(manifest.read_text())
        assert all((manifest.parent/i['assets']['red']['href']).read_bytes()==data for i in nested['features'])
        with pytest.raises(ValueError,match='Limite'):cm.download_stac(path,tmp_path/'limited',max_bytes=2)
        assert not (tmp_path/'limited').exists()
    finally:server.shutdown();server.server_close();thread.join()


def test_point_symbols_do_not_collide_with_label_boxes():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.transforms import Bbox
    from cartomize.typography import place_labels
    fig=Figure(figsize=(4,4),dpi=100);FigureCanvasAgg(fig);ax=fig.subplots();ax.set_xlim(0,10);ax.set_ylim(0,10);fig.canvas.draw()
    report=place_labels(ax,[(5,5,'Localité'),(5.1,5.1,'Village')],obstacles=[(5,5,12),(5.1,5.1,12)])
    boxes=[Bbox.from_extents(*b) for b in report['boxes']]
    assert report['placed']>=1
    for box in boxes:
        for x,y in [(5,5),(5.1,5.1)]:
            px,py=ax.transData.transform((x,y));r=12*100/72
            assert not box.overlaps(Bbox.from_extents(px-r,py-r,px+r,py+r))
    assert not any(a.overlaps(b) for i,a in enumerate(boxes) for b in boxes[i+1:])


@pytest.mark.parametrize('operation',['raster.clip','raster.reproject','raster.reclassify','raster.zonal_stats','raster.class_areas','raster.change_matrix'])
def test_registered_raster_operations(write_raster,tmp_path,operation):
    source=write_raster('classes.tif',np.ones((10,10),dtype='int16'))
    with rasterio.open(source) as src:bounds=src.bounds;crs=src.crs
    mask=tmp_path/'mask.gpkg';gpd.GeoDataFrame(geometry=[box(*bounds)],crs=crs).to_file(mask)
    parameters={'source':str(source)}
    if operation=='raster.clip':parameters['mask']=str(mask)
    elif operation=='raster.reproject':parameters['crs']=str(crs)
    elif operation=='raster.reclassify':parameters['mapping']={'1':7}
    elif operation=='raster.zonal_stats':parameters['zones']=str(mask)
    elif operation=='raster.change_matrix':parameters={'before':str(source),'after':str(source)}
    result=cm.execute_operation(operation,parameters,tmp_path/'out')
    if result['kind']=='raster':
        with rasterio.open(result['primary']) as src:np.testing.assert_equal(src.read(1,masked=True).compressed(),7 if operation=='raster.reclassify' else 1)
    elif operation=='raster.class_areas':
        import pandas as pd
        assert pd.read_csv(result['primary']).area_ha.iloc[0]==1
    elif operation=='raster.zonal_stats':assert gpd.read_file(result['primary'])['mean'].iloc[0]==1
    else:assert Path(result['primary']).stat().st_size>10


def test_other_registered_array_operators(write_raster,tmp_path):
    source=write_raster('bands.tif',np.stack([np.full((16,16),v,dtype='float32') for v in [.1,.2,.3,.9]]))
    with rasterio.open(source,'r+') as src:src.descriptions=('blue','green','red','nir')
    cases=[('indices',{'source':str(source),'indices':['NDVI']},.5),
           ('reduce',{'sources':[str(source),str(source)],'statistic':'sum'},.2),
           ('convolve',{'source':str(source),'kernel':[[1,1,1],[1,1,1],[1,1,1]],'normalize':True},.1),
           ('background',{'source':str(source)},.1)]
    for operation,parameters,expected in cases:
        result=cm.execute_operation(operation,parameters,tmp_path/operation)
        with rasterio.open(result['primary']) as src:np.testing.assert_allclose(src.read(1,masked=True).compressed(),expected,rtol=1e-5)
    result=cm.execute_operation('composite',{'source':str(source)},tmp_path/'rgb')
    with rasterio.open(result['primary']) as src:assert src.count==4 and src.colorinterp[3].name=='alpha'


def test_named_hydrology_outputs_and_atomic_failure(write_raster,tmp_path):
    y,x=np.mgrid[:8,:8];source=write_raster('dem.tif',(80-y*10).astype('float32'))
    plan=cm.processing_plan([dict(id='drainage',operation='hydrology',parameters={'source':str(source)}),
        dict(id='area',operation='calculate',parameters={'inputs':{'acc':['@drainage:accumulation',1]},'expression':'acc*100'})])
    record=json.loads(cm.run_plan(plan,tmp_path/'good').read_text())
    with rasterio.open(record['results']['area']) as src:assert src.read(1)[-1,3]==800
    assert Path(record['products']['drainage']['watersheds']).is_file()
    with rasterio.open(record['results']['area']) as src:
        provenance=json.loads(src.tags()['inputs']);assert Path(provenance['acc']['path']).is_file()
        assert '.cartomize-' not in src.tags()['inputs']
    plan['nodes'][-1]['parameters']['arguments']['inputs']['acc'][0]='@drainage:absent'
    with pytest.raises(ValueError,match='Produit intermédiaire'):cm.run_plan(plan,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_registry_rejects_named_operator_override(tmp_path):
    with pytest.raises(ValueError,match='inconnus'):
        cm.execute_operation('vector.intersection',{'left':'a','right':'b','how':'union'},tmp_path/'bad')


def test_registered_classification_exposes_confidence_and_relocates_model(write_raster,tmp_path):
    data=np.ones((2,32,32),dtype='float32');data[:,:,16:]=10
    source=write_raster('spectral.tif',data)
    with rasterio.open(source) as src:
        bounds=src.bounds;crs=src.crs;mid=(bounds.left+bounds.right)/2
    training=tmp_path/'training.gpkg';gpd.GeoDataFrame({'class':[1,2]},geometry=[box(bounds.left,bounds.bottom,mid,bounds.top),box(mid,bounds.bottom,bounds.right,bounds.top)],crs=crs).to_file(training)
    classified=cm.execute_operation('classify',{'source':str(source),'training':str(training),'class_column':'class','n_estimators':10},tmp_path/'classified')
    assert Path(classified['products']['confidence']).is_file()
    with rasterio.open(classified['primary']) as src:assert (src.read(1)[:,:16]==1).all() and (src.read(1)[:,16:]==2).all()
    clustered=cm.execute_operation('cluster',{'source':str(source),'clusters':2,'sample_limit':500},tmp_path/'clustered')
    with rasterio.open(clustered['primary']) as src:assert np.unique(src.read(1)).size==2
    for path in (tmp_path/'classified').rglob('*.json'):assert '.cartomize-' not in path.read_text()



def test_stac_portable_session_follows_local_assets(write_raster,tmp_path):
    source=write_raster('red.tif',np.ones((12,12),dtype='float32'))
    item={'type':'Feature','stac_version':'1.1.0','id':'red','properties':{},'assets':{'red':{'href':source.name,'bands':[{'eo:common_name':'red','scale':1,'unit':'reflectance'}]}},'links':[]}
    path=tmp_path/'item.json';path.write_text(json.dumps(item))
    archive=cm.save_session({'manifest':str(path)},tmp_path/'scene.cmz',portable=True)
    path.unlink();source.unlink()
    loaded=cm.load_session(archive);assert not loaded.missing
    scenes=cm.discover_scenes(loaded.state['manifest']);assert Path(scenes[0].bands['red'].path).is_file()
