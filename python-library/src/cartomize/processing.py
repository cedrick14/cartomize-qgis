"""Registered, serializable operations shared by plans, the CLI and desktop.

Only named operators are accepted. A document cannot select Python callables,
change the output directory or overwrite an input. Every operation publishes a
new directory atomically and returns a primary product and its related files.
"""
from pathlib import Path
import inspect
import os
import json
from .storage import new_directory, save_json, json_value
from .imagery import _check_cancel


def _catalog():
    from . import vector, raster
    from .algebra import calculate, reduce_rasters
    from .terrain import terrain, convolve
    from .focal import focal
    from .indices import spectral_indices
    from .nodata import mask_background
    from .color import color_composite
    from .classification import classify_landcover, cluster_raster
    result = {}
    def add(key, label, function, output, tool, fields=None):
        result[key] = dict(label=label, function=function, output=output, tool=tool, fields=fields)
    def measures(source, quantity='area', unit=None, metric_crs=None):
        data=vector.read_file(source) if isinstance(source,(str,Path)) else source.copy()
        values=(vector.area(data,unit or 'ha',metric_crs=metric_crs) if quantity=='area'
                else vector.length(data,unit or 'm',metric_crs=metric_crs))
        if values.name in data:raise ValueError('Le champ de mesure existe déjà : '+values.name)
        data[values.name]=values
        return data
    for key,label in [('clip','Découpage vectoriel'),('buffer','Zone tampon'),('sjoin','Jointure spatiale'),
                      ('nearest','Jointure de proximité'),('dissolve','Dissolution'),('reproject','Reprojection vectorielle'),
                      ('make_valid','Réparation des géométries')]:
        add('vector.'+key,label,getattr(vector,key),'vector','vector')
    from functools import partial
    for mode,label in [('intersection','Intersection'),('union','Union'),('difference','Différence'),('symmetric_difference','Différence symétrique')]:
        add('vector.'+mode,label,partial(vector.overlay,how=mode),'vector','vector')
    add('vector.area','Superficies vectorielles',partial(measures,quantity='area'),'vector','vector')
    add('vector.length','Longueurs vectorielles',partial(measures,quantity='length'),'vector','vector')
    for key,label,kind in [('clip','Extraction par masque','raster'),('reproject','Reprojection raster','raster'),
                           ('reclassify','Reclassification','raster'),('zonal_stats','Statistiques zonales','vector'),
                           ('class_areas','Superficies par classe','table'),('change_matrix','Matrice de transition','table')]:
        add('raster.'+key,label,getattr(raster,key),kind,'raster')
    for key,label,function,tool in [('calculate','Algèbre raster',calculate,'calculator'),
        ('focal','Statistiques focales',focal,'focal'),('reduce','Statistiques multirasters',reduce_rasters,'temporal'),
        ('terrain','Dérivées du terrain',terrain,'terrain'),('convolve','Convolution',convolve,'terrain'),
        ('indices','Indices spectraux',spectral_indices,'indices'),('background','Masquage du fond',mask_background,'project'),
        ('composite','Composition colorée',color_composite,'composite'),
        ('classify','Classification supervisée',classify_landcover,'classification'),('cluster','Classification non supervisée',cluster_raster,'classification')]:
        add(key,label,function,'raster',tool)
    from .hydrology import hydrology
    from .routing import shortest_path
    from .catalogs import search_stac,download_stac
    from .imagery import prepare_imagery
    from .scenes import discover_scenes
    def preparation(sources,destination,band_order=('blue','green','red','nir'),aoi=None,target_crs=None,mask_clouds=True,allow_mixed_dates=False,progress=None,cancel=None):
        return prepare_imagery(discover_scenes(sources),destination,band_order=band_order,aoi=aoi,target_crs=target_crs,mask_clouds=mask_clouds,allow_mixed_dates=allow_mixed_dates,progress=progress,cancel=cancel).path
    add('prepare','Prétraitement multispectral',preparation,'raster','prepare')
    add('hydrology','Analyse hydrologique D8',hydrology,'raster','processing')
    add('routing','Plus court chemin',shortest_path,'vector','processing')
    add('stac.search','Recherche de scènes STAC',search_stac,'document','processing')
    add('stac.download','Téléchargement des scènes STAC',download_stac,'document','processing')
    return result


