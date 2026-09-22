"""Small command line interface for templates, inspection and quick maps."""
import argparse
import json
from pathlib import Path
import sys
import math

from . import __version__, list_templates, raster, vector, Map


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
    args = parser.parse_args(argv)
    try:
        if args.command == "templates":
            result = list_templates(args.category)
        elif args.command == "inspect":
            kind = args.kind or ("raster" if Path(args.source).suffix.lower() in {".tif", ".tiff", ".vrt", ".img"} else "vector")
            result = raster.inspect(args.source) if kind == "raster" else vector.analyze(args.source, name=Path(args.source).stem)
        else:
            result = {"output": str(Map(title=args.title, template=args.template, crs=args.crs)
                      .add_layer(args.source, column=args.column, labels=args.labels)
                      .export(args.destination, dpi=args.dpi, overwrite=args.overwrite))}
        print(json.dumps(_json_value(result), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"cartomize: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
