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
    visibility={item.get('id'):item.get('checked')!='Qt::Unchecked' for item in root.findall('.//layer-tree-layer')}
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
        layers.append(record)
    return dict(schema='cartomize.native.inventory.v1',engine='qgis',project=str(path),layers=layers,layouts=[dict(name=i.get('name','')) for i in root.findall('./Layouts/Layout')],mode='xml_inventory',note='Inventaire des références locales. Le rendu et les mises en page natifs nécessitent le moteur QGIS.')


def native_project(project,*,engine=None,python=None,action='inspect',destination=None,layout=None,
                   texts=None,extents=None,template=None,prefix=None,dpi=150,timeout=600,cancel=None):
    """Inspect/export/copy an APRX or QGIS project in its own GIS runtime.

    The source project is never saved in place. Native styles remain handled
    by their original engine. Requires ArcGIS Pro/ArcPy or QGIS/PyQGIS.
    """
    project=Path(project).resolve();engine=engine or ('arcgis' if project.suffix.lower()=='.aprx' else 'qgis')
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
