import json
import threading
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
import cartomize as cm
from cartomize.algebra import Expression


def read(path):
    with rasterio.open(path) as src:return src.read(masked=True)


def test_conditional_masks_and_valid_zero(write_raster,tmp_path):
    a=write_raster("a.tif",np.array([[0,2,-9999,4]],dtype="float32"))
    b=write_raster("b.tif",np.array([[8,-9999,6,0]],dtype="float32"))
    output=cm.calculate({"filled":"coalesce(a,b)","choice":"where(a > 0, a, b)",
        "division":"a/b","threshold":"where(a/b > 0, 1, 0)"},{"a":a,"b":b},tmp_path/"out.tif")
    values=read(output)
    assert values[0].tolist()==[[0,2,6,4]]
    assert values[1].mask.tolist()==[[False,False,True,False]]
    assert values[1,0,0]==8 and values[1,0,1]==2
    assert values[2].mask.tolist()==[[False,True,True,True]]
    assert values[2,0,0]==0
    assert values[3].mask.tolist()==[[False,True,True,True]]


@pytest.mark.parametrize("expression",["__import__('os')","a.__class__","a[0]","[x for x in a]",
    "open('file')","lambda: 1","sqrt(a,2)","where(a,1)","a if a else 0","'text'","float('nan')"])
def test_expressions_reject_python_execution(expression):
    with pytest.raises(ValueError):Expression(expression)


def test_arithmetic_domain_logic_and_bitmask(write_raster,tmp_path):
    a=write_raster("values.tif",np.array([[-1,0,1,4]],dtype="float64"))
    output=cm.calculate({"root":"sqrt(a)","log":"log(a)","logic":"(0 <= a < 3) & (a != 0)",
                         "bits":"bitand(a+1, 1)","constant":"pi"},{"a":a},tmp_path/"functions.tif")
    data=read(output)
    assert data[0].mask.tolist()==[[True,False,False,False]]
    assert data[1].mask.tolist()==[[True,True,False,False]]
    assert data[2].tolist()==[[0,0,1,0]]
    assert data[3].tolist()==[[0,1,0,1]]
    np.testing.assert_allclose(data[4],np.pi)


def test_calibration_and_float_output_overflow(write_raster,tmp_path):
    raw=write_raster("raw.tif",np.array([[0,1000,2000]],dtype="uint16"),nodata=0)
    with rasterio.open(raw,"r+") as src:src.scales=(.001,);src.offsets=(-1.,)
    p=cm.calculate("a",{"a":raw},tmp_path/"calibrated.tif")
    assert read(p)[0].tolist()==[[None,0,1]]
    p=cm.calculate("a",{"a":cm.Band(raw,scale=.01,offset=0)},tmp_path/"explicit.tif")
    assert read(p)[0].tolist()==[[None,10,20]]
    p=cm.calculate("1e100",{"a":raw},tmp_path/"overflow.tif")
    assert read(p).count()==0


def test_parallel_batch_matches_serial_and_metadata(write_raster,tmp_path):
    values=np.arange(75*90,dtype="float32").reshape(75,90)/100
    a=write_raster("raster.tif",values)
    expressions={"ratio":"(a-1)/(a+1)","scaled":"a*2","mask":"where(a>3, 1, 0)"}
    progress=[]
    one=cm.calculate(expressions,{"a":a},tmp_path/"one.tif",block_size=32)
    many=cm.calculate(expressions,{"a":a},tmp_path/"many.tif",block_size=32,workers=3,progress=lambda d,t:progress.append((d,t)))
    np.testing.assert_array_equal(read(one),read(many))
    assert progress[0]==(0,9) and progress[-1]==(9,9)
    with rasterio.open(many) as src:
        assert src.descriptions==tuple(expressions) and src.tags()["workers"]=="3"
        assert json.loads(src.tags()["processing"])["expressions"]==expressions


def test_alignment_requires_explicit_request(write_raster,tmp_path):
    a=write_raster("a.tif",np.ones((2,4),dtype="float32"))
    b=write_raster("b.tif",np.full((1,2),3,dtype="float32"),transform=from_origin(300000,9500000,20,20))
    with pytest.raises(ValueError,match="grids differ"):cm.calculate("a+b",{"a":a,"b":b},tmp_path/"bad.tif")
    p=cm.calculate("a+b",{"a":a,"b":b},tmp_path/"aligned.tif",align=True)
    np.testing.assert_array_equal(read(p),4)


