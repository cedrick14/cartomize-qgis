from pathlib import Path
import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
import cartomize as cm


def scene(write_raster,ident,red,nir,*,x=300000,date="2026-08-17",quality=None,resolution=10):
    transform=from_origin(x,9500000,resolution,resolution)
    return cm.Scene(ident,{"red":write_raster(ident+"_red.tif",np.asarray(red,dtype="float32"),transform=transform),
                           "nir":write_raster(ident+"_nir.tif",np.asarray(nir,dtype="float32"),transform=transform)},
                    sensor="test",acquired=date,quality=quality,quality_kind="valid_mask" if quality else None)


def test_adjacent_mosaics_stack_named_bands_and_provenance(write_raster,tmp_path):
    a=scene(write_raster,"A",[[1,2]],[[11,12]])
    b=scene(write_raster,"B",[[3,4]],[[13,14]],x=300020)
    product=cm.prepare_imagery([a,b],tmp_path/"mosaic.tif",band_order=["red","nir"],mask_clouds=False)
    with rasterio.open(product.path) as src:
        assert src.count==2 and src.shape==(1,4)
        assert src.descriptions==("red","nir")
        assert src.read().tolist()==[[[1,2,3,4]],[[11,12,13,14]]]
    with rasterio.open(product.source_index) as src:
        assert src.read(1).tolist()==[[1,1,2,2]]
    manifest=json.loads(product.manifest.read_text())
    assert manifest["coverage_percent"]==100
    assert manifest["scenes"][0]["contributed_pixels"]==2


def test_overlap_never_mixes_bands_between_scenes(write_raster,tmp_path):
    a=scene(write_raster,"A",[[1,2]],[[11,-9999]])
    b=scene(write_raster,"B",[[3,4]],[[13,14]])
    product=cm.prepare_imagery([a,b],tmp_path/"first.tif",mask_clouds=False)
    with rasterio.open(product.path) as src:
        assert src.read().tolist()==[[[1,4]],[[11,14]]]
    product=cm.prepare_imagery([a,b],tmp_path/"last.tif",overlap="last",mask_clouds=False)
    with rasterio.open(product.path) as src:
        assert src.read().tolist()==[[[3,4]],[[13,14]]]


def test_mask_before_interpolation_prevents_cloud_bleed(write_raster,tmp_path):
    qa=write_raster("valid.tif",np.array([[1,0]],dtype="uint8"),nodata=None)
    a=scene(write_raster,"A",[[1,10000]],[[2,10000]],quality=qa)
    product=cm.prepare_imagery([a],tmp_path/"masked.tif",resolution=5,resampling="bilinear")
    with rasterio.open(product.path) as src:
        values=src.read(masked=True)
        assert np.max(values[0].compressed())==pytest.approx(1)
        assert np.max(values[1].compressed())==pytest.approx(2)
    assert product.report["upsampled_bands"]


def test_common_resolution_and_clip_polygon_hole(write_raster,tmp_path):
    red=write_raster("red.tif",np.ones((4,4),dtype="float32"))
    nir=write_raster("nir.tif",np.full((2,2),3,dtype="float32"),transform=from_origin(300000,9500000,20,20))
    a=cm.Scene("A",{"red":red,"nir":nir},sensor="test",acquired="2026-08-17")
    aoi=cm.GeoDataFrame(geometry=[box(300000,9499960,300040,9500000).difference(box(300020,9499980,300040,9500000))],crs=32733)
    product=cm.prepare_imagery([a],tmp_path/"coarse.tif",aoi=aoi,mask_clouds=False)
    assert product.report["resolution_m"]==pytest.approx(20)
    assert product.report["aoi_pixels"]==3
    with rasterio.open(product.path) as src:
        assert src.shape==(2,2)
        assert src.read(1,masked=True).count()==3


def test_explicit_calibration_preserves_valid_zero(write_raster,tmp_path):
    raw=write_raster("reflectance.tif",np.array([[0,1000,2000]],dtype="uint16"),nodata=0)
    a=cm.Scene("A",{"red":cm.Band(raw,scale=.001,offset=-1,nodata=0,unit="reflectance")},sensor="test")
    product=cm.prepare_imagery([a],tmp_path/"scaled.tif",mask_clouds=False)
    with rasterio.open(product.path) as src:
        values=src.read(1,masked=True)
        assert values.mask.tolist()==[[True,False,False]]
        assert values[0,1]==0 and values[0,2]==1


