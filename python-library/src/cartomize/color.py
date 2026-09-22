"""Natural/false-colour rendering without modifying scientific band values."""
from pathlib import Path
from contextlib import ExitStack
import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.vrt import WarpedVRT

from .raster import _writer


COMPOSITIONS = {
    "natural": ("red","green","blue"),
    "vegetation": ("nir","red","green"),
    "swir": ("swir2","nir","red"),
    "agriculture": ("swir1","nir","blue"),
}


def resolve_rgb(src,bands="natural"):
    """Resolve semantic band names or three explicit 1-based indices."""
    if isinstance(bands,str):
        if bands=="native":
            if src.count<3 or src.dtypes[:3] != ("uint8",)*3:
                raise ValueError("Native RGB display requires three uint8 channels.")
            return (1,2,3)
        if bands not in COMPOSITIONS:
            raise ValueError(f"Choose a composition from {list(COMPOSITIONS)} or three band indices.")
        bands=COMPOSITIONS[bands]
    if len(bands)!=3:
        raise ValueError("RGB requires exactly three bands, ordered red/green/blue display channels.")
    descriptions=[(d or src.tags(i).get("semantic_name","")).casefold() for i,d in enumerate(src.descriptions,1)]
    indices=[]
    for value in bands:
        if isinstance(value,str):
            matches=[i+1 for i,d in enumerate(descriptions) if d==value.casefold()]
            if len(matches)!=1:
                raise ValueError(f"Band '{value}' is missing/ambiguous. Supply explicit indices or a named multiband product.")
            indices.append(matches[0])
        elif isinstance(value,int) and 1<=value<=src.count:
            indices.append(value)
        else:
            raise ValueError("RGB band indices must be valid positive integers.")
    return tuple(indices)


def _stretch_limits(cube,percentiles):
    if len(percentiles)!=2 or not 0<=percentiles[0]<percentiles[1]<=100:
        raise ValueError("percentiles must satisfy 0 <= low < high <= 100.")
    valid=np.isfinite(cube).all(axis=0)
    if not valid.any():
        return [(0.,1.)]*3
    return [tuple(map(float,np.percentile(band[valid],percentiles))) for band in cube]


def _rgba(cube,limits,gamma):
    if not np.isfinite(gamma) or gamma<=0:
        raise ValueError("gamma must be positive and finite.")
    valid=np.isfinite(cube).all(axis=0)
    rgba=np.zeros((*cube.shape[1:],4),dtype="uint8")
    for k,(low,high) in enumerate(limits):
        values=np.nan_to_num(cube[k],nan=low,posinf=low,neginf=low)
        normalized=np.clip((values-low)/(high-low),0,1) if high>low else np.full(values.shape,.5)
        rgba[...,k]=np.round(normalized**(1/gamma)*255).astype("uint8")
    rgba[...,3]=valid.astype("uint8")*255
    return rgba


def read_rgb(source,*,bands="natural",crs=None,max_size=2048,percentiles=(2,98),gamma=1.):
    """Return (RGBA preview, imshow extent, display metadata).

    Stretch percentiles are estimated on the bounded preview. Missing pixels
    in any channel become transparent; valid zeros remain valid.
    """
    if not isinstance(max_size,int) or max_size<1:
        raise ValueError("max_size must be a positive integer.")
    with ExitStack() as stack:
        src=stack.enter_context(rasterio.open(source))
        if src.crs is None:
            raise ValueError("RGB raster needs a CRS.")
        indices=resolve_rgb(src,bands)
        # Preserve per-band NoData even when another channel is valid there.
        # Pass GDAL warp options directly (not a nested warp_extras dict).
        north_up=not (src.transform.b or src.transform.d) and src.transform.a>0 and src.transform.e<0
        vrt=src if (crs is None or rasterio.crs.CRS.from_user_input(crs)==src.crs) and north_up else stack.enter_context(
            WarpedVRT(src,crs=crs or src.crs,dtype="float64",nodata=np.nan,UNIFIED_SRC_NODATA="NO"))
        ratio=min(1,max_size/max(vrt.width,vrt.height))
        cube=np.ma.masked_invalid(vrt.read(indices,masked=True,
                     out_shape=(3,max(1,int(vrt.height*ratio)),max(1,int(vrt.width*ratio)))).astype("float64")).filled(np.nan)
        extent=(vrt.bounds.left,vrt.bounds.right,vrt.bounds.bottom,vrt.bounds.top)
        limits=[(0.,255.)]*3 if bands=="native" else _stretch_limits(cube,percentiles)
        return _rgba(cube,limits,gamma),extent,{"bands":indices,"limits":limits,"percentiles":percentiles,"gamma":gamma,"sampled_pixels":cube.shape[1]*cube.shape[2]}


def color_composite(source,destination,*,bands="natural",percentiles=(2,98),gamma=1.,overwrite=False,progress=None,cancel=None):
    """Write a four-band uint8 RGBA GeoTIFF for display; retain source bands.

    The RGB byte channels are display values, not surface reflectance.
    Alpha encodes validity; zero RGB intensity is never declared NoData.
    """
    from .imagery import _check_cancel
    _check_cancel(cancel)
    _,_,display=read_rgb(source,bands=bands,percentiles=percentiles,gamma=gamma)
    with rasterio.open(source) as src:
        profile=dict(driver="GTiff",width=src.width,height=src.height,count=4,dtype="uint8",
                     transform=src.transform,crs=src.crs,nodata=None,compress="lzw",tiled=True,
                     blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
        with _writer(destination,profile,overwrite=overwrite,sources=(source,)) as dst:
            total=((src.width+255)//256)*((src.height+255)//256)
            for number,(_,window) in enumerate(dst.block_windows(1),1):
                _check_cancel(cancel)
                cube=np.ma.masked_invalid(src.read(display["bands"],window=window,masked=True).astype("float64")).filled(np.nan)
                dst.write(np.moveaxis(_rgba(cube,display["limits"],gamma),-1,0),window=window)
                if progress:progress(number,total)
            dst.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
            dst.descriptions=("red_display","green_display","blue_display","alpha")
            dst.update_tags(CARTOMIZE_PRODUCT="display_rgba",source_bands=str(display["bands"]),
                            stretch_limits=str(display["limits"]),percentiles=str(percentiles),gamma=gamma)
            _check_cancel(cancel)
    return Path(destination)
