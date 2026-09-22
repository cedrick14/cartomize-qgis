"""Shared validation of spatial references, measurements and destinations."""
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import CRS


def frame(data):
    """Return an independent GeoDataFrame and require a known CRS."""
    if isinstance(data, gpd.GeoDataFrame):
        result = data.copy()
    elif isinstance(data, gpd.GeoSeries):
        result = gpd.GeoDataFrame(geometry=data.copy(), crs=data.crs)
    else:
        result = gpd.read_file(data)
    if result.crs is None:
        raise ValueError("The data has no CRS. Set its actual source CRS before processing.")
    return result


def aligned(left, right):
    left, right = frame(left), frame(right)
    return left, right.to_crs(left.crs)


def linear_factor(crs):
    """Number of metres per projected coordinate unit."""
    crs = CRS.from_user_input(crs)
    if not crs.is_projected or len(crs.axis_info) < 2:
        raise ValueError("This measurement needs a projected CRS; reproject the data first.")
    factors = [axis.unit_conversion_factor for axis in crs.axis_info[:2]]
    if not all(np.isfinite(f) and f > 0 for f in factors) or not np.isclose(*factors):
        raise ValueError("The CRS must use consistent, finite linear units.")
    return float(factors[0])


def measurement_frame(data, metric_crs=None):
    data = frame(data)
    if metric_crs is not None:
        data = data.to_crs(metric_crs)
    # A caller chooses the appropriate projection for their scientific analysis.
    return data, linear_factor(data.crs)


def output_path(path, overwrite=False, sources=()):
    path = Path(path).expanduser().resolve()
    if path in {Path(p).expanduser().resolve() for p in sources}:
        raise ValueError("The output must differ from every input file.")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
