"""Reproducibility snapshots, data-change checks and named review records."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
from .storage import save_json,read_json,json_value
from .session import map_document,_references


def _digest_file(path):
    digest=hashlib.sha256()
    with open(path,'rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def _digest(value):return hashlib.sha256(json.dumps(json_value(value),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def snapshot_project(project,*,hash_files=True):
    state=map_document(project) if hasattr(project,'layers') and hasattr(project,'render') else json_value(project)
    files=[]
    for path in _references(state):
        if path.is_file():files.append(dict(path=str(path),bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,sha256=_digest_file(path) if hash_files else None))
    payload=dict(state=state,files=files)
    return dict(schema='cartomize.mapops.v1',created_at=datetime.now(timezone.utc).isoformat(),fingerprint=_digest(payload),**payload)


def compare_snapshots(previous,current):
    if isinstance(previous,(str,Path)):previous=read_json(previous)
    if isinstance(current,(str,Path)):current=read_json(current)
    before={i['path']:i for i in previous.get('files',[])};after={i['path']:i for i in current.get('files',[])};changes=[]
    for path in sorted(before.keys()|after.keys()):
        kind='added' if path not in before else 'removed' if path not in after else 'modified' if before[path]!=after[path] else None
        if kind:changes.append(dict(kind=kind,path=path))
    settings_changed=_digest(previous.get('state'))!=_digest(current.get('state'))
    return dict(schema='cartomize.mapops.diff.v1',changed=bool(changes or settings_changed),settings_changed=settings_changed,
                files=changes,previous=previous.get('fingerprint'),current=current.get('fingerprint'))


def record_review(snapshot,path,*,reviewer,decision='approved',comment='',quality=None,overwrite=False):
    if not reviewer.strip() or decision not in {'approved','rejected','changes_requested'}:raise ValueError('Renseigner le responsable et une décision valide.')
    if decision=='approved' and quality is not None and not quality.get('valid'):raise ValueError('Corriger les erreurs du contrôle avant approbation.')
    if snapshot.get('fingerprint')!=_digest({k:snapshot[k] for k in ('state','files')}):raise ValueError('L’instantané a été modifié depuis sa création.')
    record=dict(schema='cartomize.review.v1',reviewer=reviewer.strip(),decision=decision,comment=comment,
        fingerprint=snapshot['fingerprint'],created_at=datetime.now(timezone.utc).isoformat(),quality=quality,
        scope='Revue locale associée à une empreinte ; ne constitue pas une signature numérique certifiée.')
    return save_json(record,path,overwrite=overwrite,sources=[item["path"] for item in snapshot.get("files",[])])


def verify_review(review,snapshot):
    if isinstance(review,(str,Path)):review=read_json(review)
    return snapshot.get('fingerprint')==_digest({k:snapshot[k] for k in ('state','files')}) and review.get('schema')=='cartomize.review.v1' and review.get('decision')=='approved' and review.get('fingerprint')==snapshot.get('fingerprint')
