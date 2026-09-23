"""Reproducible synthetic imagery, training references and automated mapping."""
from pathlib import Path
import argparse
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point,LineString
import cartomize as cm


def create_data(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    y,x=np.mgrid[:300,:400];inside=((x-200)/175)**2+((y-150)/126)**2<1
    classes=np.where((x+1.4*y)%130<75,0,1);classes[(x>235)&(y>150)]=2
    means=np.array([[.08,.14,.06,.5],[.13,.2,.12,.4],[.18,.22,.28,.33]],dtype='float32')
    rng=np.random.default_rng(2026);data=np.moveaxis(means[classes],-1,0)+rng.normal(0,.008,(4,300,400)).astype('float32');data[:,~inside]=np.nan
    transform=from_origin(300000,9500000,10,10);path=directory/'multibande.tif'
    with rasterio.open(path,'w',driver='GTiff',width=400,height=300,count=4,dtype='float32',crs=32733,transform=transform,nodata=np.nan,compress='lzw') as dst:dst.write(data);dst.descriptions=('blue','green','red','nir')
    points=[];labels=[]
    for code,name in enumerate(['Forêt primaire','Forêt secondaire','Cultures']):
        rows,cols=np.where(inside&(classes==code));chosen=rng.choice(len(rows),40,replace=False)
        for row,col in zip(rows[chosen],cols[chosen]):points.append(Point(*rasterio.transform.xy(transform,int(row),int(col))));labels.append(name)
    training=directory/'echantillons.gpkg';cm.GeoDataFrame({'classe':labels},geometry=points,crs=32733).to_file(training,index=False)
    roads=directory/'routes.geojson';cm.GeoDataFrame({'nom':['Route A']},geometry=[LineString([(300850,9498700),(301600,9497900),(303150,9498550)])],crs=32733).to_file(roads)
    localities=directory/'localites.geojson';cm.GeoDataFrame({'nom':['Localité A','Localité B']},geometry=[Point(301600,9497900),Point(303150,9498550)],crs=32733).to_file(localities)
    return path,training,[roads,localities]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('destination',nargs='?',default='demonstration_assistant');args=parser.parse_args()
    directory=Path(args.destination).resolve()
    if directory.exists():raise FileExistsError('Choisir un nouveau répertoire.')
    source,training,layers=create_data(directory/'donnees')
    plan=cm.plan_cartography([source,*layers],goal='landcover',classification='supervised',training=training,class_column='classe',title='Occupation du sol',credits='Cartomize · Données synthétiques de démonstration')
    print(cm.run_plan(plan,directory/'production',workers=2))


if __name__=='__main__':main()
