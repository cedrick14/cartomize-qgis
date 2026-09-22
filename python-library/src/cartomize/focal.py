"""Focal statistics with overlapping block margins and NoData accounting."""
import numpy as np
from scipy.ndimage import uniform_filter, minimum_filter, maximum_filter
from .algebra import _run_blocks
from .scenes import Band


def focal(source,destination,*,statistic="mean",size=3,band=1,min_valid=1,
          preserve_nodata=True,**options):
    """Square moving window in pixels; outside-grid cells never contribute.

    Mean, sum, standard deviation, minimum, maximum, range and count are
    available. Standard deviation is population SD. Halo reads eliminate
    discontinuities at processing-block boundaries. By default, missing
    centre pixels remain missing even if valid neighbours are available.
    """
    if statistic not in {"mean","sum","std","min","max","range","count"}:raise ValueError("Invalid focal statistic.")
    if not isinstance(size,int) or not 1<=size<=255 or size%2!=1:raise ValueError("Window size must be an odd integer in 1..255.")
    if not isinstance(min_valid,int) or not 1<=min_valid<=size*size:raise ValueError("Invalid minimum valid neighbour count.")
    def process(values):
        a=values["raster"];valid=~np.ma.getmaskarray(a)&np.isfinite(a.data)
        count=np.rint(uniform_filter(valid.astype("float64"),size=size,mode="constant",cval=0)*size*size)
        eligible=count>=min_valid
        if preserve_nodata:eligible &= valid
        if statistic=="count":result=count
        elif statistic in {"min","max","range"}:
            low=minimum_filter(np.where(valid,a.data,np.inf),size=size,mode="constant",cval=np.inf)
            high=maximum_filter(np.where(valid,a.data,-np.inf),size=size,mode="constant",cval=-np.inf)
            with np.errstate(invalid="ignore"):result=low if statistic=="min" else high if statistic=="max" else high-low
        else:
            anchor=float(a.data[valid][0]) if valid.any() else 0.
            centered=np.where(valid,a.data-anchor,0.)
            total=uniform_filter(centered,size=size,mode="constant",cval=0)*size*size
            with np.errstate(divide="ignore",invalid="ignore",over="ignore"):
                mean=total/count
                if statistic=="std":
                    squares=uniform_filter(centered**2,size=size,mode="constant",cval=0)*size*size
                    result=np.sqrt(np.maximum(0,squares/count-mean**2))
                else:result=mean+anchor if statistic=="mean" else total+anchor*count
        return [np.ma.array(result,mask=~eligible)]
    asset=source if isinstance(source,(Band,tuple,list)) else (source,band)
    return _run_blocks({"raster":asset},destination,[f"focal_{statistic}"],process,halo=size//2,
         metadata={"operation":"focal_statistics","statistic":statistic,"window_size":size,
                   "min_valid":min_valid,"preserve_nodata":preserve_nodata},**options)
