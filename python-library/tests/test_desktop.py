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


def test_native_window_indices_and_calculator(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    path=write_raster("bands.tif",np.array([np.full((80,90),.2),np.full((80,90),.6)],dtype="float32"))
    with rasterio.open(path,"r+") as src:src.descriptions=("red","nir")
    window=CartomizeWindow();window.show();window.navigation.setCurrentRow(4);page=window.pages[4]
    page.source.edit.setText(str(path));page.output.edit.setText(str(tmp_path/"ndvi.tif"))
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish(window)
    assert window.status.text().startswith("Traitement terminé")
    with rasterio.open(tmp_path/"ndvi.tif") as src:np.testing.assert_allclose(src.read(1),.5)
    window.navigation.setCurrentRow(5);calculator=window.pages[5]
    calculator.add_raster(path);calculator.expression.setPlainText("where(nir > red, 1, 0)")
    calculator.output.edit.setText(str(tmp_path/"mask.tif"))
    QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton);finish(window)
    with rasterio.open(tmp_path/"mask.tif") as src:np.testing.assert_array_equal(src.read(1),1)
    assert window.folder_button.isEnabled();window.close();QTest.qWait(10)


def test_background_job_keeps_event_loop_responsive_and_cancels(application,tmp_path):
    from cartomize.desktop import CartomizeWindow
    window=CartomizeWindow();window.show();ticks=[];timer=QTimer()
    timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
    def job(progress,event):
        while not event.wait(.01):pass
        raise cm.ProcessingCancelled()
    window.pages[0].staged=False;window.pages[0].job=lambda options:job
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
    window=CartomizeWindow();window.navigation.setCurrentRow(1);page=window.pages[1]
    page.source.edit.setText(str(tmp_path));page.output.edit.setText(str(tmp_path/"prepared.tif"))
    window.start();finish(window)
    assert Path(window.output_path).is_file()
    assert window.progress.value()==100
    window.close();QTest.qWait(10)


def test_mapping_page_exports_real_file(application,write_raster,tmp_path):
    from cartomize.desktop import CartomizeWindow
    path=write_raster("classes.tif",np.arange(100,dtype="float32").reshape(10,10))
    window=CartomizeWindow();window.navigation.setCurrentRow(3);page=window.pages[3]
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
    window=CartomizeWindow();window.show();page=window.pages[0]
    assert isinstance(page,WorkflowPage) and window.stack.currentIndex()==0
    assert not window.windowIcon().isNull() and not window.brand_icon.pixmap().isNull()
    assert not window.settings.isVisible()
    page.source.edit.setText(str(tmp_path));page.aoi.edit.setText(str(aoi));page.add_layer(localities)
    page.directory.edit.setText(str(tmp_path));page.project.setText("production")
    page.title.setText("Carte de démonstration");page.dpi.setValue(72)
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
    assert window.progress.value()==100 and window.folder_button.isEnabled()
    window.close();QTest.qWait(10)
