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
