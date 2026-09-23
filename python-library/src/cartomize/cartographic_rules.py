"""Automatic frame extents and thematic tables derived from actual map data."""
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from .raster import class_areas
from .nodata import _windows


def _bounds(layer,crs):
    if layer.kind=='vector':return layer.data.to_crs(crs).total_bounds
    with rasterio.open(layer.data) as src:return Transformer.from_crs(src.crs,crs,always_xy=True).transform_bounds(*src.bounds)


def thematic_table(map_object):
    layer=next((l for l in reversed(map_object.layers) if l.kind=='raster' and l.classes),None)
    if layer:
        with rasterio.open(layer.data) as src:
            if src.crs.is_projected:
                table=class_areas(layer.data,band=layer.band,unit='ha');table=table.rename(columns={'class':'Code','area_ha':'Superficie (ha)','pixels':'Pixels'})
            else:
                counts={}
                for win in _windows(src,512):
                    values,n=np.unique(src.read(layer.band,window=win,masked=True).compressed(),return_counts=True)
                    for value,count in zip(values,n):counts[float(value)]=counts.get(float(value),0)+int(count)
                table=pd.DataFrame([{'Code':code,'Pixels':n} for code,n in sorted(counts.items())])
        code='Code' if 'Code' in table else table.columns[0]
        table.insert(1,'Classe',[layer.classes.get(float(v),(str(v),'grey'))[0] for v in table[code]])
        return table
    layer=next((l for l in map_object.layers if l.kind=='vector' and l.column),None)
    if layer:return layer.data[layer.column].value_counts(dropna=False).rename_axis('Classe').reset_index(name='Effectif')
    return pd.DataFrame([{'Couche':l.name,'Entités':len(l.data)} for l in map_object.layers if l.kind=='vector'])


def complete_map(map_object):
    if not map_object.layers:return map_object
    bounds=map_object.extent
    if bounds is None:
        candidates=[_bounds(l,map_object.crs) for l in map_object.layers]
        candidates=[b for b in candidates if np.isfinite(b).all()]
        if not candidates:raise ValueError('Aucune emprise géographique valide.')
        a=np.asarray(candidates);bounds=(a[:,0].min(),a[:,1].min(),a[:,2].max(),a[:,3].max())
        x0,y0,x1,y1=bounds;dx=max((x1-x0)*.03,1e-5);dy=max((y1-y0)*.03,1e-5)
        bounds=(x0-dx,y0-dy,x1+dx,y1+dy);map_object.set_extent(bounds)
    if map_object.plan:
        for item in map_object.plan.map_items:
            if item.item_id in map_object.frames:continue
            role=item.content.get('role','main');x0,y0,x1,y1=bounds;cx=(x0+x1)/2;cy=(y0+y1)/2
            factor=1.7 if role=='locator' else .5 if role in {'detail','zoom'} else 1
            extent=(cx-(x1-x0)*factor/2,cy-(y1-y0)*factor/2,cx+(x1-x0)*factor/2,cy+(y1-y0)*factor/2)
            map_object.set_frame(item.item_id,extent=extent)
        table=thematic_table(map_object)
        for item in map_object.plan.items:
            if item.kind=='table' and item.item_id not in map_object.tables and not table.empty:
                displayed=table[['Classe','Superficie (ha)']].copy() if 'Superficie (ha)' in table else table.drop(columns=['Code'],errors='ignore')
                if 'Superficie (ha)' in displayed:displayed['Superficie (ha)']=displayed['Superficie (ha)'].map(lambda x:f'{x:.2f}')
                map_object.set_table(item.item_id,displayed)
            if item.kind=='chart' and item.item_id not in map_object.charts and not table.empty:
                labels='Classe' if 'Classe' in table else table.columns[0]
                numeric=[c for c in table if pd.api.types.is_numeric_dtype(table[c]) and c not in {'Code'}]
                if numeric:map_object.set_chart(item.item_id,table[labels].astype(str),table[numeric[-1]],color='#444444')
    return map_object


def desktop_map_config(map_object,layers,directory):
    directory=Path(directory);elements=[]
    for ident,text in map_object.texts.items():elements.append(dict(id=ident,kind='text',content=text,labels='',values=''))
    for ident,table in map_object.tables.items():
        path=directory/f'table_{len(elements)}.csv';table.to_csv(path,index=False)
        elements.append(dict(id=ident,kind='table',content=str(path),labels='',values=''))
    for ident,(labels,values,_) in map_object.charts.items():
        path=directory/f'chart_{len(elements)}.csv';pd.DataFrame({'Classe':labels,'Valeur':values}).to_csv(path,index=False)
        elements.append(dict(id=ident,kind='chart',content=str(path),labels='Classe',values='Valeur'))
    return dict(layers=layers,rgb=None,aoi=None,options=dict(title=map_object.title,subtitle=map_object.subtitle,credits=map_object.credits,crs=str(map_object.crs)),
        layout=dict(template=map_object.plan.template_id if map_object.plan else None,format='A3' if max(map_object.width,map_object.height)>350 else 'A4',
                    orientation='landscape' if map_object.width>map_object.height else 'portrait',legend=map_object.legend_enabled,scale=map_object.scale_enabled,north=map_object.north_enabled,
                    frames=[dict(frame_id=k,extent=v['extent'],layers=v['layers'],crs=str(v['crs']) if v['crs'] else None) for k,v in map_object.frames.items()],elements=elements))
