"""Real QGIS integration, activated only with an installed vendor runtime."""
import hashlib,json,os,subprocess
from pathlib import Path
import pytest
import cartomize as cm
from cartomize.native import validate_native_runtime


@pytest.mark.skipif(not os.environ.get('CARTOMIZE_QGIS_PYTHON'),reason='QGIS runtime not configured')
def test_qgis_runtime_preserves_sources_styles_and_exports(tmp_path):
    python=os.environ['CARTOMIZE_QGIS_PYTHON'];environment=os.environ.copy();environment['QT_QPA_PLATFORM']='offscreen'
    fixture=Path(__file__).parents[1]/'examples/native_qgis_fixture.py'
    subprocess.run([python,str(fixture),str(tmp_path/'input')],env=environment,check=True,timeout=120)
    project=tmp_path/'input/project.qgz';digest=hashlib.sha256(project.read_bytes()).hexdigest()
    report=json.loads(validate_native_runtime(project,tmp_path/'validation',python=python,layout='Validation').read_text())
    assert report['source_unchanged'] and len(report['exports'])==3 and report['inventory']['runtime_version']
    assert report['inventory']['layers'][0]['options']['ranges'][0]['upper']==100
    imported=cm.import_native_project(project,tmp_path/'imported',python=python)
    mapping=cm.Map.load(imported['map_file']);assert len(mapping.layers[0].ranges)==2
    mapping.export(tmp_path/'transfer.png',dpi=80)
    cm.native_project(project,python=python,action='export',layout='Validation',texts={'titre':'Texte modifié'},extents={'carte':[12.9,-4.1,14,-3.5]},destination=tmp_path/'modified.pdf')
    with pytest.raises(RuntimeError,match='unique'):cm.native_project(project,python=python,action='export',layout='Absent',destination=tmp_path/'bad.pdf')
    assert not (tmp_path/'bad.pdf').exists() and hashlib.sha256(project.read_bytes()).hexdigest()==digest