@pytest.mark.parametrize("kind,quality,expected",[
    ("landsat_qa",[64,72,80,96,66,68,192],[True,False,False,False,False,False,True]),
    ("sentinel_scl",[4,8,9,10,3,11,6],[True,False,False,False,False,False,True]),
])
def test_quality_flags(write_raster,tmp_path,kind,quality,expected):
    from cartomize.imagery import _quality_valid
    assert _quality_valid(np.ma.array([quality]),kind).tolist()==[expected]


def test_saturation_mask(write_raster,tmp_path):
    raw=write_raster("raw.tif",np.array([[1,2]],dtype="float32"))
    qa=write_raster("sat.tif",np.array([[0,8]],dtype="uint16"),nodata=None)
    a=cm.Scene("A",{"red":raw},sensor="test",saturation=qa)
    product=cm.prepare_imagery([a],tmp_path/"sat_result.tif",mask_clouds=False)
    with rasterio.open(product.path) as src:
        assert src.read(1,masked=True).mask.tolist()==[[False,True]]


def test_incompatible_scenes_missing_bands_and_dates(write_raster,tmp_path):
    a=scene(write_raster,"A",[[1]],[[2]])
    b=scene(write_raster,"B",[[3]],[[4]],date="2026-08-18")
    with pytest.raises(ValueError,match="Dates"):
        cm.prepare_imagery([a,b],tmp_path/"wrong.tif",mask_clouds=False)
    product=cm.prepare_imagery([a,b],tmp_path/"dates.tif",mask_clouds=False,allow_mixed_dates=True)
    assert len(product.report["dates"])==2
    c=cm.Scene("C",a.bands,sensor="other",acquired=a.acquired)
    with pytest.raises(ValueError,match="sensors"):
        cm.prepare_imagery([a,c],tmp_path/"wrong.tif",mask_clouds=False)
    with pytest.raises(ValueError,match="lacks bands"):
        cm.prepare_imagery([a],tmp_path/"wrong.tif",band_order=["swir2"],mask_clouds=False)
    with pytest.raises(ValueError,match="no quality"):
        cm.prepare_imagery([a],tmp_path/"wrong.tif")


def test_no_overlap_creates_no_final_product(write_raster,tmp_path):
    a=scene(write_raster,"A",[[1]],[[2]])
    aoi=cm.GeoDataFrame(geometry=[box(400000,9400000,400020,9400020)],crs=32733)
    with pytest.raises(ValueError,match="No valid pixels"):
        cm.prepare_imagery([a],tmp_path/"empty.tif",aoi=aoi,mask_clouds=False)
    assert not (tmp_path/"empty.tif").exists()
    assert not (tmp_path/"empty.json").exists()
    assert not list(tmp_path.glob(".cartomize-scenes-*"))


def test_overwrite_guard_and_pixel_budget(write_raster,tmp_path):
    a=scene(write_raster,"A",[[1,1]],[[2,2]])
    with pytest.raises(ValueError,match="Output grid"):
        cm.prepare_imagery([a],tmp_path/"big.tif",max_pixels=1,mask_clouds=False)
    product=cm.prepare_imagery([a],tmp_path/"existing.tif",mask_clouds=False)
    old=product.path.read_bytes()
    with pytest.raises(FileExistsError):
        cm.prepare_imagery([a],product.path,mask_clouds=False)
    assert product.path.read_bytes()==old


def test_landsat_discovery_and_band_semantics(write_raster,tmp_path):
    prefix="LC08_L2SP_181063_20260817_20260820_02_T1"
    for name in ["SR_B2","SR_B3","SR_B4","SR_B5","QA_PIXEL"]:
        write_raster(f"{prefix}_{name}.TIF",np.ones((2,2),dtype="uint16"),nodata=0)
    scenes=cm.discover_scenes(tmp_path)
    assert len(scenes)==1
    assert scenes[0].acquired=="2026-08-17" and scenes[0].sensor=="landsat-8"
    assert set(scenes[0].bands)=={"blue","green","red","nir"}
    assert scenes[0].bands["red"].scale==.0000275
    assert scenes[0].bands["red"].offset==-.2
    assert scenes[0].quality.name.endswith("QA_PIXEL.TIF")


def test_sentinel_discovery_reads_offsets_and_resolution_variants(write_raster,tmp_path):
    (tmp_path/"MTD_MSIL2A.xml").write_text('<root><PROCESSING_BASELINE>04.00</PROCESSING_BASELINE><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE><BOA_ADD_OFFSET band_id="1">-1000</BOA_ADD_OFFSET></root>')
    for resolution in [10,20]:
        write_raster(f"T33MUP_20260817T091031_B02_{resolution}m.tif",np.ones((2,2),dtype="uint16"),nodata=0)
    scenes=cm.discover_scenes(tmp_path)
    assert scenes[0].bands["blue"].path.name.endswith("10m.tif")
    assert scenes[0].bands["blue"].scale==.0001
    assert scenes[0].bands["blue"].offset==-.1


