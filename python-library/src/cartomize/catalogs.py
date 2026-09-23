"""STAC search, bounded asset downloads and explicit multisensor scene metadata."""
from pathlib import Path
from urllib.parse import urlsplit,urljoin,urlencode
from urllib.request import Request,urlopen
import copy
import hashlib
import json
import re
from .storage import read_json,save_json,new_directory
from .imagery import _check_cancel


def _url(value):
    parts=urlsplit(str(value))
    if parts.scheme not in {'https','http'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('Indiquer une URL HTTP(S) sans identifiant intégré.')
    return str(value)


def _fetch_json(url,*,body=None,timeout=60):
    request=Request(_url(url),data=json.dumps(body).encode() if body is not None else None,
                    headers={'Accept':'application/geo+json, application/json','Content-Type':'application/json','User-Agent':'Cartomize'})
    with urlopen(request,timeout=timeout) as response:
        content=response.read(50_000_001)
        if len(content)>50_000_000:raise ValueError('Réponse STAC trop volumineuse.')
    return json.loads(content)


def search_stac(endpoint,*,bbox=None,datetime_range=None,collections=(),limit=20,cancel=None):
    """Search a STAC Item Search endpoint, following GET/POST pagination.

    The endpoint and any access to protected collections are supplied by the
    caller. No account credentials or provider-specific signing are guessed.
    """
    import numpy as np
    if not isinstance(limit,int) or not 1<=limit<=1000:raise ValueError('La limite doit être comprise entre 1 et 1 000 scènes.')
    params={'limit':min(limit,100)}
    if bbox is not None:
        values=np.asarray(bbox,dtype=float)
        if values.shape!=(4,) or not np.isfinite(values).all() or not (-180<=values[0]<values[2]<=180 and -90<=values[1]<values[3]<=90):raise ValueError('Emprise WGS84 : [ouest, sud, est, nord].')
        params['bbox']=','.join(map(str,bbox))
    if datetime_range:params['datetime']=datetime_range
    if collections:params['collections']=','.join(collections)
    url=_url(endpoint.rstrip('/')+'/search');url+='?'+urlencode(params);seen=set();items=[];ids=set();body=None
    while url and len(items)<limit:
        _check_cancel(cancel);key=(url,json.dumps(body,sort_keys=True))
        if key in seen:raise ValueError('Boucle de pagination STAC.')
        if len(seen)>=100:raise ValueError('Pagination STAC excessive.')
        seen.add(key);document=_fetch_json(url,body=body)
        if document.get('type')!='FeatureCollection':raise ValueError('La réponse ne contient pas une collection STAC.')
        for item in document.get('features',[]):
            identity=(item.get('collection'),item.get('id'))
            if identity not in ids:
                ids.add(identity);record=copy.deepcopy(item)
                item_base=next((urljoin(url,l['href']) for l in record.get('links',[]) if l.get('rel')=='self'),url)
                for asset in record.get('assets',{}).values():asset['href']=urljoin(item_base,asset['href'])
                items.append(record)
                if len(items)>=limit:break
        link=next((l for l in document.get('links',[]) if l.get('rel')=='next'),None)
        if link:
            method=link.get('method','GET').upper()
            if method not in {'GET','POST'}:raise ValueError('Méthode de pagination STAC non prise en charge.')
            if link.get('headers'):raise ValueError('La pagination impose des en-têtes d’authentification explicites.')
            url=urljoin(url,link['href'])
            if method=='POST':body={**(body or {}),**link.get('body',{})} if link.get('merge') else link.get('body',{})
            else:body=None
        else:url=None
    return dict(type='FeatureCollection',features=items,links=[],numberReturned=len(items),cartomize_limit=limit)


def scene_from_stac(item,*,base=None,band_mapping=None,quality_asset=None,quality_kind=None):
    """Read STAC 1.0/1.1 band metadata for local assets without sensor guessing."""
    from .scenes import Scene,Band
    if item.get('type')!='Feature' or not item.get('stac_version'):raise ValueError('Objet STAC Item attendu.')
    bands={};notes=[];aliases={'swir16':'swir1','swir22':'swir2','nir08':'nir','nir09':'nir_narrow'}
    properties=item.get('properties',{});mapping=band_mapping or {}
    for key,asset in item.get('assets',{}).items():
        metadata=asset.get('bands') or asset.get('eo:bands') or properties.get('bands') or properties.get('eo:bands') or []
        raster=asset.get('raster:bands',[])
        if key in mapping and not metadata:metadata=[dict(name=key,common_name=mapping[key])]
        for index,band in enumerate(metadata,1):
            role=mapping.get(key) if len(metadata)==1 else None
            role=role or band.get('eo:common_name') or band.get('common_name')
            if not role:continue
            role=aliases.get(role,role)
            if role in bands:raise ValueError('Plusieurs bandes décrivent le même rôle spectral : '+role)
            href=asset['href']
            if urlsplit(href).scheme in {'http','https','s3'}:raise ValueError('Télécharger les assets avant le prétraitement.')
            path=Path(href)
            if not path.is_absolute():path=Path(base or '.')/path
            if not path.is_file():raise FileNotFoundError(path)
            numeric={**asset,**(raster[index-1] if index<=len(raster) else {}),**band}
            scale=numeric.get('raster:scale',numeric.get('scale',1.));offset=numeric.get('raster:offset',numeric.get('offset',0.))
            unit=numeric.get('unit','source units');nodata=numeric.get('nodata')
            if isinstance(nodata,str):nodata=float(nodata) if nodata.lower()=='nan' else None
            if 'scale' not in numeric and 'raster:scale' not in numeric:notes.append('Calibration non déclarée pour '+role+' : unités source conservées.')
            bands[role]=Band(path,index=index,scale=scale,offset=offset,nodata=nodata,unit=unit)
    if not bands:raise ValueError('Déclarer les rôles spectraux dans STAC ou band_mapping.')
    quality=None
    if quality_asset:
        quality=Path(item['assets'][quality_asset]['href'])
        if not quality.is_absolute():quality=Path(base or '.')/quality
    return Scene(item['id'],bands,sensor=properties.get('platform') or properties.get('constellation') or 'stac',
                 acquired=(properties.get('datetime') or properties.get('start_datetime') or '')[:10] or None,
                 level=str(properties.get('processing:level','custom')),quality=quality,quality_kind=quality_kind,notes=tuple(notes))


def load_scenes_manifest(path):
    """Load local STAC Items/collections or cartomize.scenes.v1 manifests."""
    from .scenes import Scene,Band
    path=Path(path).resolve();document=read_json(path)
    if document.get('stac_version') and document.get('type')=='Feature':return [scene_from_stac(document,base=path.parent)]
    if document.get('type')=='FeatureCollection':return [scene_from_stac(item,base=path.parent) for item in document['features']]
    if document.get('schema')!='cartomize.scenes.v1':raise ValueError('Manifeste de scènes ou STAC attendu.')
    scenes=[]
    for raw in document['scenes']:
        row=dict(raw);assets={}
        for name,value in row.pop('bands').items():
            band=dict(value) if isinstance(value,dict) else dict(path=value);asset=Path(band['path'])
            band['path']=asset if asset.is_absolute() else path.parent/asset
            if not band['path'].is_file():raise FileNotFoundError(band['path'])
            assets[name]=Band(**band)
        for name in ('quality','saturation'):
            if row.get(name):
                asset=Path(row[name]);row[name]=asset if asset.is_absolute() else path.parent/asset
        scenes.append(Scene(bands=assets,**row))
    if not scenes:raise ValueError('Le manifeste ne contient aucune scène.')
    return scenes


def download_stac(source,destination,*,assets=None,max_bytes=10_000_000_000,timeout=60,progress=None,cancel=None):
    """Download selected HTTP(S) STAC assets atomically; retain local metadata.

    Hashes are computed for every completed file and advertised SHA256 checksums
    are verified when present. No partial directory survives a failed transfer.
    """
    if not isinstance(max_bytes,int) or max_bytes<1:raise ValueError('Définir une limite de téléchargement positive.')
    remote=str(source).startswith(('https://','http://'))
    document=_fetch_json(source,timeout=timeout) if remote else read_json(source)
    items=document.get('features',[]) if document.get('type')=='FeatureCollection' else [document]
    if not items or len(items)>1000:raise ValueError('Sélectionner entre 1 et 1 000 scènes.')
    requested=[]
    for i,item in enumerate(items):
        if not item.get('stac_version') or item.get('type')!='Feature':raise ValueError('STAC Item invalide.')
        keys=list(item.get('assets',{})) if assets is None else list(assets)
        if not keys:raise ValueError('Aucun asset sélectionné.')
        for key in keys:
            if key not in item['assets']:raise ValueError('Asset absent : '+key)
            href=item['assets'][key]['href'];href=urljoin(str(source),href) if remote else href
            requested.append((i,key,_url(href)))
    destination=Path(destination).resolve();total=0;records=[];copies=copy.deepcopy(items)
    for item in copies:item['assets']={};item['links']=[]
    with new_directory(destination) as work:
        for number,(i,key,url) in enumerate(requested,1):
            _check_cancel(cancel);asset=items[i]['assets'][key];suffix=Path(urlsplit(url).path).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}',suffix):suffix='.bin'
            filename=f'{i:04d}_{number:05d}'+suffix;target=work/filename;digest=hashlib.sha256();size=0
            with urlopen(Request(url,headers={'User-Agent':'Cartomize'}),timeout=timeout) as response,open(target,'xb') as handle:
                declared=response.headers.get('Content-Length')
                if declared and total+int(declared)>max_bytes:raise ValueError('Limite de téléchargement dépassée.')
                while True:
                    _check_cancel(cancel);chunk=response.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk);size+=len(chunk)
                    if total>max_bytes:raise ValueError('Limite de téléchargement dépassée.')
                    digest.update(chunk);handle.write(chunk)
                if declared and size!=int(declared):raise ValueError('Asset téléchargé incomplet.')
            checksum=digest.hexdigest();expected=asset.get('file:checksum','')
            if expected.startswith('1220') and len(expected)==68 and checksum!=expected[4:]:raise ValueError('Empreinte SHA256 de l’asset incorrecte.')
            copies[i]['assets'][key]={**asset,'href':filename,'file:checksum':'1220'+checksum}
            records.append(dict(scene=items[i]['id'],asset=key,file=filename,bytes=size,sha256=checksum))
            if progress:progress(number,len(requested))
        save_json(dict(type='FeatureCollection',features=copies,links=[]),work/'scenes.json')
        save_json(dict(schema='cartomize.download.v1',bytes=total,assets=records),work/'download.json');_check_cancel(cancel)
    return destination/'scenes.json'
