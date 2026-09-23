"""Executable cartographic proposals with explicit dependencies and provenance."""
from pathlib import Path
from datetime import datetime,timezone
import json
import copy
import re
import rasterio
import numpy as np
from .assistant import assess_project
from .templates import list_templates,layout_plan
from .storage import save_json,read_json,new_directory,json_value
from .imagery import _check_cancel
from .project import prepare_project
from .session import save_map


def propose_layouts(goal='general',*,bounds=None,layer_count=1,classes=0,count=3):
    category={'landcover':'occupation_sol','administrative':'administrative'}.get(goal)
    aspect=(bounds[2]-bounds[0])/max(bounds[3]-bounds[1],1e-12) if bounds is not None else 1.4
    candidates=[]
    for template in list_templates():
        plan=layout_plan(template['id']);main=next(i for i in plan.map_items if i.item_id==plan.primary_map_id)
        distortion=abs(np.log(max(.01,aspect)/(main.width_mm/main.height_mm)))
        score=100-20*distortion-5*max(0,template['map_frames']-1)
        reasons=[]
        if category and template['category']==category:score+=40;reasons.append('Catégorie adaptée à l’objectif')
        if classes>12 and max(plan.page_width_mm,plan.page_height_mm)>350:score+=15;reasons.append('Format A3 pour une nomenclature détaillée')
        if layer_count>6 and template['map_frames']>1:score+=6;reasons.append('Cadres disponibles pour séparer le contexte et les détails')
        reasons.append('Rapport largeur/hauteur comparé à l’emprise')
        candidates.append(dict(**template,score=round(float(score),2),reasons=reasons))
    return sorted(candidates,key=lambda x:(-x['score'],x['id']))[:count]


