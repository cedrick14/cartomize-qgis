"""Rasterio processing with source masks, explicit grids and windowed writes."""
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import math
import os
import tempfile

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask as raster_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.features import geometry_mask, geometry_window
from rasterio.errors import WindowError

from ._core.raster_sampling import profile_array
from ._core.raster_intelligence_core import RasterEvidence, infer_raster
from ._validation import frame, linear_factor, output_path


def _band(src, band):
    if not isinstance(band, int) or not 1 <= band <= src.count:
        raise ValueError(f"band must be an integer in 1..{src.count}.")


def _read(src, band, **kwargs):
    return np.ma.masked_invalid(src.read(band, masked=True, **kwargs))


def _profile(src, **changes):
    profile = dict(driver="GTiff", width=src.width, height=src.height,
                   crs=src.crs, transform=src.transform, count=1,
                   dtype="float32", nodata=np.nan, compress="lzw")
    profile.update(changes)
    return profile


@contextmanager
def _writer(path, profile, *, overwrite=False, sources=()):
    """Write to a temporary GeoTIFF and replace the destination after success."""
    path = output_path(path, overwrite, sources)
    fd, temporary = tempfile.mkstemp(prefix=".cartomize-", suffix=".tif", dir=path.parent)
    os.close(fd)
    try:
        with rasterio.open(temporary, "w", **profile) as dst:
            yield dst
        os.replace(temporary, path)
        # Old GDAL sidecars must not override a replacement raster's new mask
        # or georeferencing. They are invalidated only after a successful write.
        for suffix in ('.msk','.aux.xml','.ovr'):
            Path(str(path)+suffix).unlink(missing_ok=True)
    finally:
        for suffix in ("", ".msk", ".aux.xml"):
            Path(temporary + suffix).unlink(missing_ok=True)


def inspect(path, *, band=1, max_pixels=250_000):
    """Sample a raster and run the preserved Cartomize inference engine.

    Frequencies describe the sample. Suggested NoData values are diagnostic
    only: they are never applied to the raster or to computed statistics.
    """
    if not isinstance(max_pixels, int) or max_pixels < 1:
        raise ValueError("max_pixels must be a positive integer.")
    with rasterio.open(path) as src:
        _band(src, band)
        ratio = min(1, math.sqrt(max_pixels / (src.width * src.height)))
        height, width = max(1, int(src.height * ratio)), max(1, int(src.width * ratio))
        sample = _read(src, band, out_shape=(height, width), resampling=Resampling.nearest)
        summary = profile_array(sample.data, mask=~np.ma.getmaskarray(sample))
        values = sample.compressed()
        colors = {}
        try:
            colors = src.colormap(band)
        except ValueError:
            pass
        evidence = RasterEvidence(
            band_count=src.count, data_type=src.dtypes[band-1],
            total_pixels=sample.size, valid_pixels=summary.valid_pixels,
            unique_count=summary.observed_unique_count, values=summary.profiles,
            minimum=float(values.min()) if values.size else None,
            maximum=float(values.max()) if values.size else None,
            source_nodata=src.nodatavals[band-1], has_mask=bool(np.ma.getmaskarray(sample).any()),
            has_color_table=bool(colors),
            band_color_interpretations=tuple(c.name for c in src.colorinterp),
            metadata_text=" ".join([Path(path).name, *map(str, src.tags().values())]),
            sample_fraction=sample.size/(src.width*src.height),
        )
        return {"path": str(path), "width": src.width, "height": src.height,
                "bands": src.count, "crs": str(src.crs), "dtype": src.dtypes[band-1],
                "nodata": src.nodatavals[band-1], "sample_fraction": evidence.sample_fraction,
                "sample": asdict(summary), "inference": infer_raster(evidence).to_dict()}


