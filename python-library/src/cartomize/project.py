"""Project analysis, reversible preparation, symbology and reusable map plans."""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import re
import numpy as np
import rasterio
from matplotlib import colormaps
from matplotlib.colors import to_hex,is_color_like
from rasterio.windows import Window
from .composition import infer_role,compose_map
from .vector import analyze as analyze_vector
from .nodata import detect_background,mask_background,_windows
from .imagery import _check_cancel

RASTER_SUFFIXES={'.tif','.tiff','.vrt','.img','.jp2'}


def _class_metadata(src,overrides=None):
    raw=overrides
    if raw is None:
        text=src.tags().get('CARTOMIZE_CLASSES')
        if text:
            try:raw=json.loads(text)
            except json.JSONDecodeError:raise ValueError('Invalid CARTOMIZE_CLASSES JSON metadata.') from None
    result={}
    for key,item in (raw or {}).items():
        value=float(key)
        if not np.isfinite(value):raise ValueError('Class codes must be finite.')
        if isinstance(item,str):name,color=item,None
        elif isinstance(item,dict):name,color=item.get('label',str(key)),item.get('color')
        else:name,color=item
        if color is not None and not is_color_like(color):raise ValueError(f'Invalid class color: {color}')
        result[value]=(str(name),color)
    return result


def _raster_classes(source,overrides=None,*,cancel=None,max_classes=64):
    """Use exact bounded class counts, never sampled guesses about class labels."""
    counts=Counter()
    with rasterio.open(source) as src:
        known=_class_metadata(src,overrides)
        if src.count!=1:return None,known
        text=' '.join([Path(source).stem,*[v or '' for v in src.descriptions]]).casefold()
        continuous=src.tags().get('operation') in {'terrain','convolution','spectral_indices','focal','raster_reduction'} or bool(re.search(r'(^|[ _-])(dem|mnt|dtm|dsm|elevation|altitude|slope|pente|hillshade|ndvi|ndmi|evi)([ _-]|$)',text))
        if continuous and not known:return None,known
        for window in _windows(src,512):
            _check_cancel(cancel)
            data=np.ma.masked_invalid(src.read(1,window=window,masked=True)).compressed()
            if data.size and not np.all(data==np.round(data)):return None,known
            values,n=np.unique(data,return_counts=True);counts.update({float(v):int(k) for v,k in zip(values,n)})
            if len(counts)>max_classes:return None,known
        palette={}
        try:palette=src.colormap(1)
        except ValueError:pass
    colors=colormaps['tab20'].resampled(max(1,len(counts)))
    classes=[]
    for index,(value,count) in enumerate(sorted(counts.items())):
        label,color=known.get(value,(f'Classe {value:g}',None))
        if color is None:
            rgba=palette.get(int(value))
            color=to_hex(np.array(rgba[:3])/255) if rgba is not None else to_hex(colors(index))
        classes.append(dict(value=value,label=label,color=color,pixels=count,label_source='metadata_or_user' if value in known else 'code'))
    return classes,known


def analyze_project(layers,*,auto_background=True,progress=None,cancel=None):
    """Analyze files together; return diagnostics and proposed cartographic rules.

    A project here is a list of raster/vector files, not an APRX/QGZ document.
    Class names come from user metadata or remain neutral code labels.
    """
    layers=list(layers)
    if not layers:raise ValueError('Importer au moins une couche.')
    result=[];names=set()
    for number,item in enumerate(layers,1):
        _check_cancel(cancel);options=dict(item) if isinstance(item,dict) else {'data':item}
        source=Path(options['data']).expanduser().resolve()
        if not source.is_file():raise FileNotFoundError(source)
        name=options.get('name') or source.stem
        if name in names:name=f'{name} ({number})'
        names.add(name);kind=options.get('kind') or ('raster' if source.suffix.lower() in RASTER_SUFFIXES else 'vector')
        record=dict(source=str(source),name=name,kind=kind,options={})
        if kind=='raster':
            with rasterio.open(source) as src:
                from .raster import _band
                if src.crs is None:raise ValueError(f'Raster sans système de coordonnées : {name}')
                _band(src,options.get('band',1));known=_class_metadata(src,options.get('classes'))
            explicit=[float(v) for v in options.get('nodata_values',()) if v not in options.get('keep_values',())]
            if not all(np.isfinite(explicit)):raise ValueError('Les valeurs NoData supplémentaires doivent être finies.')
            keep=list(dict.fromkeys([*options.get('keep_values',()),*(v for v in known if v not in explicit)]))
            diagnostic=detect_background(source,keep_values=keep)
            border=diagnostic['automatic_border_values'] if auto_background else []
            record.update(diagnostic=diagnostic,border_values=border,nodata_values=explicit,keep_values=keep,
                          valid_footprint=str(Path(options['valid_footprint']).resolve()) if options.get('valid_footprint') else None,
                          supplied_classes={str(k):v for k,v in known.items()})
            record['options']=dict(role=options.get('role'),band=options.get('band',1),
                                   rgb=options.get('rgb','native' if diagnostic['native_rgb'] else None))
        elif kind=='vector':
            diagnostic=analyze_vector(source,name=name)
            types=tuple(diagnostic['geometry_types'])
            role=options.get('role') or infer_role(name,'vector',types)
            record.update(diagnostic=diagnostic)
            record['options']=dict(role=role,labels=options.get('labels') or diagnostic.get('label_field'),column=options.get('column'))
            if options.get('classes') is not None:record['options']['classes']=options['classes']
        else:raise ValueError('Types de couches : raster ou vector.')
        for key in ('alpha','cmap','color','legend','zorder','categorical','edgecolor','linewidth','markersize'):
            if key in options:record['options'][key]=options[key]
        result.append(record)
        if progress:progress(number,len(layers))
    crss=sorted(set(r['diagnostic']['crs'] for r in result))
    return dict(schema='cartomize.project.analysis.v1',layers=result,coordinate_systems=crss,
                reprojection_required=len(crss)>1,auto_background=bool(auto_background),
                limitations=['Undeclared backgrounds are inferred, not ground truth.',
                             'No land-cover class meaning is inferred from integer codes alone.',
                             'APRX/QGZ native project state is not read.'])


