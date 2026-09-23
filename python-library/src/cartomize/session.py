"""Complete map/session documents, relative paths and portable project archives."""
from dataclasses import asdict,dataclass
from pathlib import Path
import hashlib
import json
import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
from .storage import json_value,read_json,save_json
from ._validation import output_path


def map_document(map_object):
    layers=[]
    for layer in map_object.layers:
        item={k:json_value(v) for k,v in vars(layer).items() if k not in {'data','style'}}
        # Role-specific path effects are rebuilt by Map.add_layer.
        item.update({k:json_value(v) for k,v in layer.style.items() if k!='path_effects'})
        if layer.kind=='vector':item['data']={'features':json.loads(layer.data.to_json())['features'],'crs':layer.data.crs.to_wkt()}
        else:item['data']=str(Path(layer.data).resolve())
        layers.append(item)
    return dict(schema='cartomize.map.v1',options=dict(title=map_object.title,subtitle=map_object.subtitle,credits=map_object.credits,
        crs=str(map_object.crs) if map_object.crs else None,template=map_object.plan.template_id if map_object.plan else None,
        format='A3' if max(map_object.width,map_object.height)>350 else 'A4',orientation='landscape' if map_object.width>map_object.height else 'portrait',
        auto_order=map_object.auto_order),layers=layers,extent=map_object.extent,
        plan=asdict(map_object.plan) if map_object.plan else None,
        frames={k:{**v,'crs':str(v['crs']) if v.get('crs') else None} for k,v in map_object.frames.items()},
        texts=map_object.texts,tables={k:json.loads(v.to_json(orient='split')) for k,v in map_object.tables.items()},
        charts=map_object.charts,legend=map_object.legend_enabled,scale=map_object.scale_enabled,north=map_object.north_enabled,
        sources=[str(p) for p in map_object._sources])


def map_from_document(document):
    from .mapping import Map
    if document.get('schema')!='cartomize.map.v1':raise ValueError('Document cartographique incompatible.')
    result=Map(**document['options'])
    if document.get('plan'):
        from ._core.layout_plan import LayoutPlan,PlannedItem
        plan=dict(document['plan']);plan['items']=tuple(PlannedItem(**i) for i in plan['items']);result.plan=LayoutPlan(**plan)
        result.width,result.height=result.plan.page_width_mm,result.plan.page_height_mm
    for item in document['layers']:
        options=dict(item);data=options.pop('data')
        if isinstance(data,dict):data=gpd.GeoDataFrame.from_features(data['features'],crs=data['crs']) if data['features'] else gpd.GeoDataFrame(geometry=[],crs=data['crs'])
        if options.get('classes'):options['classes']={(float(k) if options['kind']=='raster' else k):v for k,v in options['classes'].items()}
        if options['kind']=='vector' and options.get('column') and options.get('classes'):
            column=data[options['column']]
            if pd.api.types.is_numeric_dtype(column):options['classes']={float(k):v for k,v in options['classes'].items()}
        result.add_layer(data,**options)
    if document.get('extent'):result.set_extent(document['extent'])
    for key,config in document.get('frames',{}).items():result.set_frame(key,**config)
    result.texts=dict(document.get('texts',{}))
    for key,value in document.get('tables',{}).items():result.set_table(key,pd.DataFrame(**value))
    for key,(labels,values,color) in document.get('charts',{}).items():result.set_chart(key,labels,values,color=color)
    result.add_legend(document['legend']).add_scale_bar(document['scale']).add_north_arrow(document['north'])
    result._sources=[Path(p) for p in document.get('sources',[])];return result


def _walk(value,transform):
    if isinstance(value,dict):return {k:_walk(v,transform) for k,v in value.items()}
    if isinstance(value,list):return [_walk(v,transform) for v in value]
    if isinstance(value,str):return transform(value)
    return value


def _references(state):
    paths=set()
    def visit(value):
        if len(value)<4096 and '\n' not in value:
            try:
                path=Path(value).expanduser()
                if path.is_absolute() and path.exists():paths.add(path.resolve())
            except (OSError,ValueError):pass
        return value
    _walk(state,visit);return sorted(paths,key=str)