def normalized_difference(source, destination, *, positive_band, negative_band,
                          scale=None, offset=None, overwrite=False):
    """Write (positive-negative)/(positive+negative), respecting masks.

    Applies per-band GDAL scales/offsets unless common scale/offset values
    are supplied. Zero denominators become NoData; valid zero results survive.
    Input bands must belong to the same dataset/grid.
    """
    with rasterio.open(source) as src:
        _band(src, positive_band); _band(src, negative_band)
        if positive_band == negative_band:
            raise ValueError("Choose two distinct bands.")
        with _writer(destination, _profile(src), overwrite=overwrite, sources=(source,)) as dst:
            for _, window in src.block_windows(positive_band):
                a, b = (_read(src, k, window=window).astype("float64") for k in (positive_band, negative_band))
                a = a * (src.scales[positive_band-1] if scale is None else scale) + (src.offsets[positive_band-1] if offset is None else offset)
                b = b * (src.scales[negative_band-1] if scale is None else scale) + (src.offsets[negative_band-1] if offset is None else offset)
                with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                    result = np.ma.masked_invalid((a - b) / (a + b))
                    converted=result.filled(np.nan).astype('float32')
                dst.write(np.where(np.isfinite(converted),converted,np.nan), 1, window=window)
            dst.update_tags(operation="normalized_difference", positive_band=positive_band,
                            negative_band=negative_band)
    return Path(destination)


def ndvi(source, destination, *, red, nir, **kwargs):
    return normalized_difference(source, destination, positive_band=nir, negative_band=red, **kwargs)


def _copy_band_metadata(src,band,dst):
    dst.descriptions=(src.descriptions[band-1],)
    dst.scales=(src.scales[band-1],);dst.offsets=(src.offsets[band-1],)
    if src.units[band-1]:dst.set_band_unit(1,src.units[band-1])
    dst.update_tags(**src.tags());dst.update_tags(1,**src.tags(band))


def reclassify(source, destination, mapping, *, band=1, unmatched="nodata", overwrite=False):
    """Recode exact categorical values; preserve source masks and valid zeros.

    Unmapped valid pixels become NoData, or remain unchanged with unmatched='keep'.
    Float64 output preserves exact integer codes up to 2**53.
    """
    if unmatched not in {"nodata", "keep"}:
        raise ValueError("unmatched must be 'nodata' or 'keep'.")
    mapping = {float(k): float(v) for k, v in mapping.items()}
    if not mapping or not all(np.isfinite([k, v]).all() for k, v in mapping.items()):
        raise ValueError("mapping must contain finite input and output values.")
    with rasterio.open(source) as src:
        _band(src, band)
        with _writer(destination, _profile(src, dtype="float64"), overwrite=overwrite, sources=(source,)) as dst:
            for _, window in src.block_windows(band):
                original = _read(src, band, window=window).astype("float64")
                result = original.filled(np.nan) if unmatched == "keep" else np.full(original.shape, np.nan)
                for old, new in mapping.items():
                    result[(original.data == old) & ~np.ma.getmaskarray(original)] = new
                dst.write(result, 1, window=window)
    return Path(destination)


def clip(source, mask, destination, *, band=1, all_touched=False, overwrite=False):
    """Crop one band to a vector mask; output is a float64 GeoTIFF."""
    vectors = frame(mask)
    with rasterio.open(source) as src:
        _band(src, band)
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        vectors = vectors.to_crs(src.crs)
        geometries = [g for g in vectors.geometry if g is not None and not g.is_empty]
        if not geometries:
            raise ValueError("The clipping mask contains no geometry.")
        data, transform = raster_mask(src, geometries, indexes=band, crop=True,
                                      filled=False, all_touched=all_touched)
        data = np.ma.masked_invalid(data.astype("float64"))
        profile = _profile(src, dtype="float64", transform=transform, height=data.shape[0], width=data.shape[1])
        sources=(source,mask) if isinstance(mask,(str,Path)) else (source,)
        with _writer(destination, profile, overwrite=overwrite, sources=sources) as dst:
            dst.write(data.filled(np.nan), 1)
            _copy_band_metadata(src,band,dst)
    return Path(destination)


