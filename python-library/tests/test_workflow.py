"""Failure and cancellation must not leave a partial published production."""
import threading
import numpy as np
import pytest
import cartomize as cm


@pytest.fixture
def bands(write_raster):
    prefix="LC08_L2SP_181063_20260817_20260820_02_T1"
    paths=[write_raster(f"{prefix}_SR_B{i}.TIF",np.full((4,4),14000,dtype="uint16"),nodata=0) for i in [2,3,4,5]]
    write_raster(f"{prefix}_QA_PIXEL.TIF",np.full((4,4),64,dtype="uint16"),nodata=0)
    return paths


def test_selected_bands_and_cancel_after_mosaic(bands,tmp_path):
    event=threading.Event();stages=[]
    def stage(label):
        stages.append(label)
        if label=="Composition colorée":event.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.cartographic_workflow(bands,tmp_path/"cancelled",stage=stage,cancel=event,dpi=72)
    assert "Composition colorée" in stages
    assert not (tmp_path/"cancelled").exists()
    assert not list(tmp_path.glob(".cartomize-production-*"))


def test_export_failure_and_existing_destination_are_preserved(bands,tmp_path,monkeypatch):
    def fail(*args,**kwargs):raise RuntimeError("Export unavailable")
    monkeypatch.setattr(cm.Map,"export",fail)
    with pytest.raises(RuntimeError,match="Export unavailable"):
        cm.cartographic_workflow(bands,tmp_path/"failed",dpi=72)
    assert not (tmp_path/"failed").exists()
    assert not list(tmp_path.glob(".cartomize-production-*"))
    existing=tmp_path/"existing";existing.mkdir();(existing/"keep.txt").write_text("original")
    with pytest.raises(FileExistsError):cm.cartographic_workflow(bands,existing,dpi=72)
    assert (existing/"keep.txt").read_text()=="original"


def test_color_composite_cancels_between_blocks(write_raster,tmp_path):
    source=write_raster("multi.tif",np.ones((3,300,300),dtype="float32"))
    event=threading.Event();output=tmp_path/"color.tif"
    with pytest.raises(cm.ProcessingCancelled):
        cm.color_composite(source,output,bands=(1,2,3),cancel=event,
                           progress=lambda done,total:event.set())
    assert not output.exists()


def test_atlas_cancellation_stops_between_pages(tmp_path):
    from shapely.geometry import box
    event=threading.Event()
    zones=cm.GeoDataFrame({'nom':['A','B']},geometry=[box(300000,9500000,301000,9501000),box(301000,9500000,302000,9501000)],crs=32733)
    with pytest.raises(cm.ProcessingCancelled):
        cm.atlas(cm.Map().add_layer(zones),zones,tmp_path/'atlas',name_column='nom',format='png',dpi=60,
                 cancel=event,progress=lambda done,total:event.set())
    assert (tmp_path/'atlas/A.png').is_file() and not (tmp_path/'atlas/B.png').exists()
