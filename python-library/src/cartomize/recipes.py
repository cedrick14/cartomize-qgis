"""Reusable map recipes, legacy migration and transactional batch production."""
from copy import deepcopy
from pathlib import Path
import re
import pandas as pd
from .storage import save_json,read_json,json_value,new_directory
from .imagery import _check_cancel


def safe_name(value):
    value=str(value).strip()
    if not value or value in {'.','..'} or len(value)>100 or re.search(r'[<>:"/\\|?*\x00-\x1f]',value) or value.endswith(('.', ' ')) or value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'{p}{n}' for p in ('COM','LPT') for n in range(1,10)]}:
        raise ValueError('Nom de résultat invalide : '+value)
    return value


def map_from_config(config,*,complete=False):
    import cartomize as cm
    from .cartographic_rules import complete_map
    settings=config.get('layout',{});options=dict(config.get('options',{}))
    options.update({k:settings[k] for k in ('template','format','orientation') if k in settings})
    layers=deepcopy(config['layers'])
    if config.get('rgb'):
        for layer in layers:
            if isinstance(layer,dict) and Path(str(layer['data'])).suffix.lower() in {'.tif','.tiff','.jp2','.vrt','.img'}:layer.setdefault('rgb',config['rgb'])
    result=cm.compose_map(layers,aoi=config.get('aoi'),**options)
    result.add_legend(settings.get('legend',True)).add_scale_bar(settings.get('scale',True)).add_north_arrow(settings.get('north',True))
    for item in settings.get('items',[]):result.set_item(item['id'],**{k:v for k,v in item.items() if k!='id'})
    for frame in settings.get('frames',[]):result.set_frame(**frame)
    for item in settings.get('elements',[]):
        if item['kind']=='text':result.set_text(item['id'],item['content'])
        else:
            table=pd.read_csv(item['content'])
            if item['kind']=='table':result.set_table(item['id'],table)
            else:result.set_chart(item['id'],table[item['labels']],pd.to_numeric(table[item['values']],errors='raise'))
    if complete:complete_map(result)
    return result


def save_recipe(map_or_config,path,*,overwrite=False):
    from .mapping import Map
    from .session import map_document
    body={'map':map_document(map_or_config)} if isinstance(map_or_config,Map) else {'config':json_value(map_or_config)}
    from .session import _references
    return save_json(dict(schema='cartomize.recipe.v1',**body),path,overwrite=overwrite,sources=[p for p in _references(body) if p.is_file()])


def load_recipe(path,*,bindings=None):
    document=read_json(path) if isinstance(path,(str,Path)) else deepcopy(path)
    if document.get('schema')=='cartomize.recipe.v1':return document
    if document.get('schema_version')!=1 or not ('variant' in document or 'layout' in document):raise ValueError('Recette incompatible.')
    settings=document.get('layout') or document.get('variant') or {};bindings=bindings or {}
    if settings.get('pagx_path'):raise ValueError('Cette recette utilise un PAGX : ouvrir le projet avec le moteur ArcGIS Pro.')
    ids=document.get('layer_ids') or document.get('layer_names') or list(bindings)
    names=document.get('layer_names',[]);layers=[]
    for i,key in enumerate(ids):
        name=names[i] if i<len(names) else key;source=bindings.get(key,bindings.get(name))
        if source is None:raise ValueError('Associer un fichier à la couche de la recette : '+str(name))
        layer={'data':str(source)} if not isinstance(source,dict) else dict(source)
        layer.setdefault('name',name);layers.append(layer)
    if not layers:raise ValueError('La recette doit contenir des couches associées à des fichiers.')
    layout=dict(template=settings.get('template_id'),format='A4',orientation='landscape',legend=True,scale=True,north=True,frames=[],elements=[])
    result=dict(schema='cartomize.recipe.v1',config=dict(layers=layers,options=dict(title=settings.get('title',''),subtitle=settings.get('subtitle',''),credits=settings.get('credits',document.get('sources',''))),layout=layout),migration=dict(original_schema=document.get('schema','cartomize.qgis.recipe/v1'),original=document,
        notes=['Les identifiants SIG sont associés explicitement aux fichiers. La mise en page est reconstruite par le moteur Python ; les réglages propres au moteur SIG restent dans la recette originale.']))
    return result


def _substitute(value,variables):
    if isinstance(value,dict):return {k:_substitute(v,variables) for k,v in value.items()}
    if isinstance(value,list):return [_substitute(v,variables) for v in value]
    if isinstance(value,str):
        def replace(match):
            key=match.group(1)
            if key not in variables:raise ValueError('Variable de recette absente : '+key)
            return str(variables[key])
        return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',replace,value)
    return value