def plan_cartography(inputs,*,goal='general',data_kind='layers',aoi=None,title='',credits='',
                     training=None,class_column='classe',classification=None,indices=(),template=None,
                     target_crs=None,repair=True,relations=True,atlas_zones=None,atlas_field=None,
                     allow_mixed_dates=False,layers=(),processing_steps=(),mask_clouds=True):
    """Build a serializable dependency graph without modifying input files."""
    if classification not in {None,'supervised','unsupervised'}:raise ValueError('Mode de classification inconnu.')
    assessment=assess_project(inputs,data_kind=data_kind,goal=goal,aoi=aoi)
    errors=[i for i in assessment['issues'] if i['severity']=='error' and not (repair and i['code']=='invalid_geometry')]
    if errors:raise ValueError('; '.join(i['message'] for i in errors))
    if layers:
        extra=assess_project(layers,data_kind='layers',goal=goal,aoi=aoi)
        failures=[i for i in extra['issues'] if i['severity']=='error' and not (repair and i['code']=='invalid_geometry')]
        if failures:raise ValueError('; '.join(i['message'] for i in failures))
        assessment['layers'].extend(extra['layers'])
    nodes=[];layers=[];scientific=None
    def add(operation,parameters,requires=()):
        ident=f'step_{len(nodes)+1:02d}'
        while any(n['id']==ident for n in nodes):ident+='_'
        nodes.append(dict(id=ident,operation=operation,parameters=parameters,requires=list(requires)));return ident
    if data_kind=='scenes':
        from .indices import get_index
        bands=list(dict.fromkeys(['blue','green','red','nir']+[b for index in indices for b in get_index(index).bands]))
        scientific=add('prepare',dict(sources=assessment['inputs'],aoi=aoi,crs=target_crs,allow_mixed_dates=allow_mixed_dates,bands=bands,mask_clouds=mask_clouds))
        rgb=add('composite',dict(source='@'+scientific),[scientific]);layers.append(dict(data='@'+rgb,role='background',rgb='native',name='Image satellite'))
    for record in assessment['layers']:
        item=dict(record['options'],data=record['source'],name=record['name'],kind=record['kind'])
        if record['kind']=='vector' and record['diagnostic']['invalid_geometries']:
            node=add('repair',dict(source=record['source']));item['data']='@'+node
        if record['kind']=='raster' and record['diagnostic']['bands']>1 and not record['diagnostic']['native_rgb']:
            if scientific is None:scientific=record['source']
            descriptions={str(n).casefold() for n in record['diagnostic'].get('descriptions',[]) if n}
            if {'red','green','blue'}<=descriptions:
                node=add('composite',dict(source=record['source']));item.update(data='@'+node,rgb='native',role='background')
        layers.append(item)
    if classification:
        if scientific is None:raise ValueError('Ajouter un raster multispectral ou des scènes pour la classification.')
        if classification=='supervised' and not training:raise ValueError('La classification supervisée nécessite des échantillons de référence.')
        reference='@'+scientific if scientific.startswith('step_') else scientific
        node=add('classify' if classification=='supervised' else 'cluster',dict(source=reference,training=str(training) if training else None,class_column=class_column),[scientific] if scientific.startswith('step_') else [])
        layers.append(dict(data='@'+node,role='landcover',name='Occupation du sol' if classification=='supervised' else 'Groupes spectraux'))
    if indices:
        if scientific is None:raise ValueError('Ajouter un raster scientifique pour les indices.')
        node=add('indices',dict(source='@'+scientific if scientific.startswith('step_') else scientific,indices=list(indices)),[scientific] if scientific.startswith('step_') else [])
        # Indices remain analytical products; do not obscure the chosen thematic map.
    # User steps are placed after scientific preparation and before cartography.
    # Stable explicit identifiers allow later operators to consume earlier products.
    from .processing import validate_parameters,operation_spec
    used={n['id'] for n in nodes}
    def substitute(value):
        if isinstance(value,str) and value=='@scientific':
            if scientific is None:raise ValueError('Aucun raster scientifique disponible.')
            return '@'+scientific if scientific.startswith('step_') else scientific
        if isinstance(value,dict):return {k:substitute(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [substitute(v) for v in value]
        return value
    for index,step in enumerate(processing_steps):
        ident=step.get('id',f'process_{index+1:02d}')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',ident) or ident in used:raise ValueError('Identifiant de traitement invalide ou dupliqué : '+str(ident))
        operation=step['operation'];parameters=substitute(step['parameters'])
        validate_parameters(operation,parameters)
        refs=reference_ids(parameters)
        if not refs<=used:raise ValueError('Référence absente ou placée après son utilisation : '+', '.join(sorted(refs-used)))
        nodes.append(dict(id=ident,operation='process',parameters=dict(operator=operation,arguments=parameters),requires=sorted(refs)))
        used.add(ident)
        if step.get('map_layer') is not None:
            spec=operation_spec(operation)
            if spec['output'] not in {'raster','vector'}:raise ValueError('Un tableau ne peut pas être ajouté comme couche.')
            layer=dict(step['map_layer']);product=layer.pop('product',None);layer.update(data='@'+ident+(':'+product if product else ''),kind=spec['output']);layer.setdefault('name',spec['label'])
            layers.append(layer)
    requirements=[n['id'] for n in nodes]
    preparation=add('project',dict(layers=layers),requirements)
    if relations:add('relations',dict(layers='@'+preparation),[preparation])
    bounds=None
    for record in assessment['layers']:
        if record['diagnostic'].get('bounds'):bounds=record['diagnostic']['bounds'];break
    proposals=propose_layouts(goal,bounds=bounds,layer_count=len(layers))
    chosen=template or proposals[0]['id']
    mapping=add('map',dict(layers='@'+preparation,aoi=aoi,title=title,credits=credits,crs=target_crs,template=chosen),[preparation])
    if goal=='atlas':
        if not atlas_zones or not atlas_field:raise ValueError('Indiquer la couche d’index et le champ des noms pour l’atlas.')
        add('atlas',dict(map='@'+mapping,zones=str(atlas_zones),field=atlas_field),[mapping])
    return json_value(dict(schema='cartomize.automation.v1',goal=goal,inputs=assessment['inputs'],assessment=assessment,
                            nodes=nodes,proposals=proposals,classification=classification))


def reference_ids(value):
    if isinstance(value,str) and value.startswith('@'):return {value[1:].partition(':')[0]}
    if isinstance(value,dict):return set().union(*(reference_ids(v) for v in value.values()))
    if isinstance(value,(list,tuple)):return set().union(*(reference_ids(v) for v in value))
    return set()


def validate_plan(plan):
    """Validate the complete graph before a treatment can write anything."""
    from .processing import validate_parameters
    if plan.get('schema')!='cartomize.automation.v1':raise ValueError('Plan de traitement incompatible.')
    allowed={'prepare','repair','composite','project','indices','classify','cluster','relations','map','atlas','process'}
    nodes=plan.get('nodes',[])
    if not nodes or len(nodes)>5000:raise ValueError('Le plan doit contenir entre 1 et 5 000 étapes.')
    ids=set()
    for node in nodes:
        ident=node.get('id','');requires=node.get('requires',[]);parameters=node.get('parameters',{})
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',ident):raise ValueError('Identifiant de traitement invalide.')
        if ident in ids or not set(requires)<=ids or node.get('operation') not in allowed:raise ValueError('Dépendances ou opération du plan invalides.')
        refs=reference_ids(parameters)
        if not refs<=set(requires):raise ValueError('Chaque résultat utilisé doit figurer dans les dépendances : '+ident)
        if node['operation']=='process':validate_parameters(parameters['operator'],parameters['arguments'])
        ids.add(ident)
    return plan


def processing_plan(steps):
    """Build a processing-only graph; inputs may refer to @previous_step."""
    nodes=[]
    for step in steps:
        parameters=dict(operator=step['operation'],arguments=step['parameters'])
        nodes.append(dict(id=step['id'],operation='process',parameters=parameters,requires=sorted(reference_ids(parameters))))
    return validate_plan(dict(schema='cartomize.automation.v1',nodes=nodes))


def run_plan(plan,destination,*,dpi=150,formats=('pdf','png'),workers=1,block_size=512,memory_limit_mb=512,execution='threads',scheduler_address=None,device='cpu',progress=None,stage=None,cancel=None):
    import cartomize as cm
    if isinstance(plan,(str,Path)):plan=read_json(plan)
    validate_plan(plan)
    if not formats or any(f not in {'pdf','png','svg'} for f in formats):raise ValueError('Formats : PDF, PNG ou SVG.')
    nodes=plan['nodes']
    results={};products={};assets=[];ledger=[];mapping=None;destination=Path(destination).resolve()
    def resolve(value):
        if isinstance(value,str) and value.startswith('@'):
            key,sep,product=value[1:].partition(':')
            if key not in results:raise ValueError('Résultat requis absent : '+value)
            if sep:
                if product not in products.get(key,{}):raise ValueError('Produit intermédiaire absent : '+value)
                return products[key][product]
            return results[key]
        if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
        if isinstance(value,list):return [resolve(v) for v in value]
        return value
    with new_directory(destination) as work:
        for number,node in enumerate(nodes):
            _check_cancel(cancel);op=node['operation'];ident=node['id'];parameters=resolve(node['parameters']);start=datetime.now(timezone.utc).isoformat()
            if stage:stage({'prepare':'Prétraitement multispectral','repair':'Réparation des géométries','project':'Analyse du projet','composite':'Composition colorée','classify':'Classification supervisée','cluster':'Classification non supervisée','indices':'Indices spectraux','relations':'Relations spatiales','map':'Mise en page','atlas':'Atlas cartographique','process':'Traitement enregistré'}[op])
            callback=lambda done,total:progress(number*100+int(done/max(1,total)*100),len(nodes)*100) if progress else None
            if op=='process':
                from .processing import execute_operation,operation_spec
                spec=operation_spec(parameters['operator'])
                if stage:stage(spec['label'])
                product=execute_operation(parameters['operator'],parameters['arguments'],work/ident,workers=workers,block_size=block_size,memory_limit_mb=memory_limit_mb,execution=execution,scheduler_address=scheduler_address,device=device,progress=callback,cancel=cancel)
                result=product['primary'];products[ident]=product['products']
                if product['kind'] in {'vector','raster'}:assets.append(dict(data=result,kind=product['kind'],name=spec['label']))
            elif op=='prepare':
                result=cm.prepare_imagery(cm.discover_scenes(parameters['sources']),work/f'{ident}.tif',aoi=parameters['aoi'],target_crs=parameters['crs'],
                    band_order=parameters.get('bands',['blue','green','red','nir']),mask_clouds=parameters.get('mask_clouds',True),allow_mixed_dates=parameters['allow_mixed_dates'],progress=callback,cancel=cancel).path
                assets.append(dict(data=result,kind='raster',name='Multibande scientifique'))
            elif op=='repair':
                result=work/f'{ident}.gpkg';cm.make_valid(parameters['source']).to_file(result,driver='GPKG',index=False)
                assets.append(dict(data=result,kind='vector'))
            elif op=='composite':
                result=cm.color_composite(parameters['source'],work/f'{ident}.tif',progress=callback,cancel=cancel)
                assets.append(dict(data=result,kind='raster',rgb='native',role='background'))
            elif op=='indices':
                result=cm.spectral_indices(parameters['source'],work/f'{ident}.tif',parameters['indices'],workers=workers,block_size=block_size,memory_limit_mb=memory_limit_mb,execution=execution,scheduler_address=scheduler_address,device=device,progress=callback,cancel=cancel)
                assets.append(dict(data=result,kind='raster'))
            elif op in {'classify','cluster'}:
                if op=='classify':result=cm.classify_landcover(parameters['source'],parameters['training'],work/ident,class_column=parameters['class_column'],workers=workers,block_size=min(block_size,1024),progress=callback,cancel=cancel)
                else:result=cm.cluster_raster(parameters['source'],work/ident,progress=callback,cancel=cancel)
                assets.append(dict(data=result,kind='raster',role='landcover',report=str(Path(result).parent/('classification.json' if op=='classify' else 'clustering.json')),**({'model':str(Path(result).parent/'model/model.json')} if op=='classify' else {})))
            elif op=='project':
                prepared=prepare_project(parameters['layers'],work/ident,progress=callback,cancel=cancel);result=prepared.layers;assets.extend(result)
            elif op=='relations':
                result=cm.analyze_relations(parameters['layers'],progress=callback,cancel=cancel);save_json(result,work/'relations.json')
            elif op=='map':
                from .cartographic_rules import complete_map,desktop_map_config
                mapping=cm.compose_map(**parameters);complete_map(mapping)
                ui_config=desktop_map_config(mapping,parameters['layers'],work)
                for fmt in formats:_check_cancel(cancel);mapping.export(work/f'carte.{fmt}',dpi=dpi)
                result=mapping
            elif op=='atlas':result=cm.atlas(parameters['map'],parameters['zones'],work/'atlas',name_column=parameters['field'],format=formats[0],dpi=dpi,progress=callback,cancel=cancel)
            results[ident]=result;ledger.append(dict(id=ident,operation=op,status='completed',started=start,finished=datetime.now(timezone.utc).isoformat()))
            if progress:progress((number+1)*100,len(nodes)*100)
        def publish(value):
            if isinstance(value,Path):value=str(value)
            if isinstance(value,str) and value.startswith(str(work)):return str(destination)+value[len(str(work)):]
            if isinstance(value,dict):return {k:publish(v) for k,v in value.items()}
            if isinstance(value,(list,tuple)):return [publish(v) for v in value]
            return value
        from .storage import relocate_products
        relocate_products(work,destination)
        if mapping is not None:
            from .session import map_document
            document=publish(map_document(mapping));save_json(document,work/'map.json')
        record=publish(dict(schema='cartomize.automation.result.v1',plan=plan,steps=ledger,layers=assets,
                    results={key:str(value) for key,value in results.items() if isinstance(value,(str,Path))},products=products,map_file=str(work/'map.json') if mapping else None,map_config=ui_config if mapping else None,
                    outputs=[str(work/f'carte.{fmt}') for fmt in formats] if mapping else []))
        save_json(record,work/'automation.json');_check_cancel(cancel)
    return destination/'automation.json'
