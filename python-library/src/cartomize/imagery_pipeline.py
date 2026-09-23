"""Selectable multispectral preparation with atomic, separate deliverables."""
from dataclasses import dataclass
from pathlib import Path
import re

import rasterio

from .scenes import Scene, discover_scenes
from .imagery import prepare_imagery, _check_cancel
from .color import color_composite, COMPOSITIONS
from .storage import new_directory, save_json, relocate_products
from .raster import _copy_band_metadata


@dataclass(frozen=True)
class ImageryProducts:
    manifest: Path
    products: tuple[dict, ...]


def _split(source, directory, *, progress=None, cancel=None):
    """Copy calibrated bands by windows, preserving masks and metadata."""
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    with rasterio.open(source) as src:
        total = src.count * sum(1 for _ in src.block_windows(1))
        done = 0
        for band in src.indexes:
            _check_cancel(cancel)
            name = src.descriptions[band - 1] or f"band_{band}"
            stem = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:60] or "band"
            path = directory / f"{band:02d}_{stem}.tif"
            profile = {**src.profile, "count": 1}
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(path, "w", **profile) as dst:
                for _, window in src.block_windows(band):
                    _check_cancel(cancel)
                    dst.write(src.read(band, window=window), 1, window=window)
                    dst.write_mask(src.read_masks(band, window=window), window=window)
                    done += 1
                    if progress:
                        progress(done, total)
                _copy_band_metadata(src, band, dst)
            # Indices prevent collisions even when descriptions repeat.
            outputs[str(band)] = dict(name=name, path=str(path))
    return outputs


def split_bands(source, destination, *, progress=None, cancel=None):
    """Export every band to a new directory of single-band GeoTIFFs."""
    _check_cancel(cancel)
    destination = Path(destination).expanduser().resolve()
    with new_directory(destination) as work:
        outputs = _split(source, work, progress=progress, cancel=cancel)
        save_json(dict(schema="cartomize.bands.v1", source=str(Path(source).resolve()),
                       bands=outputs), work / "bands.json")
        replace = relocate_products(work, destination)
        outputs = replace(outputs)
        _check_cancel(cancel)
    return {int(index): Path(record["path"]) for index, record in outputs.items()}


def process_imagery(scenes, destination, *, aoi=None, mosaic=True, multiband=True,
                    separate_bands=False, composition=None, band_order=None,
                    target_crs=None, resolution=None, overlap="first", resampling="nearest",
                    mask_clouds=True, mask_saturation=True, allow_mixed_dates=False,
                    all_touched=False, max_pixels=250_000_000, percentiles=(2, 98),
                    gamma=1., progress=None, cancel=None, stage=None):
    """Prepare selected scenes and publish the requested products together.

    With mosaic=False each scene has its own output folder. The multiband
    product retains calibrated scientific values; composition is a separate
    RGBA display product. Unrequested intermediate multibands are removed.
    destination must be new; errors/cancellation leave no partial directory.
    """
    _check_cancel(cancel)
    if not (multiband or separate_bands or composition is not None):
        raise ValueError("Choisir un GeoTIFF multibande, des bandes séparées ou une composition colorée.")
    if isinstance(scenes, (str, Path)):
        scenes = discover_scenes(scenes)
    else:
        scenes = list(scenes)
        if scenes and not all(isinstance(scene, Scene) for scene in scenes):
            scenes = discover_scenes(scenes)
    if not scenes:
        raise ValueError("Sélectionner au moins une scène.")
    if len({scene.scene_id for scene in scenes}) != len(scenes):
        raise ValueError("Les identifiants des scènes doivent être uniques.")
    if mosaic and band_order is None and any(set(s.bands) != set(scenes[0].bands) for s in scenes):
        raise ValueError("La mosaïque nécessite les mêmes bandes sélectionnées dans chaque scène.")
    groups = [scenes] if mosaic else [[scene] for scene in scenes]
    if isinstance(composition, str):
        if composition not in COMPOSITIONS:
            raise ValueError("Composition colorée inconnue.")
        composition = COMPOSITIONS[composition]
    if composition is not None:
        composition = tuple(composition)
        if len(composition) != 3:
            raise ValueError("Affecter trois bandes aux canaux rouge, vert et bleu.")
        for group in groups:
            names = tuple(band_order) if band_order is not None else tuple(group[0].bands)
            for value in composition:
                if not ((isinstance(value, str) and value in names) or
                        (type(value) is int and 1 <= value <= len(names))):
                    raise ValueError(f"Bande de composition absente : {value} ({group[0].scene_id}).")
    destination = Path(destination).expanduser().resolve()
    products = []
    phases = 1 + int(separate_bands) + int(composition is not None)
    phase = 0
    total = len(groups) * phases * 1000
    if progress:
        progress(0, total)

    def callback(done, count):
        if progress:
            progress(phase * 1000 + round(1000 * done / max(1, count)), total)

    with new_directory(destination) as work:
        for number, group in enumerate(groups, 1):
            _check_cancel(cancel)
            directory = work / ("mosaique" if mosaic else f"scene_{number:03d}")
            directory.mkdir()
            if stage:
                stage("Prétraitement multispectral" + (" et mosaïque" if mosaic and len(group) > 1 else "") + f" · {number}/{len(groups)}")
            prepared = prepare_imagery(group, directory / "multibande.tif", aoi=aoi,
                band_order=band_order, target_crs=target_crs, resolution=resolution,
                overlap=overlap, resampling=resampling, mask_clouds=mask_clouds,
                mask_saturation=mask_saturation, allow_mixed_dates=allow_mixed_dates,
                all_touched=all_touched, max_pixels=max_pixels, progress=callback, cancel=cancel)
            phase += 1
            bands = {}
            if separate_bands:
                if stage:
                    stage("Extraction des bandes")
                bands = _split(prepared.path, directory / "bandes", progress=callback, cancel=cancel)
                phase += 1
            display = None
            if composition is not None:
                if stage:
                    stage("Composition colorée")
                display = color_composite(prepared.path, directory / "composition_coloree.tif",
                    bands=composition, percentiles=percentiles, gamma=gamma,
                    progress=callback, cancel=cancel)
                phase += 1
            if not multiband:
                prepared.path.unlink()
            report = {**prepared.report, "product": str(prepared.path) if multiband else None,
                      "separate_bands": bands, "composition": str(display) if display else None}
            save_json(report, prepared.manifest, overwrite=True)
            products.append(dict(scenes=[s.scene_id for s in group],
                multiband=str(prepared.path) if multiband else None, bands=bands,
                composition=str(display) if display else None,
                source_index=str(prepared.source_index), report=str(prepared.manifest)))
        manifest = dict(schema="cartomize.imagery.v1", mosaic=mosaic,
            multiband=multiband, separate_bands=separate_bands,
            rgb_bands=composition, aoi=str(Path(aoi).resolve()) if isinstance(aoi, (str, Path)) else None,
            products=products)
        save_json(manifest, work / "imagery.json")
        replace = relocate_products(work, destination)
        products = replace(products)
        _check_cancel(cancel)
    if progress:
        progress(total, total)
    return ImageryProducts(destination / "imagery.json", tuple(products))
