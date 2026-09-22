"""Windowed, spectrally coherent multiscene mosaics and multiband products."""
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import tempfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_bounds
from pyproj import CRS

from .scenes import Scene, Band, discover_scenes
from .raster import _writer, _read, _band
from ._validation import frame, linear_factor, output_path


@dataclass(frozen=True)
class PreparedImage:
    path: Path
    source_index: Path
    manifest: Path
    bands: tuple[str, ...]
    report: dict


def _quality_valid(values, kind):
    valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
    raw = np.nan_to_num(values.filled(0), nan=0).astype("uint32")
    if kind == "landsat_qa":
        # C2 fill, dilated cloud, cirrus (8/9), cloud, shadow and snow.
        valid &= (raw & 63) == 0
    elif kind == "sentinel_scl":
        # Keep dark areas, vegetation, bare soil, water and unclassified.
        valid &= np.isin(raw, [2,4,5,6,7])
    elif kind == "valid_mask":
        valid &= raw != 0
    elif kind == "saturation":
        valid &= raw == 0
    else:
        raise ValueError("Unknown quality mask type.")
    return valid


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        from .algebra import ProcessingCancelled
        raise ProcessingCancelled("Traitement interrompu.")


def _calibrate(asset, scene, destination, mask_clouds, mask_saturation, cancel=None):
    """Mask/calibrate on the native grid *before* spectral interpolation."""
    with ExitStack() as stack:
        src = stack.enter_context(rasterio.open(asset.path))
        _band(src, asset.index)
        profile = dict(driver="GTiff",width=src.width,height=src.height,count=1,
                       transform=src.transform,crs=src.crs,dtype="float32",nodata=np.nan,
                       tiled=True,blockxsize=256,blockysize=256,compress="lzw",BIGTIFF="IF_SAFER")
        masks=[]
        requested = [(scene.quality,scene.quality_kind)] if mask_clouds else []
        if mask_saturation and scene.saturation:
            requested.append((scene.saturation,"saturation"))
        for path,kind in requested:
            quality=stack.enter_context(rasterio.open(path))
            if quality.crs is None:
                raise ValueError(f"Quality mask has no CRS: {path}")
            vrt=stack.enter_context(WarpedVRT(quality,crs=src.crs,transform=src.transform,
                         width=src.width,height=src.height,resampling=Resampling.nearest,dtype="float64",nodata=np.nan))
            masks.append((vrt,kind))
        with rasterio.open(destination,"w",**profile) as dst:
            for _,window in dst.block_windows(1):
                _check_cancel(cancel)
                values=_read(src,asset.index,window=window).astype("float64")
                valid=~np.ma.getmaskarray(values)
                if asset.nodata is not None:
                    valid &= values.data != asset.nodata
                for quality,kind in masks:
                    valid &= _quality_valid(_read(quality,1,window=window),kind)
                calibrated=values.data*asset.scale+asset.offset
                valid &= np.isfinite(calibrated)
                dst.write(np.where(valid,calibrated,np.nan).astype("float32"),1,window=window)


