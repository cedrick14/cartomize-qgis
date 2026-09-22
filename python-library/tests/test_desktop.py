"""Exercise the actual Qt widgets and background processing without a display."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import time
import threading
from pathlib import Path
import numpy as np
import pytest
import rasterio

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtTest import QTest
import cartomize as cm


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def finish(window,timeout=15):
    # Run the real event loop, releasing the GIL for Python work in QThread.
    loop=QEventLoop();timer=QTimer();deadline=time.monotonic()+timeout
    timer.timeout.connect(lambda:loop.quit() if window.thread is None or time.monotonic()>deadline else None)
    timer.start(10);loop.exec();timer.stop()
    assert window.thread is None,"Desktop worker did not finish"


def test_project_analysis_applies_classes_and_restores_sources(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    data=np.zeros((100,100),dtype='int16');data[12:88,12:88]=2;data[40:65,40:65]=3
    path=write_raster('occupation.tif',data,nodata=None)
    window=CartomizeWindow();window.show();window.select_tool('project');page=window.tool('project')
    icon=window.brand_icon.pixmap().toImage()
    assert any(max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())>40
               for x in range(icon.width()) for y in range(icon.height()) if (c:=icon.pixelColor(x,y)).alpha()>100)
    assert window.run_button.text()=='Analyser le projet'
    page.add_layer(path);page.directory.edit.setText(str(tmp_path));page.name.setText('analyse')
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish(window,30)
    assert page.project is not None,window.status.text()
    assert page.classes.rowCount()==2
    page.classes.item(0,2).setText('Forêt primaire');page.classes.item(0,3).setText('#26743b')
    QTest.mouseClick(page.apply_button,Qt.MouseButton.LeftButton)
    assert window.pages[window.stack.currentIndex()] is window.tool('mapping')
    mapping=window.tool('mapping');config=mapping.capture_map()
    assert config['layers'][0]['classes'][2]==('Forêt primaire','#26743b')
    assert cm.load_project(page.project.manifest).layers[0]['classes'][2][0]=='Forêt primaire'
    mapping.output.edit.setText(str(tmp_path/'carte.png'));mapping.dpi.setValue(72)
    window.start();finish(window,30)
    assert (tmp_path/'carte.png').stat().st_size>1000,window.status.text()
    window.select_tool('project');QTest.mouseClick(page.restore_button,Qt.MouseButton.LeftButton)
    config=mapping.capture_map();assert Path(config['layers'][0]['data'])==path and 'classes' not in config['layers'][0]
    window.close();QTest.qWait(10)


def test_native_window_indices_and_calculator(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    path=write_raster("bands.tif",np.array([np.full((80,90),.2),np.full((80,90),.6)],dtype="float32"))
    with rasterio.open(path,"r+") as src:src.descriptions=("red","nir")
    window=CartomizeWindow();window.show();window.select_tool('indices');page=window.tool('indices')
    page.source.edit.setText(str(path));page.output.edit.setText(str(tmp_path/"ndvi.tif"))
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish(window)
    assert window.status.text().startswith("Traitement terminé")
    with rasterio.open(tmp_path/"ndvi.tif") as src:np.testing.assert_allclose(src.read(1),.5)
    window.select_tool('calculator');calculator=window.tool('calculator')
    calculator.add_raster(path);calculator.expression.setPlainText("where(nir > red, 1, 0)")
    calculator.output.edit.setText(str(tmp_path/"mask.tif"))
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish(window)
    with rasterio.open(tmp_path/"mask.tif") as src:np.testing.assert_array_equal(src.read(1),1)
    assert window.folder_button.isEnabled();window.close();QTest.qWait(10)


def test_background_job_keeps_event_loop_responsive_and_cancels(application,tmp_path):
    from cartomize.desktop import CartomizeWindow
    window=CartomizeWindow();window.show();window.select_tool('workflow');ticks=[];timer=QTimer()
    timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
    def job(progress,event):
        while not event.wait(.01):pass
        raise cm.ProcessingCancelled()
    window.tool('workflow').staged=False;window.tool('workflow').job=lambda options:job
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton)
    QTest.qWait(80)
    assert len(ticks)>=3 and window.thread is not None
    QTest.mouseClick(window.cancel_button,Qt.MouseButton.LeftButton);finish(window)
    assert window.status.text()=="Traitement interrompu."
    timer.stop();window.close();QTest.qWait(10)


def test_preparation_page_progress_and_cancellation(application,write_raster,tmp_path):
    prefix="LC08_L2SP_181063_20260817_20260820_02_T1"
    for index in [2,3,4,5]:write_raster(f"{prefix}_SR_B{index}.TIF",np.full((2,2),10000,dtype="uint16"),nodata=0)
    write_raster(f"{prefix}_QA_PIXEL.TIF",np.full((2,2),64,dtype="uint16"),nodata=0)
    from cartomize.desktop import CartomizeWindow
    window=CartomizeWindow();window.select_tool('prepare');page=window.tool('prepare')
    page.source.edit.setText(str(tmp_path));page.output.edit.setText(str(tmp_path/"prepared.tif"))
    window.start();finish(window)
    assert Path(window.output_path).is_file()
    assert window.progress.value()==100
    window.close();QTest.qWait(10)


def test_mapping_page_exports_real_file(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    path=write_raster("classes.tif",np.arange(100,dtype="float32").reshape(10,10))
    window=CartomizeWindow();window.select_tool('mapping');page=window.tool('mapping')
    page.add_layer(path);page.title.setText("Distribution spatiale")
    page.output.edit.setText(str(tmp_path/"carte.png"));page.dpi.setValue(72)
    window.start();finish(window)
    assert (tmp_path/"carte.png").stat().st_size>1000
    window.close();QTest.qWait(10)


def test_default_workflow_produces_multiband_rgb_and_map(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow, WorkflowPage
    from rasterio.transform import from_origin
    import geopandas as gpd
    from shapely.geometry import Point, box
    import json
    # Adjacent scenes from the same acquisition; test clipping and overlays.
    for scene,x in [("181063",300000),("181064",300020)]:
        prefix=f"LC08_L2SP_{scene}_20260817_20260820_02_T1"
        for index in [2,3,4,5]:
            write_raster(f"{prefix}_SR_B{index}.TIF",np.full((4,4),10000+index*1000,dtype="uint16"),
                         nodata=0,transform=from_origin(x,9500000,10,10))
        write_raster(f"{prefix}_QA_PIXEL.TIF",np.full((4,4),64,dtype="uint16"),
                     nodata=0,transform=from_origin(x,9500000,10,10))
    aoi=tmp_path/"zone.geojson"
    gpd.GeoDataFrame(geometry=[box(300010,9499960,300050,9500000)],crs=32733).to_file(aoi)
    localities=tmp_path/"localites.geojson"
    gpd.GeoDataFrame({"nom":["Site A"]},geometry=[Point(300025,9499980)],crs=32733).to_file(localities)
    window=CartomizeWindow();window.show();window.select_tool('workflow');page=window.tool('workflow')
    assert isinstance(page,WorkflowPage) and window.pages[window.stack.currentIndex()] is page
    assert not window.windowIcon().isNull() and not window.brand_icon.pixmap().isNull()
    assert not window.settings.isVisible()
    page.source.edit.setText(str(tmp_path));page.aoi.edit.setText(str(aoi));page.add_layer(localities)
    page.directory.edit.setText(str(tmp_path));page.project.setText("production")
    page.title.setText("Carte de démonstration");page.dpi.setValue(72)
    page.layout_settings.template.setCurrentIndex(1);page.layout_settings.north.setChecked(False)
    window.start();finish(window,30)
    assert window.status.text().startswith("Traitement terminé"),window.status.text()
    out=tmp_path/"production"
    assert Path(window.output_path)==out/"production.json"
    with rasterio.open(out/"multibande.tif") as src:
        assert src.count==4 and src.width==4 and src.descriptions==("blue","green","red","nir")
        np.testing.assert_allclose(src.read(3),14000*.0000275-.2,atol=1e-7)
    with rasterio.open(out/"composition_coloree.tif") as src:
        assert src.count==4 and src.dtypes==("uint8",)*4
    assert (out/"carte.pdf").stat().st_size>1000
    assert (out/"carte.png").stat().st_size>1000
    manifest=json.loads((out/"multibande.json").read_text())
    assert manifest["product"]==str(out/"multibande.tif")
    assert ".cartomize-production-" not in (out/"production.json").read_text()
    plan=json.loads((out/"production.json").read_text())["layer_plan"]
    assert plan[-1]["role"]=="localities" and plan[-1]["labels"]=="nom"
    production=json.loads((out/"production.json").read_text())
    assert production["template"] and production["north_arrow"] is False
    assert window.progress.value()==100 and window.folder_button.isEnabled()
    window.resume_production();config=window.tool('mapping').capture_map()
    assert len(config['layers'])==2 and config['layers'][0]['rgb']=='native'
    assert config['options']['title']=='Carte de démonstration' and config['layout']['north'] is False
    window.close();QTest.qWait(10)


def test_layout_template_controls_preview_and_frames(application,tmp_path):
    from cartomize.desktop import CartomizeWindow
    from shapely.geometry import box
    source=tmp_path/'limites.geojson'
    cm.GeoDataFrame({'nom':['Zone A']},geometry=[box(300000,9500000,302000,9502000)],crs=32733).to_file(source)
    window=CartomizeWindow();window.select_tool('mapping');page=window.tool('mapping')
    page.add_layer(source);page.title.setText('Mise en page');page.dpi.setValue(72)
    settings=page.layout_settings
    assert settings.template.count()==25
    ident=next(t['id'] for t in cm.list_templates() if t['map_frames']>=3)
    settings.template.setCurrentIndex(settings.template.findData(ident))
    assert settings.frames.rowCount()>=3
    settings.frames.item(0,1).setText('300000, 9500000, 302000, 9502000')
    settings.frames.item(1,1).setText('300000, 9500000, 300500, 9500500')
    settings.legend.setChecked(False);settings.north.setChecked(False)
    mapped=page.build_map(page.capture_map())
    assert not mapped.legend_enabled and not mapped.north_enabled
    assert mapped.frames[mapped.frame_ids[1]]['extent']==(300000,9500000,300500,9500500)
    page.output.edit.setText(str(tmp_path/'layout.pdf'));window.start();finish(window,30)
    assert (tmp_path/'layout.pdf').read_bytes().startswith(b'%PDF')
    window.start(preview=True);finish(window,30)
    assert window.status.text()=='Aperçu cartographique actualisé.'
    assert window.preview_dialog.isVisible()
    window.preview_dialog.close();window.close();QTest.qWait(10)


def test_atlas_page_exports_one_map_per_zone(application,tmp_path):
    from cartomize.desktop import CartomizeWindow
    from shapely.geometry import box
    source=tmp_path/'zones.geojson'
    cm.GeoDataFrame({'nom':['Zone A','Zone B']},geometry=[box(300000,9500000,301000,9501000),box(301000,9500000,302000,9501000)],crs=32733).to_file(source)
    window=CartomizeWindow();window.select_tool('atlas');page=window.tool('atlas')
    page.add_layer(source);page.zones.edit.setText(str(source));page.name_column.setText('nom')
    page.output.edit.setText(str(tmp_path/'atlas'));page.atlas_format.setCurrentText('png');page.dpi.setValue(72)
    window.start();finish(window,30)
    assert window.status.text().startswith('Traitement terminé'),window.status.text()
    assert sorted(p.name for p in (tmp_path/'atlas').glob('*.png'))==['Zone_A.png','Zone_B.png']
    window.close();QTest.qWait(10)


def test_vector_raster_and_diagnostic_pages(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    from shapely.geometry import Point
    source=tmp_path/'localites.geojson';cm.GeoDataFrame({'nom':['A']},geometry=[Point(300000,9500000)],crs=32733).to_file(source)
    window=CartomizeWindow();window.select_tool('vector');page=window.tool('vector')
    page.source.edit.setText(str(source));page.operation.setCurrentIndex(page.operation.findData('buffer'))
    page.distance.setValue(100);page.output.edit.setText(str(tmp_path/'tampon.gpkg'))
    window.start();finish(window)
    result=cm.read_file(tmp_path/'tampon.gpkg')
    assert result.geometry.iloc[0].area==pytest.approx(np.pi*100**2,rel=.01)
    window.select_tool('inspect');page=window.tool('inspect')
    page.source.edit.setText(str(source));page.output.edit.setText(str(tmp_path/'rapport.json'))
    window.start();finish(window)
    assert 'label_field' in page.report.toPlainText() and 'nom' in page.report.toPlainText()
    path=write_raster('classes.tif',np.array([[1,1],[2,2]],dtype='int16'))
    window.select_tool('raster');page=window.tool('raster')
    page.source.edit.setText(str(path));page.operation.setCurrentIndex(page.operation.findData('reclassify'))
    page.mapping.setPlainText('1 = 10\n2 = 20');page.output.edit.setText(str(tmp_path/'reclasse.tif'))
    window.start();finish(window)
    with rasterio.open(tmp_path/'reclasse.tif') as src:np.testing.assert_array_equal(src.read(1),[[10,10],[20,20]])
    page.operation.setCurrentIndex(page.operation.findData('class_areas'));page.output.edit.setText(str(tmp_path/'superficies.csv'))
    window.start();finish(window)
    import pandas as pd
    table=pd.read_csv(tmp_path/'superficies.csv');np.testing.assert_allclose(table['area_ha'],[.02,.02])
    window.close();QTest.qWait(10)


@pytest.mark.parametrize('operation',['clip','buffer','intersection','union','difference','symmetric_difference','sjoin','dissolve','reproject','make_valid','area','length','nearest'])
def test_every_vector_selector_runs_its_algorithm(application,tmp_path,operation):
    from cartomize.desktop_tools import VectorPage
    from shapely.geometry import box
    source=tmp_path/'left.geojson';other=tmp_path/'right.geojson'
    cm.GeoDataFrame({'group':['A']},geometry=[box(300000,9500000,300020,9500020)],crs=32733).to_file(source)
    cm.GeoDataFrame({'target':['B']},geometry=[box(300010,9500000,300030,9500020)],crs=32733).to_file(other)
    page=VectorPage();page.operation.setCurrentIndex(page.operation.findData(operation))
    page.source.edit.setText(str(source));page.secondary.edit.setText(str(other));page.crs.setText('EPSG:32733')
    page.distance.setValue(10);page.field.setText('group');page.unit.setCurrentText('m2' if operation=='area' else 'm')
    destination=tmp_path/'result.gpkg';page.output.edit.setText(str(destination))
    page.job({'overwrite':False})(lambda *args:None,threading.Event())
    result=cm.read_file(destination)
    assert not result.empty and result.crs.to_epsg()==32733
    expected={'clip':200,'intersection':200,'union':600,'difference':200,'symmetric_difference':400,'dissolve':400,'reproject':400,'make_valid':400}
    if operation in expected:assert result.geometry.area.sum()==pytest.approx(expected[operation])
    elif operation=='buffer':assert result.geometry.area.sum()==pytest.approx(400+80*10+np.pi*100,rel=.001)
    elif operation=='sjoin':assert result.target.tolist()==['B']
    elif operation=='nearest':assert result.distance_m.tolist()==[0]
    elif operation=='area':assert result.area_m2.tolist()==[400]
    elif operation=='length':assert result.length_m.tolist()==[80]
    page.close()


@pytest.mark.parametrize('operation',['clip','reproject','reclassify','zonal_stats','class_areas','change_matrix'])
def test_every_raster_selector_runs_its_algorithm(application,write_raster,tmp_path,operation):
    from cartomize.desktop_tools import RasterToolsPage
    from shapely.geometry import box
    import pandas as pd
    source=write_raster('classes.tif',np.array([[1,1],[2,2]],dtype='int16'))
    after=write_raster('after.tif',np.array([[2,2],[2,3]],dtype='int16'))
    zone=tmp_path/'zone.geojson';cm.GeoDataFrame({'nom':['A']},geometry=[box(300000,9499980,300020,9500000)],crs=32733).to_file(zone)
    page=RasterToolsPage();page.operation.setCurrentIndex(page.operation.findData(operation))
    page.source.edit.setText(str(source));page.secondary.edit.setText(str(after if operation=='change_matrix' else zone))
    page.crs.setText('EPSG:32733');page.mapping.setPlainText('1 = 10\n2 = 20')
    suffix='.csv' if operation in {'class_areas','change_matrix'} else '.gpkg' if operation=='zonal_stats' else '.tif'
    destination=tmp_path/('result'+suffix);page.output.edit.setText(str(destination))
    page.job({'overwrite':False})(lambda *args:None,threading.Event())
    if suffix=='.tif':
        with rasterio.open(destination) as src:np.testing.assert_array_equal(src.read(1),[[10,10],[20,20]] if operation=='reclassify' else [[1,1],[2,2]])
    elif operation=='zonal_stats':
        table=cm.read_file(destination);assert table['mean'].iloc[0]==pytest.approx(1.5) and table['count'].iloc[0]==4
    elif operation=='class_areas':np.testing.assert_allclose(pd.read_csv(destination)['area_ha'],[.02,.02])
    else:assert pd.read_csv(destination)['pixels'].sum()==4
    page.close()


def test_assistant_result_transfers_quality_and_atlas_configuration(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    from shapely.geometry import box
    source=tmp_path/'communes.geojson'
    cm.GeoDataFrame({'nom':['Commune A']},geometry=[box(300000,9500000,301000,9501000)],crs=32733).to_file(source)
    window=CartomizeWindow();window.show();assistant=window.tool('assistant')
    assert window.pages[window.stack.currentIndex()] is assistant
    assert window.run_button.text()=='Examiner les données'
    assistant.inputs.addItem(str(source));assistant.title.setText('Carte administrative')
    assistant.goal.setCurrentIndex(assistant.goal.findData('administrative'))
    window.start();finish(window)
    assert assistant.assessment['ready'],window.status.text()
    assistant.steps.selectRow(0);QTest.mouseClick(assistant.open_button,Qt.MouseButton.LeftButton)
    project=window.tool('project');assert window.pages[window.stack.currentIndex()] is project
    assert project.layers.item(0,0).text()==str(source)
    project.directory.edit.setText(str(tmp_path));window.start();finish(window)
    assert len(window.results)==1 and window.results[0]['labels']=='nom'
    window.transfer_result(window.results[0],'mapping');mapping=window.tool('mapping')
    window.open_assistant_step('mapping',assistant.assessment)
    config=mapping.capture_map();assert config['options']['title']=='Carte administrative'
    assert config['layers'][0]['labels']=='nom' and config['layout']['template']
    mapping.layout_settings.frames.item(0,1).setText('300000, 9500000, 301000, 9501000')
    mapping.layout_settings.legend.setChecked(False);mapping.layout_settings.refresh()
    assert mapping.layout_settings.capture()['frames'][0]['extent']==(300000,9500000,301000,9501000)
    window.start(review=True);finish(window)
    assert window.review_dialog.isVisible()
    window.review_dialog.close();window.prepare_atlas(mapping.capture_map())
    atlas=window.tool('atlas');assert atlas.capture_map()==mapping.capture_map()
    scientific=write_raster('science.tif',np.array([np.full((2,2),.2),np.full((2,2),.6)],dtype='float32'))
    with rasterio.open(scientific,'r+') as src:src.descriptions=('red','nir')
    window.register_result({'data':scientific});window.transfer_result(window.results[-1],'indices')
    indices=window.tool('indices');indices.output.edit.setText(str(tmp_path/'ndvi.tif'));window.start();finish(window)
    assert window.results[-1]['data']==str(tmp_path/'ndvi.tif')
    window.transfer_result(window.results[-1],'calculator');calculator=window.tool('calculator')
    assert calculator.inputs.rowCount()==1
    temporal=window.tool('temporal');temporal.minimum.setValue(5);temporal.stat.setCurrentIndex(temporal.stat.findData('count'))
    assert temporal.minimum.value()==1 and not temporal.minimum.isEnabled()
    window.close();QTest.qWait(10)
