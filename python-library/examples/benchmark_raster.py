"""Reproducible local benchmark on synthetic rasters; no universal speed claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
import cartomize as cm


NAMES=["NDVI","NDMI","NBR"]


def signatures(paths):
    hashes=[]
    for path,band in paths:
        digest=hashlib.sha256()
        with rasterio.open(path) as src:
            for row in range(0,src.height,128):
                data=src.read(band,window=Window(0,row,src.width,min(128,src.height-row)))
                # Canonical encodings: NaN payloads and signed zero are not
                # scientific differences. Finite nonzero values stay exact.
                data[np.isnan(data)]=np.float32(np.nan);data[data==0]=0.
                digest.update(data.tobytes())
        hashes.append(digest.hexdigest())
    return hashes


def run_case(source,out,mode):
    started=time.perf_counter();paths=[]
    if mode=="separate":
        for name,positive,negative in [("NDVI",2,1),("NDMI",2,3),("NBR",2,4)]:
            p=out/f"{name}.tif";cm.raster.normalized_difference(source,p,positive_band=positive,negative_band=negative,overwrite=True)
            paths.append((p,1))
    else:
        p=out/"indices.tif"
        cm.spectral_indices(source,p,NAMES,workers=1 if mode=="batch_serial" else 4,overwrite=True)
        paths=[(p,i) for i in range(1,4)]
    elapsed=time.perf_counter()-started
    rss=None
    if sys.platform=="linux":
        import resource
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    result=dict(mode=mode,seconds=elapsed,peak_rss_mb=rss,signatures=signatures(paths),
                output_bytes=sum(p.stat().st_size for p in {p for p,_ in paths}))
    for p in {p for p,_ in paths}:p.unlink()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size",type=int,default=2048);parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--directory",default="output/benchmark")
    parser.add_argument("--case",choices=["separate","batch_serial","batch_parallel"])
    args=parser.parse_args();out=Path(args.directory).resolve();out.mkdir(parents=True,exist_ok=True)
    source=out/"synthetic_reflectance.tif"
    if args.case:
        print(json.dumps(run_case(source,out,args.case)));return
    if args.size<32 or args.repeats<1:raise ValueError("Invalid benchmark dimensions or repeat count.")
    rng=np.random.default_rng(20260922)
    with rasterio.open(source,"w",driver="GTiff",width=args.size,height=args.size,count=4,dtype="float32",
        crs=32733,transform=from_origin(300000,9500000,30,30),nodata=np.nan,compress="lzw",predictor=3,
        tiled=True,blockxsize=256,blockysize=256) as dst:
        for _,window in dst.block_windows(1):
            shape=(4,int(window.height),int(window.width))
            data=(rng.random(shape)*.35+np.array([.1,.4,.2,.15])[:,None,None]).astype("float32")
            data[:,rng.random(shape[1:])<.015]=np.nan;dst.write(data,window=window)
        dst.descriptions=("red","nir","swir1","swir2")
    results=[];modes=["separate","batch_serial","batch_parallel"]
    for iteration in range(args.repeats):
        order=modes[iteration%3:]+modes[:iteration%3]
        for mode in order:
            completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--case",mode,"--directory",str(out)],
                                     capture_output=True,text=True)
            if completed.returncode:raise RuntimeError(completed.stderr)
            record=json.loads(completed.stdout);record["repetition"]=iteration+1;results.append(record)
            print(f"{mode}: {record['seconds']:.3f} s",flush=True)
    baseline=results[0]["signatures"]
    if not all(r["signatures"]==baseline for r in results):
        (out/"failed_runs.json").write_text(json.dumps(results,indent=2))
        raise AssertionError("Numerical outputs differ between benchmark cases; see failed_runs.json")
    medians={mode:statistics.median(r["seconds"] for r in results if r["mode"]==mode) for mode in modes}
    report=dict(cartomize=cm.__version__,python=platform.python_version(),platform=platform.platform(),
                logical_cpus=os.cpu_count(),rasterio=rasterio.__version__,numpy=np.__version__,
                raster_size=[args.size,args.size],input_bands=4,output_indices=NAMES,
                source_bytes=source.stat().st_size,identical_outputs=True,
                cache_policy="OS and GDAL caches not purged; repeated source reads, rotating case order.",
                repeats=args.repeats,median_seconds=medians,
                speedup_vs_separate={mode:medians["separate"]/seconds for mode,seconds in medians.items()},runs=results)
    (out/"benchmark.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"median_seconds":medians,"speedup":report["speedup_vs_separate"],"identical_outputs":True},indent=2))


if __name__=="__main__":main()