_ENGINE = {'workers':1,'block_size':512,'memory_limit_mb':512,'align':False,'resampling':'nearest','dtype':'float32','compression':'lzw'}
BLOCK_OPERATIONS={'calculate','indices','reduce','focal','terrain','convolve'}
CUDA_OPERATIONS={'calculate','indices','reduce'}
_HIDDEN = {'destination','overwrite','progress','cancel','stage','options','kwargs','how_fixed','quantity'}


def operation_catalog():
    """Machine-readable operator names, parameter defaults and output types."""
    rows=[]
    for key,spec in _catalog().items():
        parameters=[]
        for name,p in inspect.signature(spec['function']).parameters.items():
            if (name=='how' and key in {'vector.intersection','vector.union','vector.difference','vector.symmetric_difference'}) or name in _HIDDEN or p.kind in (p.VAR_POSITIONAL,p.VAR_KEYWORD):continue
            required=p.default is p.empty
            parameters.append(dict(name=name,required=required,default=None if required else json_value(p.default)))
        products=['primary']
        if key in BLOCK_OPERATIONS:
            for name,default in dict(execution='threads',scheduler_address=None).items():parameters.append(dict(name=name,required=False,default=default))
        if key in CUDA_OPERATIONS:parameters.append(dict(name='device',required=False,default='cpu'))
        if key=='hydrology':products+=['filled','direction','accumulation','streams','watersheds']
        if key=='classify':products+=['classification','confidence']
        if key=='classify':
            from .classification import fit_classifier
            present={p['name'] for p in parameters}
            for name,p in inspect.signature(fit_classifier).parameters.items():
                if name not in present and name not in _HIDDEN:parameters.append(dict(name=name,required=p.default is p.empty,default=None if p.default is p.empty else json_value(p.default)))
        rows.append(dict(id=key,label=spec['label'],tool=spec['tool'],output=spec['output'],parameters=parameters,products=products))
    return rows


def operation_spec(name):
    try:return next(row for row in operation_catalog() if row['id']==name)
    except StopIteration:raise ValueError('Opération non enregistrée : '+str(name)) from None


def validate_parameters(operation,parameters):
    spec=_catalog().get(operation)
    if spec is None:raise ValueError('Opération non enregistrée : '+str(operation))
    if not isinstance(parameters,dict):raise ValueError('Les paramètres doivent être un objet.')
    forbidden=set(parameters)&(_HIDDEN|{'function','backend','scheduler'})
    if forbidden:raise ValueError('Paramètres réservés : '+', '.join(sorted(forbidden)))
    signature=inspect.signature(spec['function'])
    allowed={p.name for p in signature.parameters.values() if p.kind not in (p.VAR_KEYWORD,p.VAR_POSITIONAL)}
    # **options only conveys the documented block-engine options, never arbitrary arguments.
    if 'options' in signature.parameters:allowed.update(_ENGINE)
    if operation in BLOCK_OPERATIONS:allowed.update({'execution','scheduler_address'})
    if operation in CUDA_OPERATIONS:allowed.add('device')
    if operation=='classify':
        from .classification import fit_classifier
        allowed.update(set(inspect.signature(fit_classifier).parameters)-_HIDDEN)
    if operation in {'vector.intersection','vector.union','vector.difference','vector.symmetric_difference'}:allowed.discard('how')
    unknown=set(parameters)-allowed
    if unknown:raise ValueError('Paramètres inconnus : '+', '.join(sorted(unknown)))
    supplied=dict(parameters)
    if operation=='classify' and supplied.get('model'):supplied.setdefault('training',None)
    if 'destination' in signature.parameters:supplied['destination']='output'
    try:signature.bind(**supplied)
    except TypeError as exc:raise ValueError(str(exc)) from None
    return spec