def reproject(source, destination, crs, *, band=1, resolution=None, resampling="nearest", overwrite=False):
    """Reproject a band; nearest-neighbour is the default for categorical safety."""
    if resampling not in {"nearest", "bilinear", "cubic", "average", "mode"}:
        raise ValueError("Unsupported resampling method.")
    with rasterio.open(source) as src:
        _band(src, band)
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        transform, width, height = calculate_default_transform(
            src.crs, crs, src.width, src.height, *src.bounds, resolution=resolution)
        with WarpedVRT(src, crs=crs, transform=transform, width=width, height=height,
                       dtype="float64", nodata=np.nan, resampling=Resampling[resampling]) as vrt:
            with _writer(destination, _profile(vrt, dtype="float64"), overwrite=overwrite, sources=(source,)) as dst:
                for _, window in dst.block_windows(1):
                    dst.write(_read(vrt, band, window=window).filled(np.nan), 1, window=window)
                _copy_band_metadata(src,band,dst)
    return Path(destination)


def zonal_stats(source, zones, *, band=1, all_touched=False):
    """One row per input feature, preserving its index and original CRS.

    Adds count, min, max, mean, sum, std (population standard deviation).
    Empty/nonoverlapping zones get count=0 and NaN statistics. A window per
    feature is read; overlapping zones are evaluated independently.
    """
    result = frame(zones)
    names = ["count", "min", "max", "mean", "sum", "std"]
    if set(names) & set(result.columns):
        raise ValueError("Rename existing count/min/max/mean/sum/std columns before zonal_stats.")
    records = []
    with rasterio.open(source) as src:
        _band(src, band)
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        for geometry in result.to_crs(src.crs).geometry:
            values = np.array([], dtype=float)
            if geometry is not None and not geometry.is_empty:
                try:
                    window = geometry_window(src, [geometry])
                    data = _read(src, band, window=window)
                    inside = geometry_mask([geometry], out_shape=data.shape,
                                           transform=src.window_transform(window),
                                           invert=True, all_touched=all_touched)
                    values = data.data[inside & ~np.ma.getmaskarray(data)].astype("float64")
                except WindowError:
                    pass
            records.append([len(values), *([float(f(values)) for f in (np.min, np.max, np.mean, np.sum, np.std)] if len(values) else [np.nan]*5)])
    # Assign positionally: duplicate input indices must remain distinct features.
    for i, name in enumerate(names):
        result[name] = [r[i] for r in records]
    return result


def class_areas(source, *, band=1, unit="ha"):
    """Exact pixel counts and planar areas by class, excluding declared NoData."""
    divisor = {"m2": 1, "ha": 1e4, "km2": 1e6}.get(unit)
    if divisor is None:
        raise ValueError("unit must be 'm2', 'ha' or 'km2'.")
    counts = Counter()
    with rasterio.open(source) as src:
        _band(src, band)
        factor = linear_factor(src.crs)
        pixel_area = abs(src.transform.a * src.transform.e - src.transform.b * src.transform.d) * factor**2
        for _, window in src.block_windows(band):
            values, frequencies = np.unique(_read(src, band, window=window).compressed(), return_counts=True)
            counts.update({float(v): int(n) for v, n in zip(values, frequencies)})
    return pd.DataFrame([(v, n, n*pixel_area/divisor) for v, n in sorted(counts.items())],
                        columns=["class", "pixels", f"area_{unit}"])


def change_matrix(before, after, *, band=1):
    """Exact from/to pixel counts on identical grids, excluding either mask."""
    counts = Counter()
    with rasterio.open(before) as a, rasterio.open(after) as b:
        _band(a, band); _band(b, band)
        if a.crs is None or b.crs is None:
            raise ValueError("Both rasters need a CRS.")
        if a.crs != b.crs or a.transform != b.transform or a.shape != b.shape:
            raise ValueError("Raster grids differ; align CRS, transform and dimensions first.")
        for _, window in a.block_windows(band):
            x, y = _read(a, band, window=window), _read(b, band, window=window)
            valid = ~np.ma.getmaskarray(x) & ~np.ma.getmaskarray(y)
            pairs, frequencies = np.unique(np.column_stack((x.data[valid], y.data[valid])), axis=0, return_counts=True)
            counts.update({(float(v[0]), float(v[1])): int(n) for v, n in zip(pairs, frequencies)})
    return pd.DataFrame([(a, b, n) for (a, b), n in sorted(counts.items())], columns=["from", "to", "pixels"])
