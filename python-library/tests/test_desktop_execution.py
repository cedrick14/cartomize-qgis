"""Actual Qt state persistence and execution-engine propagation."""
import os,time,json
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
import rasterio
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QEventLoop


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def test_execution_settings_restore_and_scope(app,tmp_path):
    from cartomize.desktop import CartomizeWindow
    window=CartomizeWindow();window.select_tool('indices')
    engine=window.execution_settings;engine.execution.setCurrentIndex(1);engine.scheduler.setText('tcp://127.0.0.1:8786');engine.device.setCurrentIndex(1)
    state=window.capture_session();engine.scheduler.clear();engine.device.setCurrentIndex(0);window.restore_session(state)
    assert engine.parameters()==dict(execution='distributed',scheduler_address='tcp://127.0.0.1:8786',device='cuda')
    window.select_tool('terrain');assert not engine.device.isEnabled()
    window.select_tool('mapping');assert engine.isHidden()
    window.tool('native').action.setCurrentIndex(window.tool('native').action.findData('validate'))
    assert window.tool('native').output.mode=='directory'
    window.close()


def test_distributed_chain_qt_worker(app,write_raster,tmp_path):
    pytest.importorskip('distributed')
    from cartomize.desktop import CartomizeWindow
    source=write_raster('source.tif',np.ones((70,70),dtype='float32'))
    window=CartomizeWindow();window.select_tool('processing');window.workers.setValue(2);window.execution_settings.execution.setCurrentIndex(1)
    page=window.tool('processing');page.processing_steps.set_records([dict(id='result',operation='calculate',parameters={'expression':'a*7','inputs':{'a':str(source)}})])
    page.output.edit.setText(str(tmp_path));page.name.setText('qt-distributed');window.start()
    loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+60
    timer.timeout.connect(lambda:loop.quit() if window.thread is None or time.monotonic()>deadline else None);timer.start(10);loop.exec();timer.stop()
    assert window.thread is None and window.status.text().startswith('Traitement terminé'),window.status.text()
    report=json.loads((tmp_path/'qt-distributed/automation.json').read_text())
    with rasterio.open(report['results']['result']) as src:assert src.tags()['execution']=='distributed' and (src.read(1)==7).all()
    window.close()