@dataclass
class PreparedProject:
    directory: Path
    manifest: Path
    layers: list
    report: dict
    def compose(self,**options):return compose_map(self.layers,**options)


def prepare_project(layers,destination,*,auto_background=True,progress=None,stage=None,cancel=None):
    """Analyze, apply masks in copies, derive classes and persist a reusable plan.

    A new directory is published only after complete success. Original source
    files are retained; files without additional masks are referenced directly.
    """
    destination=Path(destination).expanduser().resolve()
    if destination.exists():raise FileExistsError('Choisir un nouveau répertoire de préparation.')
    if stage:stage('Analyse du projet')
    report=analyze_project(layers,auto_background=auto_background,cancel=cancel,
        progress=lambda done,total:progress(int(done/total*25),100) if progress else None)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cartomize-project-',dir=destination.parent) as temporary:
        work=Path(temporary)/'project';work.mkdir();(work/'rasters').mkdir()
        total=len(report['layers'])
        for index,record in enumerate(report['layers']):
            _check_cancel(cancel);source=Path(record['source']);prepared=source
            if stage:stage(f"Préparation cartographique : {record['name']}")
            if record['kind']=='raster':
                if record['border_values'] or record['nodata_values'] or record.get('valid_footprint'):
                    relative=Path('rasters')/f'{index+1:03d}_{source.stem}.tif';prepared=work/relative
                    record['mask_result']=mask_background(source,prepared,border_values=record['border_values'],
                        nodata_values=record['nodata_values'],keep_values=record['keep_values'],valid_footprint=record.get('valid_footprint'),cancel=cancel,
                        progress=lambda done,count:progress(25+int(65*(index+done/count)/total),100) if progress else None)
                    if record['mask_result']['valid_pixels']==0:raise ValueError(f"Aucun pixel valide après masquage : {record['name']}")
                    record['mask_result']['path']=str(relative);record['prepared']=str(relative)
                else:
                    record['prepared']=str(source);record['mask_result']={'additional_border_masked':0,'additional_value_masked':0}
                classes,_=_raster_classes(prepared,record['supplied_classes'],cancel=cancel) if record['options'].get('categorical') is not False or record['supplied_classes'] else (None,{})
                record['classes']=classes
                if classes:
                    record['options']['classes']={str(c['value']):[c['label'],c['color']] for c in classes}
                    record['options']['role']=record['options'].get('role') or 'landcover'
                else:record['options']['role']=record['options'].get('role') or ('background' if record['options']['rgb'] else 'thematic')
            else:record['prepared']=str(source)
            if progress:progress(25+int(65*(index+1)/total),100)
        from . import __version__
        report.update(version=__version__,schema='cartomize.project.v1',sources_modified=False)
        (work/'project.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str,allow_nan=False)+'\n',encoding='utf-8')
        _check_cancel(cancel)
        if destination.exists():raise FileExistsError(destination)
        work.rename(destination)
    if progress:progress(100,100)
    return load_project(destination/'project.json')


def load_project(manifest,*,original_sources=False):
    """Reload Cartomize's own project plan; optionally restore original sources."""
    manifest=Path(manifest).resolve();report=json.loads(manifest.read_text(encoding='utf-8'))
    if report.get('schema')!='cartomize.project.v1':raise ValueError('Unsupported Cartomize project schema.')
    layers=[]
    for record in report['layers']:
        path=Path(record['source'] if original_sources else record['prepared'])
        if not path.is_absolute():path=manifest.parent/path
        options=dict(record['options'])
        if original_sources:options.pop('classes',None)
        elif options.get('classes'):options['classes']={float(k):tuple(v) for k,v in options['classes'].items()}
        layers.append(dict(data=path,name=record['name'],kind=record['kind'],**options))
    return PreparedProject(manifest.parent,manifest,layers,report)