def save_session(state,path,*,portable=False,overwrite=False):
    """Persist all supplied UI/model state. Portable archives copy dependencies."""
    state=json_value(state);refs=_references(state);path=output_path(path,overwrite,[p for p in refs if p.is_file()])
    from . import __version__
    if not portable:
        mapping={str(p):os.path.relpath(p,path.parent) if p.drive==path.parent.drive else str(p) for p in refs}
        document=dict(schema='cartomize.session.v1',version=__version__,state=state,references=mapping)
        return save_json(document,path,overwrite=overwrite,sources=[p for p in refs if p.is_file()])
    # Follow Cartomize manifests, including their relative dependency paths.
    dependencies=set(refs);pending=[p for p in refs if p.is_file() and p.suffix=='.json'];documents={}
    while pending:
        source=pending.pop()
        if source in documents:continue
        try:document=read_json(source)
        except (ValueError,OSError):continue
        if not isinstance(document,dict) or not (str(document.get('schema','')).startswith('cartomize.') or document.get('stac_version') or document.get('type')=='FeatureCollection' and all(i.get('stac_version') for i in document.get('features',[]))):continue
        documents[source]=document
        def absolute(value):
            try:
                candidate=Path(value)
                if not candidate.is_absolute() and (source.parent/candidate).is_file():return str((source.parent/candidate).resolve())
            except (OSError,ValueError):pass
            return value
        document=_walk(document,absolute);documents[source]=document
        for item in _references(document):
            if item not in dependencies:
                dependencies.add(item)
                if item.is_file() and item.suffix=='.json':pending.append(item)
        if len(dependencies)>100000:raise ValueError('Trop de dépendances dans le projet.')
    refs=sorted(dependencies,key=str)
    input_dirs={Path(p).resolve() for p in state.get('input_directories',[])}
    fd,temporary=tempfile.mkstemp(prefix='.cartomize-project-',suffix='.cmz',dir=path.parent);os.close(fd)
    try:
        mapping={};entries={};directories=[]
        for source in refs:
            # A referenced output directory can contain this archive: never include it.
            key=hashlib.sha256(str(source).encode()).hexdigest()[:16]
            target=Path('assets')/key/source.name;mapping[str(source)]=target.as_posix()
            if source.is_dir():
                directories.append(target.as_posix()+'/')
                if source not in input_dirs:continue
                children=(p for p in source.rglob('*') if p.is_file())
                for child in children:
                    if child.resolve() not in {path,Path(temporary).resolve()}:entries[(target/child.relative_to(source)).as_posix()]=child
            else:
                entries[target.as_posix()]=source
                companions=list(source.parent.glob(source.stem+'.*')) if source.suffix.lower()=='.shp' else []
                companions += [Path(str(source)+s) for s in ('.msk','.aux.xml','.ovr')]
                if source.name=='model.json':companions.append(source.with_suffix('.npz'))
                for child in companions:
                    if child.is_file():entries[(target.parent/child.name).as_posix()]=child
        if len(entries)>100_000:raise ValueError('Le projet portable contient trop de fichiers.')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            for name in directories:archive.writestr(name,b'')
            for name,source in entries.items():
                if source in documents:
                    rewrite=_walk(documents[source],lambda value:os.path.relpath(mapping[value],Path(name).parent) if value in mapping else value)
                    archive.writestr(name,json.dumps(rewrite,ensure_ascii=False,allow_nan=False))
                else:archive.write(source,name)
            archive.writestr('project.json',json.dumps(dict(schema='cartomize.session.v1',version=__version__,state=state,references=mapping),ensure_ascii=False,allow_nan=False))
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)
    return path


@dataclass
class LoadedSession:
    state:dict
    missing:list
    directory:Path


def load_session(path,*,relocate=None,directory=None):
    path=Path(path).expanduser().resolve();root=path.parent;extracted=False
    if zipfile.is_zipfile(path):
        root=Path(directory) if directory else Path(tempfile.mkdtemp(prefix='cartomize-project-'))
        root.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            records=archive.infolist()
            if len(records)>100_000 or sum(i.file_size for i in records)>100*1024**3:raise ValueError('Archive de projet trop volumineuse.')
            for item in records:
                target=(root/item.filename).resolve()
                if not target.is_relative_to(root.resolve()) or (item.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('Chemin non autorisé dans le projet portable.')
                if target.exists():raise FileExistsError('Extraire le projet dans un répertoire vide.')
            archive.extractall(root)
        path=root/'project.json';extracted=True
    document=read_json(path)
    if document.get('schema')!='cartomize.session.v1':raise ValueError('Projet Cartomize incompatible.')
    mapping={};missing=[]
    for original,reference in document.get('references',{}).items():
        target=Path(reference)
        if not target.is_absolute():target=(root/target).resolve()
        for before,after in (relocate or {}).items():
            if Path(original).is_relative_to(Path(before)):target=Path(after)/Path(original).relative_to(before);break
        mapping[original]=str(target)
        if not target.exists():missing.append(str(target))
    if extracted:
        for item in root.rglob('*.json'):
            if item==path:continue
            try:child=read_json(item)
            except (ValueError,OSError):continue
            if not isinstance(child,dict) or not str(child.get('schema','')).startswith('cartomize.'):continue
            def resolve_child(value):
                try:
                    candidate=(item.parent/value).resolve()
                    if not Path(value).is_absolute() and candidate.is_relative_to(root.resolve()) and candidate.exists():return str(candidate)
                except (OSError,ValueError):pass
                return mapping.get(value,value)
            save_json(_walk(child,resolve_child),item,overwrite=True)
    state=_walk(document['state'],lambda value:mapping.get(value,value))
    return LoadedSession(state,missing,root)


def save_map(map_object,path,*,portable=False,overwrite=False):
    return save_session({'map':map_document(map_object)},path,portable=portable,overwrite=overwrite)


def load_map(path,**options):
    if not zipfile.is_zipfile(path):
        document=read_json(path)
        if document.get('schema')=='cartomize.map.v1':
            if options:raise ValueError('Les options de session nécessitent un projet enregistré avec Map.save().')
            return map_from_document(document)
    session=load_session(path,**options)
    if session.missing:raise FileNotFoundError('Sources absentes : '+', '.join(session.missing))
    return map_from_document(session.state['map'])
