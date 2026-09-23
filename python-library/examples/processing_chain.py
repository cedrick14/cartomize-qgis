"""Generate a reproducible synthetic terrain-to-map demonstration.

Run: python examples/processing_chain.py /path/to/new/demo
All geographic data in this example are synthetic.
"""
from pathlib import Path
import sys
import json
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point
import cartomize as cm


def create_demo(destination):
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    y,x=np.mgrid[:160,:160]
    elevation=(600-y*1.8+90*np.sin(x/20)+20*np.cos(y/12)).astype('float32')
    source=root/'mnt.tif'
    with rasterio.open(source,'w',driver='GTiff',width=160,height=160,count=1,
                       crs=32733,transform=from_origin(300000,9500000,10,10),dtype='float32',nodata=-9999) as dst:
        dst.write(elevation,1);dst.set_band_description(1,'elevation');dst.set_band_unit(1,'m')
    localities=root/'localites.gpkg'
    gpd.GeoDataFrame({'nom':['Station A','Station B','Station C']},geometry=[Point(300300,9499700),Point(301100,9499400),Point(300700,9498800)],crs=32733).to_file(localities)
    steps=[
        dict(id='pente',operation='terrain',parameters={'source':str(source),'products':['slope']},
             map_layer={'name':'Pente (°)','cmap':'YlOrBr','legend':True,'categorical':False}),
        dict(id='drainage',operation='hydrology',parameters={'source':str(source),'stream_threshold':100}),
        dict(id='reseau',operation='calculate',parameters={'inputs':{'a':['@drainage:accumulation',1]},'expression':'where(a >= 100, 1, a / 0)'},
             map_layer={'name':'Réseau de drainage','classes':{1:['Drainage D8','#2867a3']},'legend':True,'zorder':40}),
    ]
    plan=cm.plan_cartography([dict(data=str(source),legend=False),str(localities)],processing_steps=steps,
        template='topographique/institutionnel',title='Relief et drainage',
        credits='Données synthétiques • Démonstration Cartomize')
    from cartomize.storage import save_json
    save_json(plan,root/'plan.json')
    result=cm.run_plan(plan,root/'production',workers=2,block_size=128,dpi=150)
    report=json.loads(result.read_text(encoding='utf-8'))
    mapping=cm.Map.load(report['map_file']);mapping.save(root/'projet.cmz',portable=True)
    return result


if __name__=='__main__':
    print(create_demo(sys.argv[1] if len(sys.argv)>1 else 'demonstration-cartomize'))
