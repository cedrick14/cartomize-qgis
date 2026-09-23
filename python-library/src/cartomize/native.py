"""Optional native project exchange through an installed GIS Python runtime."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from .storage import read_json,save_json
from ._validation import output_path
from .imagery import _check_cancel


def inspect_qgis_project(path):
    """Read local layer references from QGS/QGZ without executing project code."""
    path=Path(path).resolve()
    if path.suffix.lower()=='.qgz':
        with zipfile.ZipFile(path) as archive:
            names=[i for i in archive.infolist() if i.filename.endswith('.qgs')]
            if len(names)!=1 or names[0].file_size>50*1024**2:raise ValueError('Archive QGZ invalide ou trop volumineuse.')
            text=archive.read(names[0])
    else:
        if path.stat().st_size>50*1024**2:raise ValueError('Projet QGS trop volumineux.')
        text=path.read_bytes()
    if b'<!ENTITY' in text.upper():raise ValueError('Entités XML non autorisées.')
    root=ET.fromstring(text);layers=[]
    visibility={};order=[]
    def walk(node,visible=True):
        visible=visible and node.get('checked')!='Qt::Unchecked'
        if node.tag=='layer-tree-layer':visibility[node.get('id')]=visible;order.append(node.get('id'))
        for child in node:
            if child.tag in {'layer-tree-group','layer-tree-layer'}:walk(child,visible)
    tree=root.find('layer-tree-group')
    if tree is not None:walk(tree)
    custom=root.find('./layer-tree-canvas/custom-order')
    if custom is not None and custom.get('enabled')=='1':order=[i.text for i in custom.findall('item')]
    for element in root.findall('./projectlayers/maplayer'):
        source=element.findtext('datasource','');provider=element.findtext('provider','');ident=element.findtext('id','')
        local=None
        if provider in {'ogr','gdal'} and '://' not in source:
            raw=source.split('|')[0];candidate=Path(raw)
            if not candidate.is_absolute():candidate=path.parent/candidate
            if candidate.is_file():local=str(candidate.resolve())
        record=dict(id=ident,name=element.findtext('layername',''),kind=element.get('type'),provider=provider,source=local or source,local=bool(local),visible=visibility.get(ident,True),crs=element.findtext('./srs/spatialrefsys/authid',''))
        if '|' in source:record['provider_options']=source.partition('|')[2]
        renderer=element.find('renderer-v2')
        if renderer is not None:record['renderer']=renderer.get('type');record['column']=renderer.get('attr')
        from .native_styles import layer_style
        record['options'],record['transfer_warnings']=layer_style(element)
        record['options']['zorder']=len(order)-order.index(ident) if ident in order else len(layers)+1
        layers.append(record)
    return dict(schema='cartomize.native.inventory.v1',engine='qgis',project=str(path),layers=layers,layouts=[dict(name=i.get('name','')) for i in root.findall('./Layouts/Layout')],mode='xml_inventory',note='Inventaire des références locales. Le rendu et les mises en page natifs nécessitent le moteur QGIS.')


def native_project(project,*,engine=None,python=None,action='inspect',destination=None,layout=None,
                   texts=None,extents=None,template=None,prefix=None,dpi=150,timeout=600,cancel=None):
    """Inspect/export/copy an APRX or QGIS project in its own GIS runtime.

    The source project is never saved in place. Native styles remain handled
    by their original engine. Requires ArcGIS Pro/ArcPy or QGIS/PyQGIS.
    """
    project=Path(project).resolve();engine=engine or ('arcgis' if project.suffix.lower()=='.aprx' else 'qgis')
    if action=='import':return import_native_project(project,destination,engine=engine,python=python,cancel=cancel)
    if engine not in {'arcgis','qgis'} or action not in {'inspect','export','copy'}:raise ValueError('Moteur ou opération native invalide.')
    if not project.is_file():raise FileNotFoundError(project)
    if python is None and action=='inspect' and engine=='qgis':return inspect_qgis_project(project)
    if not python:raise ValueError('Sélectionner le Python du moteur SIG installé (ArcGIS Pro ou QGIS).')
    executable=Path(python).resolve()
    if not executable.is_file():raise FileNotFoundError('Interpréteur Python SIG absent : '+str(executable))
    if not 72<=dpi<=1200 or not 1<=timeout<=86400:raise ValueError('Résolution ou délai hors limites.')
    final=None
    if action!='inspect':
        if not destination:raise ValueError('Indiquer un nouveau fichier de sortie.')
        final=output_path(destination,False,[project])
        formats={'copy':{'.aprx'} if engine=='arcgis' else {'.qgs','.qgz'},'export':{'.pdf','.png','.svg','.pagx'} if engine=='arcgis' else {'.pdf','.png','.svg','.qpt'}}
        if final.suffix.lower() not in formats[action]:raise ValueError('Extension incompatible avec le moteur et l’opération.')
    with tempfile.TemporaryDirectory(prefix='cartomize-native-',dir=final.parent if final else None) as directory:
        work=Path(directory);target=work/f'project{final.suffix}' if final else None
        request=dict(project=str(project),engine=engine,action=action,destination=str(target) if target else None,layout=layout,texts=texts or {},extents=extents or {},template=str(Path(template).resolve()) if template else None,prefix=prefix,dpi=dpi)
        save_json(request,work/'request.json');script=Path(__file__).with_name('_native_worker.py');started=time.monotonic()
        environment=os.environ.copy();environment.setdefault('QT_QPA_PLATFORM','offscreen')
        # Do not use shell=True: executable and every argument are distinct.
        with open(work/'runtime.log','w',encoding='utf-8') as log:
            process=subprocess.Popen([str(executable),str(script),str(work/'request.json'),str(work/'response.json')],stdout=log,stderr=log,env=environment)
            try:
                while process.poll() is None:
                    _check_cancel(cancel)
                    if time.monotonic()-started>timeout:raise TimeoutError('Délai dépassé dans le moteur SIG.')
                    time.sleep(.05)
            except BaseException:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                raise
        if not (work/'response.json').exists():raise RuntimeError('Le moteur SIG n’a pas répondu. Vérifier son environnement Python. '+(work/'runtime.log').read_text(encoding='utf-8',errors='replace')[-1500:])
        result=read_json(work/'response.json')
        if not result.get('ok'):raise RuntimeError(result.get('error','Échec du moteur SIG.'))
        if process.returncode:raise RuntimeError('Le moteur SIG a quitté en erreur.')
        if action=='inspect' and engine=='qgis':
            from .native_styles import layer_style
            for layer in result['result'].get('layers',[]):
                xml=layer.pop('style_xml',None)
                if xml:
                    layer['options'],layer['transfer_warnings']=layer_style(ET.fromstring(xml))
                    layer['options']['zorder']=layer.pop('zorder',0)
                source=layer.get('source','')
                if '|' in source:
                    layer['source'],_,layer['provider_options']=source.partition('|')
        if final:
            _check_cancel(cancel)
            if not target.is_file():raise RuntimeError('Le moteur SIG n’a pas produit le fichier attendu.')
            # Recheck immediately before publication; an existing file is never replaced.
            with open(final,'xb') as dst,open(target,'rb') as src:
                import shutil
                try:shutil.copyfileobj(src,dst)
                except BaseException:dst.close();final.unlink(missing_ok=True);raise
            result['result']['output']=str(final)
        return result['result']



def import_native_project(project,destination,*,engine=None,python=None,cancel=None):
    """Materialize supported visible native layers and persist their styles.

    Unsupported renderers/providers are enumerated in transfer_warnings. This
    is a documented translation, while native copy/export retains native objects.
    """
    import geopandas as gpd
    from .storage import new_directory
    from .session import map_document
    from .composition import compose_map
    if not destination:raise ValueError('Indiquer un nouveau dossier pour le projet importé.')
    inventory=native_project(project,engine=engine,python=python,action='inspect',cancel=cancel)
    destination=Path(destination).resolve();layers=[];warnings=[]
    with new_directory(destination) as work:
        for i,layer in enumerate(inventory.get('layers',[])):
            _check_cancel(cancel)
            if not layer.get('visible',True):continue
            name=layer['name'];source=layer.get('source');options=dict(layer.get('options',{}))
            warnings.extend(name+' : '+w for w in layer.get('transfer_warnings',[]))
            if not source or '://' in source or not Path(source.split('|')[0]).is_file():
                warnings.append(name+' : source non locale ou inaccessible.');continue
            source=Path(source.split('|')[0]);provider_options=layer.get('provider_options','')
            kind=layer.get('kind','vector')
            if kind=='raster':
                if provider_options:warnings.append(name+' : sous-jeu raster nécessitant le moteur natif.');continue
                data=source
            elif kind=='vector':
                kwargs={};unsupported=False
                for item in provider_options.split('|') if provider_options else []:
                    key,sep,value=item.partition('=')
                    if key=='layername' and sep:kwargs['layer']=value
                    elif key=='layerid' and sep:kwargs['layer']=int(value)
                    else:unsupported=True
                if unsupported:warnings.append(name+' : filtre fournisseur nécessitant le moteur natif.');continue
                data=work/f'layer_{i:03d}.gpkg';gpd.read_file(source,**kwargs).to_file(data,driver='GPKG',index=False)
            else:continue
            layers.append(dict(data=str(data),name=name,kind=kind,**options))
        if not layers:raise ValueError('Aucune couche locale transférable dans le projet.')
        mapping=compose_map(layers,title=Path(project).stem,clip_vectors=False)
        document=map_document(mapping)
        def publish(value):
            if isinstance(value,str) and value.startswith(str(work)+os.sep):return str(destination)+value[len(str(work)):]
            if isinstance(value,dict):return {k:publish(v) for k,v in value.items()}
            if isinstance(value,list):return [publish(v) for v in value]
            return value
        save_json(publish(document),work/'map.json')
        report=publish(dict(schema='cartomize.native.transfer.v1',engine=inventory['engine'],project=str(Path(project).resolve()),
            map_file=str(work/'map.json'),transfer_warnings=warnings,
            layers=[dict(source=layer['data'],name=layer['name'],kind=layer['kind'],visible=True,options={k:v for k,v in layer.items() if k not in {'data','name','kind'}}) for layer in layers]))
        save_json(report,work/'transfer.json');_check_cancel(cancel)
    return report


def validate_native_runtime(project,destination,*,python,engine=None,layout=None,cancel=None):
    """Exercise a real installed GIS: inventory, copy and all three map exports.

    No mocked runtime counts as validation. The original project is read only.
    The requested layout is required to be unique; all products are published
    together, including engine inventory and source hashes.
    """
    import hashlib
    from .storage import new_directory,relocate_products
    project=Path(project).resolve();engine=engine or ('arcgis' if project.suffix.lower()=='.aprx' else 'qgis')
    before=hashlib.sha256(project.read_bytes()).hexdigest();destination=Path(destination).resolve()
    with new_directory(destination) as work:
        inventory=native_project(project,engine=engine,python=python,cancel=cancel)
        native_project(project,engine=engine,python=python,action='copy',destination=work/('copy.aprx' if engine=='arcgis' else 'copy.qgz'),cancel=cancel)
        checks=[]
        for suffix,signature in [('pdf',b'%PDF'),('png',b'\x89PNG\r\n\x1a\n'),('svg',None)]:
            result=native_project(project,engine=engine,python=python,action='export',layout=layout,destination=work/('map.'+suffix),cancel=cancel)
            target=Path(result['output']);data=target.read_bytes()
            if not data or signature and not data.startswith(signature):raise RuntimeError('Export natif invalide : '+suffix)
            if suffix=='svg' and not ET.fromstring(data).tag.endswith('svg'):raise RuntimeError('Export SVG invalide.')
            checks.append(dict(format=suffix,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        after=hashlib.sha256(project.read_bytes()).hexdigest()
        if before!=after:raise RuntimeError('Le projet source a été modifié par le moteur natif.')
        report=dict(schema='cartomize.native.validation.v1',engine=engine,python=str(Path(python).resolve()),project=str(project),source_sha256=before,source_unchanged=True,exports=checks,inventory=inventory)
        save_json(report,work/'validation.json');relocate_products(work,destination)
    return destination/'validation.json'
