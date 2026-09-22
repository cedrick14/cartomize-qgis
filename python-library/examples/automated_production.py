"""Reproducible desktop/API demonstration using explicitly synthetic data."""
from pathlib import Path
import argparse
import numpy as np
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import box, Point, LineString
import cartomize as cm


def create_data(destination):
    destination=Path(destination);scenes=destination/"scenes";scenes.mkdir(parents=True,exist_ok=True)
    y,x=np.mgrid[0:96,0:96]
    for scene,origin_x,shift in [("181063",300000,0),("181064",302100,70)]:
        prefix=f"LC08_L2SP_{scene}_20260817_20260820_02_T1"
        xx=x+shift
        for band in (2,3,4,5):
            values=10000+band*650+1200*np.sin(xx/17)+850*np.cos(y/13)
            if band==5:values+=1600*np.sin((xx+y)/23)**2
            values=values.astype("uint16")
            with rasterio.open(scenes/f"{prefix}_SR_B{band}.TIF","w",driver="GTiff",width=96,height=96,
                               count=1,dtype="uint16",crs=32733,transform=from_origin(origin_x,9500000,30,30),nodata=0) as dst:dst.write(values,1)
        qa=np.full((96,96),64,dtype="uint16")
        with rasterio.open(scenes/f"{prefix}_QA_PIXEL.TIF","w",driver="GTiff",width=96,height=96,count=1,
                           dtype="uint16",crs=32733,transform=from_origin(origin_x,9500000,30,30),nodata=0) as dst:dst.write(qa,1)
    zone=gpd.GeoDataFrame({"nom":["Emprise fictive"]},geometry=[box(300240,9497360,304650,9499760)],crs=32733)
    zone.to_file(destination/"zone_etude.geojson")
    routes=gpd.GeoDataFrame({"nom":["Route fictive"]},geometry=[LineString([(300240,9497700),(301300,9498600),(303200,9498100),(304650,9499400)])],crs=32733)
    routes.to_file(destination/"routes.geojson")
    points=gpd.GeoDataFrame({"nom":["Localité A","Localité B","Localité C"]},geometry=[Point(301300,9498600),Point(303200,9498100),Point(304200,9499000)],crs=32733)
    points.to_file(destination/"localites.geojson")
    return scenes


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("directory",type=Path);args=parser.parse_args()
    scenes=create_data(args.directory/"donnees")
    result=cm.cartographic_workflow(scenes,args.directory/"production",
        aoi=args.directory/"donnees/zone_etude.geojson",
        layers=[args.directory/"donnees/routes.geojson",args.directory/"donnees/localites.geojson"],
        title="Production cartographique — démonstration",credits="Cartomize · Données synthétiques sans valeur géographique réelle",dpi=120)
    print(result.directory)


if __name__=="__main__":main()
