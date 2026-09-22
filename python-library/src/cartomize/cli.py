"""Small command line interface for templates, inspection and quick maps."""
import argparse
import json
from pathlib import Path
import sys
import math

from . import __version__, list_templates, raster, vector, Map, discover_scenes, prepare_imagery, color_composite
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
        if args.command == "templates":
            result = list_templates(args.category)
        elif args.command == "inspect":
            kind = args.kind or ("raster" if Path(args.source).suffix.lower() in {".tif", ".tiff", ".vrt", ".img"} else "vector")
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
    except (ValueError, OSError, KeyError) as exc:
        print(f"cartomize: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
