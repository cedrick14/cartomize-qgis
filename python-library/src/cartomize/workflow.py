"""Satellite scenes to cartographic deliverables in one reproducible operation."""
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile

from .color import COMPOSITIONS, color_composite
from .composition import compose_map
from .imagery import _check_cancel, prepare_imagery
from .scenes import Scene, discover_scenes


@dataclass(frozen=True)
class CartographicProduct:
    directory: Path
    multiband: Path
    composite: Path
    maps: tuple[Path, ...]
    manifest: Path


def cartographic_workflow(scenes, destination, *, layers=(), aoi=None,
                          band_order=None, target_crs=None, resolution=None,
                          mask_clouds=True, allow_mixed_dates=False,
                          composition="natural", title="", credits="",
                          template=None, formats=("pdf", "png"), dpi=300,
                          page_format="A4", orientation="landscape", subtitle="",
                          legend=True, scale_bar=True, north_arrow=True,
                          progress=None, stage=None, cancel=None):
    """Prepare, mosaic, stack, mask, render RGB and export ordered map layers.

    ``scenes`` accepts Scene objects, a product directory or selected band paths.
    The destination must be a new directory. Products are staged beside it and
    moved into place only after all operations succeed. Existing directories
    are never replaced. Cancellation is checked between raster blocks and map
    exports; an individual cartographic render completes before cancellation.
    """
    _check_cancel(cancel)
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Choisir un nouveau répertoire de production : {destination}")
    if composition not in COMPOSITIONS:
        raise ValueError(f"Composition inconnue : {composition}")
    formats = tuple(dict.fromkeys(formats))
    if not formats or any(fmt not in {"pdf", "png", "svg"} for fmt in formats):
        raise ValueError("Choisir au moins un format parmi pdf, png et svg.")
    if not isinstance(dpi, int) or not 72 <= dpi <= 1200:
        raise ValueError("La résolution d’export doit être comprise entre 72 et 1 200 ppp.")
    def notify(label, value):
        if stage: stage(label)
        if progress: progress(value, 100)
        _check_cancel(cancel)
    notify("Identification des scènes et des bandes spectrales", 0)
    if isinstance(scenes, (str, Path)):
        scenes = discover_scenes(scenes)
    else:
        scenes = list(scenes)
        if scenes and not all(isinstance(s, Scene) for s in scenes):
            scenes = discover_scenes(scenes)
    names = list(dict.fromkeys(band_order or ("blue", "green", "red", "nir")))
    names += [name for name in COMPOSITIONS[composition] if name not in names]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cartomize-production-", dir=destination.parent) as temporary:
        work = Path(temporary) / "products"
        work.mkdir()
        notify("Calibration radiométrique, mosaïque et assemblage multibande", 2)
        prepared = prepare_imagery(
            scenes, work / "multibande.tif", aoi=aoi, band_order=names,
            target_crs=target_crs, resolution=resolution, mask_clouds=mask_clouds,
            allow_mixed_dates=allow_mixed_dates, cancel=cancel,
            progress=lambda done, total: progress(2 + int(68 * done / max(1, total)), 100) if progress else None)
        notify("Composition colorée", 70)
        composite = color_composite(
            prepared.path, work / "composition_coloree.tif", bands=composition,
            cancel=cancel, progress=lambda done, total: progress(70 + int(15 * done / max(1, total)), 100) if progress else None)
        notify("Superposition des couches et mise en page cartographique", 85)
        map_layers = [{"data": composite, "role": "background", "rgb": "native", "name": "Image satellite"}]
        map_layers.extend(layers)
        cartography = compose_map(map_layers, aoi=aoi, title=title, credits=credits,
                                  template=template, crs=target_crs, format=page_format,
                                  orientation=orientation, subtitle=subtitle)
        cartography.add_legend(legend).add_scale_bar(scale_bar).add_north_arrow(north_arrow)
        outputs = []
        for index, fmt in enumerate(formats):
            notify(f"Export cartographique ({fmt.upper()})", 85 + int(13 * index / len(formats)))
            outputs.append(cartography.export(work / f"carte.{fmt}", dpi=dpi))
        # Manifests must refer to the published directory, never temporary paths.
        report = dict(prepared.report)
        report["product"] = str(destination / prepared.path.name)
        report["source_index"] = str(destination / prepared.source_index.name)
        prepared.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from . import __version__
        record = dict(version=__version__, multiband="multibande.tif",
                      composite="composition_coloree.tif", preparation="multibande.json",
                      maps=[p.name for p in outputs], composition=composition,
                      title=title, credits=credits, template=template, dpi=dpi,
                      page_format=page_format, orientation=orientation, subtitle=subtitle,
                      legend=legend, scale_bar=scale_bar, north_arrow=north_arrow,
                      aoi=str(aoi) if aoi is not None else None,
                      layer_plan=cartography.layer_plan())
        manifest = work / "production.json"
        manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        notify("Enregistrement des produits cartographiques", 99)
        if destination.exists():
            raise FileExistsError(destination)
        work.rename(destination)
    if progress: progress(100, 100)
    if stage: stage("Production cartographique terminée")
    return CartographicProduct(destination, destination / prepared.path.name,
                              destination / composite.name,
                              tuple(destination / path.name for path in outputs),
                              destination / manifest.name)
