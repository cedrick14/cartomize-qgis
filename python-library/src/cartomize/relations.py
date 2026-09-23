"""Measured spatial relations between vector geometries and raster footprints."""
from pathlib import Path
from itertools import combinations
import numpy as np
import geopandas as gpd
import rasterio
from shapely.geometry import box
from ._validation import frame,linear_factor
from .imagery import _check_cancel


def analyze_relations(layers,*,metric_crs=None,max_pairs=1000,cancel=None,progress=None):
    records=[]
    for i,item in enumerate(layers):
        spec=dict(item) if isinstance(item,dict) else {'data':item};source=spec['data'];name=spec.get('name') or (Path(source).stem if isinstance(source,(str,Path)) else f'Couche {i+1}')
        raster=spec.get('kind')=='raster' or isinstance(source,(str,Path)) and Path(source).suffix.lower() in {'.tif','.tiff','.jp2','.vrt','.img'}
        if raster:
            with rasterio.open(source) as src:data=gpd.GeoDataFrame(geometry=[box(*src.bounds)],crs=src.crs)
        else:data=frame(source)
        usable=data.geometry.notna()&~data.geometry.is_empty
        if not data.loc[usable].geometry.is_valid.all():raise ValueError(f'Géométries invalides : {name}')
        records.append(dict(name=name,kind='raster_footprint' if raster else 'vector',data=data.loc[usable]))
    pairs=len(records)*(len(records)-1)//2
    if pairs>max_pairs:raise ValueError('Trop de couples de couches pour ce diagnostic ; sélectionner les couches pertinentes.')
    if metric_crs is None:
        present=[r['data'].to_crs(4326) for r in records if not r['data'].empty]
        if not present:return {'pairs':[],'crs':None,'scope':'No nonempty geometry.'}
        import pandas as pd
        combined=gpd.GeoDataFrame(pd.concat(present,ignore_index=True),crs=4326)
        metric_crs=combined.estimate_utm_crs()
        if metric_crs is None:raise ValueError('Choisir une projection métrique adaptée au projet.')
    factor=linear_factor(metric_crs)
    for record in records:
        projected=record.pop('data').to_crs(metric_crs)
        record['geometry']=projected.geometry.union_all() if not projected.empty else None
    output=[]
    for i,(a,b) in enumerate(combinations(records,2),1):
        _check_cancel(cancel);left,right=a['geometry'],b['geometry']
        if left is None or right is None:relation='empty';distance=None;overlap=None
        else:
            relation='equal' if left.equals(right) else 'contains' if left.covers(right) else 'within' if right.covers(left) else 'intersects' if left.intersects(right) else 'disjoint'
            distance=float(left.distance(right)*factor);overlap=float(left.intersection(right).area*factor**2)
        output.append(dict(left=a['name'],right=b['name'],relation=relation,distance_m=distance,intersection_m2=overlap,
                           scope='footprint' if 'raster_footprint' in {a['kind'],b['kind']} else 'geometry'))
        if progress:progress(i,pairs)
    return dict(schema='cartomize.relations.v1',crs=str(metric_crs),pairs=output,
                note='Les rasters sont comparés par leur emprise ; les mesures sont planes dans la projection indiquée.')