def instantiate_recipe(recipe,*,variables=None,bindings=None,title=None,subtitle=None,credits=None):
    from .session import map_from_document
    doc=_substitute(load_recipe(recipe,bindings=bindings),variables or {})
    body=doc.get('map') or doc.get('config')
    for index,layer in enumerate(body['layers']):
        choices=[str(index),layer.get('name',''),str(layer.get('data',''))]
        for key in choices:
            if key in (bindings or {}):
                value=bindings[key]
                if isinstance(value,dict):layer.update(value)
                else:layer['data']=str(value)
                break
    options=body['options']
    for key,value in [('title',title),('subtitle',subtitle),('credits',credits)]:
        if value is not None:options[key]=value
    return map_from_document(body) if 'map' in doc else map_from_config(body,complete=True)


def run_recipe(recipe,destination,*,variables=None,bindings=None,formats=('pdf','png'),dpi=150,cancel=None,progress=None):
    if not formats or any(f not in {'pdf','png','svg'} for f in formats):raise ValueError('Formats : PDF, PNG ou SVG.')
    mapping=instantiate_recipe(recipe,variables=variables,bindings=bindings);destination=Path(destination).resolve()
    with new_directory(destination) as work:
        for i,fmt in enumerate(formats,1):
            _check_cancel(cancel);mapping.export(work/f'carte.{fmt}',dpi=dpi)
            if progress:progress(i,len(formats))
        mapping.save(work/'carte.cartomize.json');save_json(dict(schema='cartomize.recipe.result.v1',outputs=[str(destination/f'carte.{f}') for f in formats]),work/'recipe-result.json')
    return destination/'recipe-result.json'


def run_batch(manifest,destination=None,*,bindings=None,reviewed=False,continue_on_error=False,cancel=None,progress=None,stage=None):
    root=Path(manifest).resolve().parent if isinstance(manifest,(str,Path)) else Path.cwd()
    document=read_json(manifest) if isinstance(manifest,(str,Path)) else deepcopy(manifest)
    if document.get('schema') not in {None,'cartomize.batch.v1'} or document.get('schema_version',1)!=1:raise ValueError('Manifeste de production incompatible.')
    if document.get('require_human_validation',False) and not reviewed:raise ValueError('Le manifeste exige un plan vérifié avant exécution.')
    recipe=document.get('recipe') or document.get('recipe_path')
    if isinstance(recipe,str):recipe=str((root/recipe).resolve())
    jobs=document.get('jobs',[])
    if not 1<=len(jobs)<=5000:raise ValueError('Le manifeste doit contenir 1 à 5 000 cartes.')
    names=[safe_name(job.get('output_name') or job.get('job_id') or str(i+1)) for i,job in enumerate(jobs)]
    if len(set(n.casefold() for n in names))!=len(names):raise ValueError('Les noms de sortie doivent être uniques.')
    if destination is None and not document.get('output_directory'):raise ValueError('Indiquer le répertoire de sortie.')
    destination=Path(destination or root/document['output_directory']).resolve();ledger=[]
    with new_directory(destination) as work:
        for i,(job,name) in enumerate(zip(jobs,names)):
            _check_cancel(cancel)
            if stage:stage('Mise en page : '+name)
            try:
                formats=job.get('output_formats',['pdf']);formats=[f.lower().lstrip('.') for f in formats]
                if not formats or any(f not in {'pdf','png','svg'} for f in formats):raise ValueError('Formats : PDF, PNG ou SVG.')
                associated=dict(bindings or {});associated.update(job.get('layer_bindings',{}))
                associated={k:str((root/v).resolve()) if isinstance(v,str) else v for k,v in associated.items()}
                mapping=instantiate_recipe(recipe,variables=job.get('variables',{}),bindings=associated,title=job.get('title'),subtitle=job.get('subtitle'),credits=job.get('sources'))
                with new_directory(work/name) as target:
                    for fmt in formats:_check_cancel(cancel);mapping.export(target/f'{name}.{fmt}',dpi=document.get('dpi',150))
                    if document.get('keep_layouts',True):save_json(__import__('cartomize.session',fromlist=['map_document']).map_document(mapping),target/'map.json')
                ledger.append(dict(job_id=job.get('job_id',name),status='completed',outputs=[str(destination/name/f'{name}.{f}') for f in formats]))
            except Exception as exc:
                from .algebra import ProcessingCancelled
                if isinstance(exc,ProcessingCancelled) or not continue_on_error:raise
                ledger.append(dict(job_id=job.get('job_id',name),status='failed',error=str(exc)))
            if progress:progress(i+1,len(jobs))
        save_json(dict(schema='cartomize.batch.result.v1',jobs=ledger,complete=all(j['status']=='completed' for j in ledger)),work/'batch.json')
    return destination/'batch.json'
