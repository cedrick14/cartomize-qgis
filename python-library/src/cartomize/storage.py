"""Atomic, JSON-only persistence shared by project and production tools."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import tempfile
import numpy as np
from ._validation import output_path


def json_value(value):
    if isinstance(value,dict):return {str(k):json_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_value(v) for v in value]
    if isinstance(value,np.ndarray):return json_value(value.tolist())
    if isinstance(value,np.generic):return json_value(value.item())
    if isinstance(value,Path):return str(value)
    if isinstance(value,float) and not np.isfinite(value):return None
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise TypeError(f'Unsupported project value: {type(value).__name__}')


def save_json(payload,path,*,overwrite=False,sources=()):
    path=output_path(path,overwrite,sources)
    text=json.dumps(json_value(payload),ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    fd,temporary=tempfile.mkstemp(prefix='.cartomize-',suffix='.json',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle:handle.write(text)
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)
    return path


def read_json(path,*,limit=50_000_000):
    path=Path(path)
    if path.stat().st_size>limit:raise ValueError('Le fichier de configuration est trop volumineux.')
    return json.loads(path.read_text(encoding='utf-8'))


def relocate_products(work,destination):
    """Relocate generated references without changing downloaded source assets."""
    work=Path(work);destination=Path(destination);prefix=str(work)+os.sep
    downloaded=set()
    for manifest in work.rglob('download.json'):
        document=read_json(manifest)
        if document.get('schema')=='cartomize.download.v1':
            downloaded.update((manifest.parent/asset['file']).resolve() for asset in document['assets'])
    def replace(value):
        if isinstance(value,str) and value.startswith(prefix):return str(destination)+value[len(str(work)):]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        return value
    for path in work.rglob('*.json'):
        if path.resolve() not in downloaded:save_json(replace(read_json(path)),path,overwrite=True)
    import rasterio
    for path in work.rglob('*.tif'):
        if path.resolve() in downloaded:continue
        updates={}
        with rasterio.open(path) as src:
            for band in (0,*src.indexes):
                changes={}
                for key,value in src.tags(band).items():
                    try:
                        parsed=json.loads(value);changed=replace(parsed)
                        if changed!=parsed:changes[key]=json.dumps(changed,ensure_ascii=False)
                    except (ValueError,TypeError):
                        changed=replace(value)
                        if changed!=value:changes[key]=changed
                if changes:updates[band]=changes
        if updates:
            with rasterio.open(path,'r+') as src:
                for band,changes in updates.items():src.update_tags(band,**changes)
    return replace


@contextmanager
def new_directory(destination):
    destination=Path(destination).expanduser().resolve()
    if destination.exists():raise FileExistsError(f'Choisir un nouveau répertoire : {destination}')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cartomize-',dir=destination.parent) as temporary:
        work=Path(temporary)/'products';work.mkdir()
        yield work
        if destination.exists():raise FileExistsError(destination)
        work.rename(destination)