def test_cancellation_preserves_existing_output(write_raster,tmp_path):
    a=write_raster("input.tif",np.ones((96,96),dtype="float32"))
    output=tmp_path/"output.tif";output.write_bytes(b"existing output")
    cancel=threading.Event()
    def progress(done,total):
        if done==1:cancel.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.calculate("a*2",{"a":a},output,overwrite=True,workers=2,block_size=32,progress=progress,cancel=cancel)
    assert output.read_bytes()==b"existing output"
    assert not list(tmp_path.glob(".cartomize-*"))


def test_budget_protection_and_missing_inputs(write_raster,tmp_path):
    a=write_raster("input.tif",np.ones((5,5),dtype="float32"))
    with pytest.raises(ValueError,match="Missing raster variables"):cm.calculate("missing+1",{"a":a},tmp_path/"bad.tif")
    with pytest.raises(ValueError,match="differ"):cm.calculate("a",{"a":a},a,overwrite=True)
    output=cm.calculate("a+1",{"a":a},tmp_path/"budget.tif",workers=4,block_size=2048,memory_limit_mb=16)
    with rasterio.open(output) as src:assert float(src.tags()["estimated_working_mb"])<=16


def test_temporal_statistics_skip_missing_and_enforce_count(write_raster,tmp_path):
    a=write_raster("a.tif",np.array([[1,-9999,3,-9999]],dtype="float32"))
    b=write_raster("b.tif",np.array([[3,4,-9999,-9999]],dtype="float32"))
    p=cm.reduce_rasters([a,b],tmp_path/"mean.tif")
    assert read(p)[0].tolist()==[[2,4,3,None]]
    p=cm.reduce_rasters([a,b],tmp_path/"strict.tif",statistic="median",min_valid=2)
    assert read(p)[0].tolist()==[[2,None,None,None]]
    p=cm.reduce_rasters([a,b],tmp_path/"count.tif",statistic="count")
    assert read(p)[0].tolist()==[[2,1,1,0]]


@pytest.mark.parametrize("statistic",["mean","sum","min","max","std","range","count"])
def test_focal_halo_and_edges_against_explicit_neighbours(write_raster,tmp_path,statistic):
    values=np.arange(37*42,dtype="float64").reshape(37,42)+1e6
    values[12,11]=-9999;values[32,31]=-9999
    source=write_raster("surface.tif",values)
    result=read(cm.focal(source,tmp_path/"focal.tif",statistic=statistic,size=5,block_size=32,workers=2,dtype="float64"))[0]
    for row,col in [(0,0),(15,22),(31,32),(32,32),(36,41)]:
        neighbourhood=values[max(0,row-2):row+3,max(0,col-2):col+3]
        valid=neighbourhood[neighbourhood!=-9999]
        expected=len(valid) if statistic=="count" else np.ptp(valid) if statistic=="range" else getattr(np,statistic)(valid)
        assert result[row,col]==pytest.approx(expected,abs=1e-6)
    assert result.mask[12,11] and result.mask[32,31]


def test_indices_named_bands_parameters_and_custom_formula(write_raster,tmp_path):
    source=write_raster("spectral.tif",np.array([[[.1,.2]],[[.2,.3]],[[.6,.8]],[[.4,.5]]],dtype="float32"))
    with rasterio.open(source,"r+") as src:src.descriptions=("blue","red","nir","swir1")
    p=cm.spectral_indices(source,tmp_path/"indices.tif",["NDVI","EVI","SAVI","NDMI"],parameters={"SAVI":{"L":.2}})
    data=read(p)
    assert data[0,0,0]==pytest.approx(.5)
    assert data[1,0,0]==pytest.approx(2.5*(.6-.2)/(.6+6*.2-7.5*.1+1))
    assert data[2,0,0]==pytest.approx(1.2*(.6-.2)/(.6+.2+.2))
    cm.register_index("TEST_DIFFERENCE","nir-red",bands=["nir","red"],title="Différence spectrale",replace=True)
    p=cm.spectral_indices(source,tmp_path/"custom.tif","TEST_DIFFERENCE")
    assert read(p)[0,0,0]==pytest.approx(.4)
    with pytest.raises(ValueError,match="swir2"):cm.spectral_indices(source,tmp_path/"missing.tif","NBR")


def test_cli_calculator_and_catalog(write_raster,tmp_path,capsys):
    from cartomize.cli import main
    path=write_raster("data.tif",np.array([[2,3]],dtype="float32"))
    assert main(["calculate","x*2",str(tmp_path/"cli.tif"),"--input","x",str(path),"1"])==0
    assert read(tmp_path/"cli.tif")[0].tolist()==[[4,6]]
    capsys.readouterr()
    assert main(["indices"])==0
    assert "NDVI" in {i["name"] for i in json.loads(capsys.readouterr().out)}