def test_discovery_does_not_guess_unknown_sensor_or_offset(write_raster,tmp_path):
    path=write_raster("arbitrary_B2.tif",np.ones((2,2),dtype="uint16"),nodata=0)
    with pytest.raises(ValueError,match="Unrecognized"):
        cm.discover_scenes([path])
    s2=write_raster("T33MUP_20260817T091031_B02_10m.tif",np.ones((2,2),dtype="uint16"),nodata=0)
    with pytest.raises(ValueError,match="MTD_MSIL2A"):
        cm.discover_scenes([s2])


def test_rgb_semantics_masks_and_native_rgba(write_raster,tmp_path):
    array=np.array([[[0,1,-9999]],[[2,3,4]],[[4,5,6]]],dtype="float32")
    source=write_raster("rgb.tif",array)
    with rasterio.open(source,"r+") as src:src.descriptions=("red","green","blue")
    rgba,_,report=cm.read_rgb(source,percentiles=(0,100))
    assert report["bands"]==(1,2,3)
    assert rgba[0,0,0]==0 and rgba[0,0,3]==255
    assert rgba[0,2,3]==0
    out=cm.color_composite(source,tmp_path/"display.tif",percentiles=(0,100))
    with rasterio.open(out) as src:
        assert src.count==4 and src.nodata is None
        assert tuple(c.name for c in src.colorinterp)==("red","green","blue","alpha")
    native,_,_=cm.read_rgb(out,bands="native")
    assert native[0,0,3]==255 and native[0,2,3]==0


def test_named_false_color_and_missing_band(write_raster):
    source=write_raster("multi.tif",np.ones((4,2,2),dtype="float32"))
    with rasterio.open(source,"r+") as src:src.descriptions=("blue","green","red","nir")
    assert cm.read_rgb(source,bands="vegetation")[2]["bands"]==(4,3,2)
    with pytest.raises(ValueError,match="missing"):
        cm.read_rgb(source,bands="swir")


def test_rgb_reprojection_respects_individual_band_nodata(write_raster):
    data=np.full((3,8,8),2,dtype="float32")
    data[0,:,4:]=-9999
    data[0,:,:4]=0
    path=write_raster("reproject_rgb.tif",data)
    rgba,_,_=cm.read_rgb(path,bands=(1,2,3),crs=32732)
    assert (rgba[...,3]==0).any() and (rgba[...,3]==255).any()
    # Constant valid channels must stretch to middle gray, never from -9999.
    assert set(rgba[...,0][rgba[...,3]>0])=={128}


def test_nan_nodata_manifest_is_strict_json(write_raster,tmp_path):
    raw=write_raster("nan_input.tif",np.array([[np.nan,1]],dtype="float32"),nodata=np.nan)
    s=cm.Scene("A",{"red":cm.Band(raw,nodata=np.nan)},sensor="test")
    product=cm.prepare_imagery([s],tmp_path/"nan_output.tif",mask_clouds=False)
    report=json.loads(product.manifest.read_text(),parse_constant=lambda v:pytest.fail("Nonstandard JSON"))
    assert report["assets"][0]["declared_nodata"]=="NaN" and report["valid_pixels"]==1


def test_cli_discovery_preparation_and_composite(write_raster,tmp_path,capsys):
    from cartomize.cli import main
    prefix="LC08_L2SP_181063_20260817_20260820_02_T1"
    for band in [2,3,4]:
        write_raster(f"{prefix}_SR_B{band}.TIF",np.full((2,2),10000+band*100,dtype="uint16"),nodata=0)
    write_raster(f"{prefix}_QA_PIXEL.TIF",np.full((2,2),64,dtype="uint16"),nodata=0)
    assert main(["scenes",str(tmp_path)])==0
    assert json.loads(capsys.readouterr().out)[0]["sensor"]=="landsat-8"
    output=tmp_path/"prepared.tif"
    assert main(["prepare",str(tmp_path),str(output),"--bands","blue,green,red"])==0
    assert json.loads(capsys.readouterr().out)["coverage_percent"]==100
    with rasterio.open(output) as src:
        assert src.read(3)[0,0]==pytest.approx(10400*.0000275-.2)
    assert main(["composite",str(output),str(tmp_path/"display.tif")])==0
