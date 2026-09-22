"""Reproducible project analysis using explicitly synthetic land-cover data."""
from pathlib import Path
import json
import argparse
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point,LineString
import cartomize as cm


def create_data(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    y,x=np.mgrid[:400,:480]
    inside=((x-240)/205)**2+((y-200)/163)**2<1
    classes=np.where((x+1.3*y)%155<85,2,3).astype('uint8')
    classes[(x>260)&(y>210)]=4;classes[~inside]=0
    path=directory/'occupation_du_sol.tif'
    with rasterio.open(path,'w',driver='GTiff',width=480,height=400,count=1,dtype='uint8',
                       crs=32733,transform=from_origin(300000,9500000,10,10),compress='lzw') as dst:
        dst.write(classes,1);dst.update_tags(CARTOMIZE_CLASSES=json.dumps({
            '2':['Forêt primaire','#2e7145'],'3':['Forêt secondaire','#9dbf75'],
            '4':['Cultures','#e4c477']},ensure_ascii=False))
    cm.GeoDataFrame({'nom':['Route A']},geometry=[LineString([(300750,9498000),(301700,9497200),(303500,9498300)])],crs=32733).to_file(directory/'routes.geojson')
    cm.GeoDataFrame({'nom':['Localité A','Localité B']},geometry=[Point(301700,9497200),Point(303500,9498300)],crs=32733).to_file(directory/'localites.geojson')
    return [path,directory/'routes.geojson',directory/'localites.geojson']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('destination',nargs='?',default='demonstration_projet')
    directory=Path(parser.parse_args().destination).resolve()
    if directory.exists():raise FileExistsError('Choisir un nouveau répertoire de démonstration.')
    layers=create_data(directory/'donnees')
    project=cm.prepare_project(layers,directory/'analyse')
    mapped=project.compose(title='Occupation du sol',subtitle='Données synthétiques de démonstration',
                          credits='Cartomize · Classes et géométries fictives')
    for suffix in ['pdf','png']:mapped.export(directory/f'carte.{suffix}',dpi=120)
    print(project.manifest)


if __name__=='__main__':main()
