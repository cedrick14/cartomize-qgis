"""Check the exact two distributions before handing them to PyPI."""
from pathlib import Path
from email.parser import BytesParser
from email import policy
import hashlib
import json
import os
import sys
import tarfile
import tomllib
import zipfile

root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/'pyproject.toml').read_text())['project']
name,version=project['name'],project['version']
directory=Path(sys.argv[1]) if len(sys.argv)>1 else root/'pypi-dist'
expected={f'{name}-{version}-py3-none-any.whl',f'{name}-{version}.tar.gz'}
assert {p.name for p in directory.iterdir() if p.is_file()}==expected, 'Only the current wheel and sdist belong in the upload directory.'
if os.environ.get('GITHUB_REF_TYPE')=='tag':
    assert os.environ['GITHUB_REF_NAME']==f'python-v{version}', 'Release tag and package version differ.'
wheel=directory/f'{name}-{version}-py3-none-any.whl'
with zipfile.ZipFile(wheel) as z:
    metadata=BytesParser(policy=policy.default).parsebytes(z.read(f'{name}-{version}.dist-info/METADATA'))
    assert metadata['Name']==name and metadata['Version']==version
    assert metadata['License-Expression']=='GPL-3.0-only'
    assert metadata['Requires-Python']=='>=3.11'
    assert metadata['Description-Content-Type']=='text/markdown'
    assert {'gui','distributed','gpu'}<=set(metadata.get_all('Provides-Extra'))
    assert 'ONDON NKOUA' in metadata['Author']
    assert '## Installation' in metadata.get_payload()
    assert 'cartomize/desktop_imagery.py' in z.namelist()
    assert 'cartomize/imagery_pipeline.py' in z.namelist()
with tarfile.open(directory/f'{name}-{version}.tar.gz') as archive:
    names=set(archive.getnames())
    for file in ('README_PYPI.md','LICENSE','NOTICE.md','pyproject.toml','tests/test_imagery_pipeline.py','scripts/check_release.py'):
        assert f'{name}-{version}/{file}' in names, file
print(json.dumps({'name':name,'version':version,'files':[
    {'filename':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in sorted(directory.iterdir()) if p.is_file()]},indent=2))