def _paths(value):
    if isinstance(value,(str,Path)) and not str(value).startswith('@'):
        try:
            path=Path(value)
            if path.is_file():yield path.resolve()
        except (OSError,ValueError):pass
    elif isinstance(value,dict):
        for item in value.values():yield from _paths(item)
    elif isinstance(value,(tuple,list)):
        for item in value:yield from _paths(item)


def execute_operation(operation,parameters,destination,*,workers=1,block_size=512,memory_limit_mb=512,execution='threads',scheduler_address=None,device='cpu',progress=None,cancel=None):
    """Run one registered operator and return a reopenable product record."""
    spec=validate_parameters(operation,parameters);_check_cancel(cancel)
    sources=list(_paths(parameters));destination=Path(destination).resolve()
    if any(p==destination or destination in p.parents for p in sources):
        raise ValueError('Le dossier de sortie contient une source.')
    with new_directory(destination) as work:
        import geopandas as gpd
        import pandas as pd
        p=dict(parameters);function=spec['function'];signature=inspect.signature(function)
        if operation in BLOCK_OPERATIONS:
            p.setdefault('execution',execution);p.setdefault('scheduler_address',scheduler_address)
        if operation in CUDA_OPERATIONS:p.setdefault('device',device)
        if operation=='raster.reclassify':p['mapping']={float(k):v for k,v in p['mapping'].items()}
        # JSON raster assets use [path, band], accepted by the array engine.
        if 'destination' in signature.parameters:
            p['destination']=work/'products' if operation in {'classify','cluster','hydrology','stac.download'} else work/'result.tif'
        for name,value in [('workers',workers),('block_size',block_size),('memory_limit_mb',memory_limit_mb)]:
            if 'options' in signature.parameters or name in signature.parameters or operation=='classify' and name=='workers':p.setdefault(name,value)
        if operation=='classify' and p.get('model'):p.setdefault('training',None)
        for name,value in [('progress',progress),('cancel',cancel)]:
            if name in signature.parameters or 'options' in signature.parameters:p[name]=value
        result=function(**p);_check_cancel(cancel)
        if isinstance(result,gpd.GeoDataFrame):
            primary=work/'result.gpkg';result.to_file(primary,driver='GPKG',index=False)
        elif isinstance(result,(pd.DataFrame,pd.Series)):
            primary=work/'result.csv';result.to_csv(primary,index=True)
        elif isinstance(result,dict):
            save_json(result,work/'result.json')
            primary=Path(result['path']) if spec['output']=='raster' and 'path' in result else work/'result.json'
        elif isinstance(result,(str,Path)):primary=Path(result)
        else:raise ValueError('Type de produit inattendu pour '+operation)
        if not primary.is_file():raise RuntimeError('Le traitement n’a pas créé son produit.')
        files=[str(destination/p.relative_to(work)) for p in sorted(work.rglob('*')) if p.is_file()]
        record=dict(schema='cartomize.operation.result.v1',operation=operation,
                    primary=str(destination/primary.relative_to(work)),kind=spec['output'],files=files)
        products={'primary':record['primary']}
        for path in sorted(work.rglob('*')):
            if path.is_file() and path.suffix.lower() in {'.tif','.gpkg','.csv'}:
                key=path.stem
                if key in products and products[key]!=str(destination/path.relative_to(work)):raise ValueError('Produits intermédiaires de même nom : '+key)
                products[key]=str(destination/path.relative_to(work))
        record['products']=products
        from .storage import relocate_products
        relocate_products(work,destination)
        save_json(record,work/'operation.json');_check_cancel(cancel)
    return record
