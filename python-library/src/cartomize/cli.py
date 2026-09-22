"""Small command line interface for templates, inspection and quick maps."""
import argparse
import json
from pathlib import Path
import sys
import math

from . import (__version__, list_templates, raster, vector, Map, discover_scenes, prepare_imagery,
               color_composite, calculate, spectral_indices, list_indices, focal, reduce_rasters,
               assess_project, prepare_project)
from .color import COMPOSITIONS


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cartomize", description="Cartographic layouts and spatial analysis")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("gui", help="Open the Cartomize desktop interface")
    subs.add_parser("indices", help="List spectral indices and formulas")
    assess=subs.add_parser('assess',help='Inspect project inputs and propose ordered cartographic steps')
    assess.add_argument('sources',nargs='+');assess.add_argument('--goal',choices=['general','administrative','landcover','atlas'],default='general')
    assess.add_argument('--kind',choices=['layers','scenes'],default='layers');assess.add_argument('--aoi')
    project=subs.add_parser('project',help='Prepare masks and symbology in a new Cartomize project directory')
    project.add_argument('destination');project.add_argument('sources',nargs='+');project.add_argument('--without-background-detection',action='store_true')
    calc=subs.add_parser("calculate", help="Evaluate a raster algebra expression")
    calc.add_argument("expression");calc.add_argument("destination")
    calc.add_argument("--input",nargs=3,action="append",required=True,metavar=("NAME","PATH","BAND"))
    calc.add_argument("--align",action="store_true")
    index=subs.add_parser("index",help="Calculate spectral indices in one pass")
    index.add_argument("source");index.add_argument("destination")
    index.add_argument("--indices",default="NDVI");index.add_argument("--band",action="append",default=[],help="Semantic mapping, e.g. red=3")
    index.add_argument("--scale",type=float);index.add_argument("--offset",type=float)
    focal_parser=subs.add_parser("focal",help="Calculate moving-window statistics")
    focal_parser.add_argument("source");focal_parser.add_argument("destination")
    focal_parser.add_argument("--statistic",default="mean");focal_parser.add_argument("--size",type=int,default=3)
    focal_parser.add_argument("--band",type=int,default=1)
    reduction=subs.add_parser("reduce",help="Calculate per-pixel statistics across rasters")
    reduction.add_argument("destination");reduction.add_argument("sources",nargs="+")
    reduction.add_argument("--statistic",default="mean");reduction.add_argument("--min-valid",type=int,default=1)
    reduction.add_argument("--band",type=int,default=1)
    for command in (calc,index,focal_parser,reduction):
        command.add_argument("--workers",type=int,default=1);command.add_argument("--block-size",type=int,default=512)
        command.add_argument("--memory-limit-mb",type=int,default=512);command.add_argument("--overwrite",action="store_true")
    templates = subs.add_parser("templates", help="List the 24 bundled templates")
    templates.add_argument("--category", default="")
    inspect = subs.add_parser("inspect", help="Inspect raster/vector data")
    inspect.add_argument("source")
    inspect.add_argument("--kind", choices=["raster", "vector"])
    mapping = subs.add_parser("map", help="Create a PDF, PNG or SVG map")
    mapping.add_argument("source"); mapping.add_argument("destination")
    mapping.add_argument("--title", default="")
    mapping.add_argument("--column"); mapping.add_argument("--labels")
    mapping.add_argument("--template"); mapping.add_argument("--crs")
    mapping.add_argument("--dpi", type=int, default=300)
    mapping.add_argument("--overwrite", action="store_true")
    mapping.add_argument("--rgb", choices=list(COMPOSITIONS)+["native"])
    discovery = subs.add_parser("scenes", help="Discover standard local Landsat/Sentinel scenes")
    discovery.add_argument("source")
    prepare = subs.add_parser("prepare", help="Mosaic, calibrate, stack and clip spectral scenes")
    prepare.add_argument("source"); prepare.add_argument("destination")
    prepare.add_argument("--bands", required=True, help="Comma-separated semantic names: blue,green,red,nir")
    prepare.add_argument("--aoi"); prepare.add_argument("--crs")
    prepare.add_argument("--resolution", type=float, help="Output pixel size in metres")
    prepare.add_argument("--overlap", choices=["first","last"], default="first")
    prepare.add_argument("--resampling", choices=["nearest","bilinear","cubic","average"], default="nearest")
    prepare.add_argument("--allow-mixed-dates", action="store_true")
    prepare.add_argument("--without-cloud-mask", action="store_true")
    prepare.add_argument("--overwrite", action="store_true")
    composite = subs.add_parser("composite", help="Export a natural/false-colour RGBA GeoTIFF")
    composite.add_argument("source"); composite.add_argument("destination")
    composite.add_argument("--rgb", choices=list(COMPOSITIONS)+["native"], default="natural")
    composite.add_argument("--gamma", type=float, default=1.)
    composite.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .desktop import main as desktop_main
            return desktop_main()
        elif args.command == "indices":result=list_indices()
        elif args.command == 'assess':result=assess_project(args.sources,goal=args.goal,data_kind=args.kind,aoi=args.aoi)
        elif args.command == 'project':result=prepare_project(args.sources,args.destination,auto_background=not args.without_background_detection).report
        elif args.command in {"calculate","index","focal","reduce"}:
            options=dict(workers=args.workers,block_size=args.block_size,memory_limit_mb=args.memory_limit_mb,overwrite=args.overwrite)
            if args.command=="calculate":
                inputs={name:(path,int(band)) for name,path,band in args.input}
                if len(inputs)!=len(args.input):raise ValueError("Input variable names must be unique.")
                output=calculate(args.expression,inputs,args.destination,align=args.align,**options)
            elif args.command=="index":
                mapping={}
                for item in args.band:
                    name,separator,value=item.partition("=")
                    if not separator or name in mapping:raise ValueError("Band mapping must use distinct name=number entries.")
                    mapping[name]=int(value)
                output=spectral_indices(args.source,args.destination,args.indices.split(","),band_map=mapping,
                         scale=args.scale,offset=args.offset,**options)
            elif args.command=="focal":output=focal(args.source,args.destination,statistic=args.statistic,size=args.size,band=args.band,**options)
            else:output=reduce_rasters(args.sources,args.destination,statistic=args.statistic,band=args.band,min_valid=args.min_valid,**options)
            result={"output":str(output)}
        elif args.command == "templates":
            result = list_templates(args.category)
        elif args.command == "inspect":
            kind = args.kind or ("raster" if Path(args.source).suffix.lower() in {".tif", ".tiff", ".vrt", ".img", ".jp2"} else "vector")
            result = raster.inspect(args.source) if kind == "raster" else vector.analyze(args.source, name=Path(args.source).stem)
        elif args.command == "scenes":
            result = [{"id":s.scene_id,"sensor":s.sensor,"date":s.acquired,"level":s.level,
                       "bands":list(s.bands),"quality_mask":str(s.quality) if s.quality else None}
                      for s in discover_scenes(args.source)]
        elif args.command == "prepare":
            product = prepare_imagery(args.source,args.destination,aoi=args.aoi,
                      band_order=[b.strip() for b in args.bands.split(",")],target_crs=args.crs,
                      resolution=args.resolution,overlap=args.overlap,resampling=args.resampling,
                      allow_mixed_dates=args.allow_mixed_dates,mask_clouds=not args.without_cloud_mask,
                      overwrite=args.overwrite)
            result = product.report
        elif args.command == "composite":
            result = {"output":str(color_composite(args.source,args.destination,bands=args.rgb,
                        gamma=args.gamma,overwrite=args.overwrite))}
        else:
            result = {"output": str(Map(title=args.title, template=args.template, crs=args.crs)
                      .add_layer(args.source, column=args.column, labels=args.labels, rgb=args.rgb)
                      .export(args.destination, dpi=args.dpi, overwrite=args.overwrite))}
        print(json.dumps(_json_value(result), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, ImportError) as exc:
        print(f"cartomize: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