def prepare_imagery(scenes, destination, *, aoi=None, band_order=None,
                    target_crs=None, resolution=None, overlap="first",
                    resampling="nearest", mask_clouds=True, mask_saturation=True,
                    allow_mixed_dates=False, all_touched=False,
                    max_pixels=250_000_000, overwrite=False, progress=None, cancel=None):
    """Mosaic scenes, stack spectral bands and clip to an AOI on one grid.

    Resolution is in metres; default is the coarsest selected native resolution
    transformed to the target projected CRS. No new detail is inferred by
    oversampling. Dates/sensors/levels must agree unless mixed dates are explicit.

    Overlap first/last chooses one valid scene for *all* bands of each pixel.
    Bands are calibrated and cloud-masked before warping. The result includes
    a source-scene index raster and a JSON processing manifest.
    """
    _check_cancel(cancel)
    if isinstance(scenes,(str,Path)):
        scenes=discover_scenes(scenes)
    scenes=list(scenes)
    if not scenes or not all(isinstance(s,Scene) for s in scenes):
        raise ValueError("Provide Scene objects or a directory of supported scenes.")
    if len(scenes)>65534 or len({s.scene_id for s in scenes}) != len(scenes):
        raise ValueError("Use at most 65534 scenes with unique ids.")
    if len({s.sensor for s in scenes}) != 1 or len({s.level for s in scenes}) != 1:
        raise ValueError("Mixed sensors or processing levels need explicit harmonization before mosaicking.")
    dates={s.acquired for s in scenes}
    if not allow_mixed_dates and (len(dates)>1 or (len(scenes)>1 and None in dates)):
        raise ValueError("Dates differ or are unknown. Set allow_mixed_dates=True only for an intentional multitemporal mosaic.")
    if overlap not in {"first","last"}:
        raise ValueError("overlap must be 'first' or 'last' to preserve spectral coherence.")
    if resampling not in {"nearest","bilinear","cubic","average"}:
        raise ValueError("Unsupported spectral resampling method.")
    names=tuple(band_order) if band_order is not None else tuple(scenes[0].bands)
    if not names or len(set(names)) != len(names):
        raise ValueError("Choose at least one unique band name.")
    sources=[]; records=[]
    crs=CRS.from_user_input(target_crs) if target_crs else None
    for scene in scenes:
        missing=set(names)-set(scene.bands)
        if missing:
            raise ValueError(f"Scene {scene.scene_id} lacks bands: {sorted(missing)}.")
        if mask_clouds and scene.quality is None:
            raise ValueError(f"Scene {scene.scene_id} has no quality mask. Supply QA/SCL or explicitly set mask_clouds=False.")
        for name in names:
            asset=scene.bands[name]
            sources.append(asset.path)
            with rasterio.open(asset.path) as src:
                _band(src,asset.index)
                if src.crs is None:
                    raise ValueError(f"No source CRS: {asset.path}")
                if crs is None:crs=CRS.from_user_input(src.crs)
                factor=linear_factor(crs)
                transform,_,_=calculate_default_transform(src.crs,crs,src.width,src.height,*src.bounds)
                native_resolution=max(abs(transform.a),abs(transform.e))*factor
                bounds=transform_bounds(src.crs,crs,*src.bounds,densify_pts=21)
                if not np.isfinite(bounds).all():
                    raise ValueError("The chosen projection cannot represent a scene extent.")
                records.append({"scene":scene.scene_id,"band":name,"path":str(Path(asset.path).resolve()),
                                "index":asset.index,"scale":asset.scale,"offset":asset.offset,"unit":asset.unit,
                                "declared_nodata":("NaN" if asset.nodata is not None and np.isnan(asset.nodata) else asset.nodata),"source_crs":str(src.crs),
                                "resolution_m":native_resolution,"bounds":bounds,
                                "size_bytes":Path(asset.path).stat().st_size})
        sources.extend(p for p in (scene.quality,scene.saturation) if p)
    for name in names:
        if len({s.bands[name].unit for s in scenes}) != 1:
            raise ValueError(f"Incompatible physical units for {name}.")
    factor=linear_factor(crs)
    resolution=float(resolution) if resolution is not None else max(r["resolution_m"] for r in records)
    if not np.isfinite(resolution) or resolution<=0:
        raise ValueError("resolution must be positive metres.")
    cell=resolution/factor
    geometries=None
    if aoi is not None:
        if isinstance(aoi,(str,Path)):sources.append(aoi)
        zones=frame(aoi).to_crs(crs)
        if zones.empty or zones.geometry.isna().any() or zones.geometry.is_empty.any() or not zones.geometry.is_valid.all():
            raise ValueError("AOI must contain valid nonempty polygons.")
        if not zones.geom_type.isin(["Polygon","MultiPolygon"]).all():
            raise ValueError("AOI must be polygonal.")
        geometries=list(zones.geometry)
        bounds=zones.total_bounds
    else:
        bounds=(min(r["bounds"][0] for r in records),min(r["bounds"][1] for r in records),
                max(r["bounds"][2] for r in records),max(r["bounds"][3] for r in records))
    left=math.floor(bounds[0]/cell+1e-9)*cell
    bottom=math.floor(bounds[1]/cell+1e-9)*cell
    right=math.ceil(bounds[2]/cell-1e-9)*cell
    top=math.ceil(bounds[3]/cell-1e-9)*cell
    width,height=round((right-left)/cell),round((top-bottom)/cell)
    if width<1 or height<1 or width*height>max_pixels:
        raise ValueError(f"Output grid is {width}×{height} pixels. Adjust AOI/resolution or max_pixels.")
    transform=from_origin(left,top,cell,cell)
    destination=output_path(destination,overwrite,sources)
    index_path=output_path(destination.with_name(destination.stem+"_source_index.tif"),overwrite,sources)
    manifest_path=output_path(destination.with_suffix(".json"),overwrite,sources)
    if destination in {index_path,manifest_path}:
        raise ValueError("Use a .tif output filename.")
    profile=dict(driver="GTiff",width=width,height=height,count=len(names),dtype="float32",
                 crs=crs,transform=transform,nodata=np.nan,compress="lzw",tiled=True,
                 blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
    counts=Counter(); aoi_pixels=0; valid_pixels=0
    progress_total=len(records)+math.ceil(width/256)*math.ceil(height/256);progress_done=0
    if progress:progress(0,progress_total)
    with tempfile.TemporaryDirectory(prefix=".cartomize-scenes-",dir=destination.parent) as temporary:
        work=Path(temporary)
        with ExitStack() as stack:
            readers=[]
            for scene_index,scene in enumerate(scenes):
                bands=[]
                for band_index,name in enumerate(names):
                    calibrated=work/f"s{scene_index}_b{band_index}.tif"
                    _calibrate(scene.bands[name],scene,calibrated,mask_clouds,mask_saturation,cancel)
                    progress_done+=1
                    if progress:progress(progress_done,progress_total)
                    src=stack.enter_context(rasterio.open(calibrated))
                    bands.append(stack.enter_context(WarpedVRT(src,crs=crs,transform=transform,width=width,height=height,
                                 dtype="float32",nodata=np.nan,resampling=Resampling[resampling])))
                readers.append(bands)
            staged=work/"product.tif"; staged_index=work/"source_index.tif"
            index_profile={**profile,"count":1,"dtype":"uint16","nodata":0}
            with rasterio.open(staged,"w",**profile) as dst, rasterio.open(staged_index,"w",**index_profile) as ids:
                for _,window in dst.block_windows(1):
                    _check_cancel(cancel)
                    shape=(int(window.height),int(window.width))
                    inside=geometry_mask(geometries,out_shape=shape,transform=dst.window_transform(window),
                                         invert=True,all_touched=all_touched) if geometries is not None else np.ones(shape,dtype=bool)
                    aoi_pixels+=int(inside.sum())
                    output=np.full((len(names),*shape),np.nan,dtype="float32")
                    chosen=np.zeros(shape,dtype="uint16")
                    for scene_index,bands in enumerate(readers,1):
                        cube=np.stack([_read(src,1,window=window).filled(np.nan) for src in bands])
                        valid=np.isfinite(cube).all(axis=0)&inside
                        if overlap=="first":valid &= chosen==0
                        output[:,valid]=cube[:,valid]
                        chosen[valid]=scene_index
                    dst.write(output,window=window);ids.write(chosen,1,window=window)
                    unique,n=np.unique(chosen[chosen>0],return_counts=True)
                    counts.update({int(k):int(v) for k,v in zip(unique,n)})
                    valid_pixels+=int((chosen>0).sum())
                    progress_done+=1
                    if progress:progress(progress_done,progress_total)
                dst.descriptions=names
                for k,name in enumerate(names,1):
                    dst.update_tags(k,semantic_name=name,unit=scenes[0].bands[name].unit)
                dst.update_tags(CARTOMIZE_PRODUCT="spectral_mosaic",sensor=scenes[0].sensor,
                                dates=",".join(sorted(d for d in dates if d)),overlap=overlap,
                                spectral_coherence="one_scene_per_pixel_all_bands",calibration="applied")
                ids.set_band_description(1,"source_scene_index")
        if valid_pixels==0:
            raise ValueError("No valid pixels in the AOI after masking and alignment; no product was saved.")
        from . import __version__
        report={"version":__version__,"product":str(destination),"source_index":str(index_path),
                "band_order":names,"crs":str(crs),"resolution_m":resolution,"width":width,"height":height,
                "transform":list(transform)[:6],"aoi_pixels":aoi_pixels,"valid_pixels":valid_pixels,
                "coverage_percent":100*valid_pixels/max(1,aoi_pixels),"overlap":overlap,"resampling":resampling,
                "mask_clouds":mask_clouds,"mask_saturation":mask_saturation,
                "dates":sorted(d for d in dates if d),"allow_mixed_dates":allow_mixed_dates,
                "upsampled_bands":[{"scene":r["scene"],"band":r["band"],"native_resolution_m":r["resolution_m"]}
                                    for r in records if r["resolution_m"]>resolution*1.001],
                "scenes":[{"index":i,"id":s.scene_id,"sensor":s.sensor,"level":s.level,"acquired":s.acquired,
                           "quality_mask":str(s.quality) if s.quality else None,"saturation_mask":str(s.saturation) if s.saturation else None,
                           "contributed_pixels":counts.get(i,0),"notes":s.notes} for i,s in enumerate(scenes,1)],
                "assets":records,"limitations":["No histogram matching or atmospheric correction is performed.",
                    "A multiband/color composite is not a land-cover classification.",
                    "Resampling to smaller pixels does not add native spatial detail."]}
        staged_manifest=work/"manifest.json"
        staged_manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        # All processing must succeed before replacing the final deliverables.
        _check_cancel(cancel)
        os.replace(staged_index,index_path);os.replace(staged_manifest,manifest_path);os.replace(staged,destination)
        for path in (index_path,destination):
            for suffix in ('.msk','.aux.xml','.ovr'):Path(str(path)+suffix).unlink(missing_ok=True)
    return PreparedImage(destination,index_path,manifest_path,names,report)
