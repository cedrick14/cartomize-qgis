"""Run the new widgets through actual worker jobs and session reloading."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,time
from pathlib import Path
import pytest
import numpy as np
import rasterio
import geopandas as gpd
from shapely.geometry import box
from rasterio.transform import from_origin
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QEventLoop
import cartomize as cm


@pytest.fixture(scope='module')
def application():return QApplication.instance() or QApplication([])


def finish(window):
    loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+40
    timer.timeout.connect(lambda:loop.quit() if window.thread is None or time.monotonic()>deadline else None);timer.start(10);loop.exec();timer.stop()
    assert window.thread is None
    assert window.status.text().startswith('Traitement terminé'),window.status.text()


@pytest.fixture
def inputs(tmp_path):
    source=tmp_path/'bands.tif';a=np.ones((4,48,48),dtype='float32')*.1;a[:,:,24:]=.8
    with rasterio.open(source,'w',driver='GTiff',height=48,width=48,count=4,dtype='float32',transform=from_origin(500000,1000000,10,10),crs=32631) as dst:dst.write(a);dst.descriptions=('blue','green','red','nir')
    training=tmp_path/'training.gpkg';gpd.GeoDataFrame({'classe':[0,2]},geometry=[box(500030,999550,500180,999950),box(500300,999550,500440,999950)],crs=32631).to_file(training)
    return source,training


def test_new_ui_classification_plan_and_complete_session(application,inputs,tmp_path):
    from cartomize.desktop import CartomizeWindow
    source,training=inputs;window=CartomizeWindow();window.select_tool('classification');page=window.tool('classification')
    page.source.edit.setText(str(source));page.training.edit.setText(str(training));page.output.edit.setText(str(tmp_path));page.trees.setValue(10)
    window.start();finish(window);assert (tmp_path/'classification/classification.tif').exists();assert len(window.results)==2
    window.select_tool('assistant');assistant=window.tool('assistant');assistant.inputs.addItem(str(source));assistant.title.setText('Carte automatique');assistant.output.edit.setText(str(tmp_path));assistant.classification.setCurrentIndex(assistant.classification.findData('supervised'));assistant.training.edit.setText(str(training))
    window.start(proposal=True);finish(window);assert assistant.execution_plan and assistant.execute_button.isEnabled()
    window.start(execute_plan=True);finish(window);assert (tmp_path/'production/carte.pdf').exists();assert window.production_config
    window.resume_production();mapping=window.tool('mapping');settings=mapping.layout_settings
    if settings.items.rowCount():settings.items.item(0,6).setText('8')
    config=mapping.capture_map();mapping.build_map(config).export(tmp_path/'resumed.png',dpi=72);saved=window.save_session_file(tmp_path/'session.cartomize.json')
    before=window.capture_session();second=CartomizeWindow();second.open_session_file(saved)
    assert second.tool('mapping').capture_map()==config
    assert second.tool('classification').training.text()==str(training)
    assert second.tool('assistant').execution_plan==assistant.execution_plan and second.tool('assistant').execute_button.isEnabled()
    assert second.capture_session()['pages']==before['pages']
    second.close();window.close();application.processEvents()


def test_ui_recipe_mapops_terrain_and_native_inventory(application,inputs,tmp_path):
    from cartomize.desktop import CartomizeWindow
    source,training=inputs;window=CartomizeWindow();window.tool('mapping').load_layers([{'data':str(training)}]);window.tool('mapping').title.setText('Échantillons')
    window.select_tool('mapops');review=window.tool('mapops');review.output.edit.setText(str(tmp_path/'snapshot.json'));window.start();finish(window)
    assert json.loads((tmp_path/'snapshot.json').read_text())['fingerprint']
    recipe=cm.save_recipe(window.tool('mapping').capture_map(),tmp_path/'recipe.json');window.select_tool('recipes');page=window.tool('recipes');page.source.edit.setText(str(recipe));page.output.edit.setText(str(tmp_path));window.start();finish(window)
    assert (tmp_path/'production-serie/carte.pdf').exists()
    window.select_tool('terrain');page=window.tool('terrain');page.source.edit.setText(str(source));page.output.edit.setText(str(tmp_path/'terrain.tif'));window.start();finish(window)
    with rasterio.open(tmp_path/'terrain.tif') as src:assert src.descriptions==('slope','aspect','hillshade')
    project=tmp_path/'project.qgs';project.write_text('<qgis><projectlayers/><Layouts><Layout name="Carte"/></Layouts></qgis>')
    window.select_tool('native');page=window.tool('native');page.source.edit.setText(str(project));window.start();finish(window)
    assert page.inventory['layouts']==[{'name':'Carte'}]
    window.close();application.processEvents()
