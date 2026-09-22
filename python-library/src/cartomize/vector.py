"""GeoPandas operations with explicit CRSs, metric units and Cartomize profiling."""
from dataclasses import asdict
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd

from ._validation import aligned, frame, measurement_frame
from ._core.vector import _profile_field, _infer_role, _choose_label, _choose_thematic


def read_file(path, **kwargs):
    """Read a vector file into a standard GeoPandas GeoDataFrame."""
    return gpd.read_file(path, **kwargs)


def from_xy(data, x="longitude", y="latitude", crs="EPSG:4326"):
    """Create points from a table without dropping its attributes."""
    table = pd.DataFrame(data).copy()
    coords = table[[x, y]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(coords.to_numpy()).all():
        raise ValueError("Coordinates must be finite.")
    return gpd.GeoDataFrame(table, geometry=gpd.points_from_xy(coords[x], coords[y]), crs=crs)


def reproject(data, crs):
    return frame(data).to_crs(crs)


def clip(data, mask, **kwargs):
    """Clip to a vector mask, explicitly aligning it to the input CRS."""
    data, mask = aligned(data, mask)
    return gpd.clip(data, mask, **kwargs)


def overlay(left, right, how="intersection", **kwargs):
    left, right = aligned(left, right)
    return gpd.overlay(left, right, how=how, **kwargs)


def sjoin(left, right, how="inner", predicate="intersects", **kwargs):
    left, right = aligned(left, right)
    return gpd.sjoin(left, right, how=how, predicate=predicate, **kwargs)


def nearest(left,right,*,metric_crs=None,max_distance=None,how='left'):
    """Nearest features with distances in metres; equal-distance ties are kept."""
    original=frame(left);work,factor=measurement_frame(original,metric_crs)
    target=frame(right).to_crs(work.crs)
    if 'distance_m' in work or 'distance_m' in target:raise ValueError('Rename the existing distance_m field first.')
    if how not in {'left','inner'}:raise ValueError('how must be left or inner.')
    if max_distance is not None and (not np.isfinite(max_distance) or max_distance<=0):raise ValueError('max_distance must be positive metres.')
    result=gpd.sjoin_nearest(work,target,how=how,distance_col='distance_m',
                            max_distance=max_distance/factor if max_distance is not None else None)
    result['distance_m']*=factor
    return result.to_crs(original.crs)


def dissolve(data, by=None, aggfunc="first", **kwargs):
    return frame(data).dissolve(by=by, aggfunc=aggfunc, **kwargs)


def buffer(data, distance, *, metric_crs=None, dissolve=False, **kwargs):
    """Buffer by metres, using a projected input CRS or explicit metric_crs.

    Returns the original CRS and attributes; never buffers in degrees.
    A projected CRS may use feet: its units are converted automatically.
    """
    original = frame(data)
    work, factor = measurement_frame(original, metric_crs)
    distance = float(distance)
    if not np.isfinite(distance):
        raise ValueError("distance must be finite (metres).")
    work.geometry = work.geometry.buffer(distance / factor, **kwargs)
    if dissolve:
        work = work.dissolve()
    return work.to_crs(original.crs)


def area(data, unit="ha", *, metric_crs=None):
    """Planar area as an indexed Series, in m2, ha or km2."""
    units = {"m2": 1.0, "ha": 10000.0, "km2": 1e6}
    if unit not in units:
        raise ValueError("unit must be 'm2', 'ha' or 'km2'.")
    work, factor = measurement_frame(data, metric_crs)
    return (work.geometry.area * factor**2 / units[unit]).rename(f"area_{unit}")


def length(data, unit="m", *, metric_crs=None):
    if unit not in {"m", "km"}:
        raise ValueError("unit must be 'm' or 'km'.")
    work, factor = measurement_frame(data, metric_crs)
    return (work.geometry.length * factor / (1000 if unit == "km" else 1)).rename(f"length_{unit}")


def validate(data):
    """Full geometry audit (not a sampled estimate)."""
    data = frame(data)
    missing = data.geometry.isna()
    empty = data.geometry.is_empty
    present = ~missing & ~empty
    return {
        "features": len(data), "crs": str(data.crs),
        "missing_geometries": int(missing.sum()),
        "empty_geometries": int(empty.sum()),
        "invalid_geometries": int((present & ~data.geometry.is_valid).sum()),
        "duplicate_geometries": int(data.loc[present].geometry.to_wkb().duplicated().sum()),
        "geometry_types": data.geom_type.value_counts().to_dict(),
    }


def make_valid(data):
    data = frame(data)
    data.geometry = data.geometry.make_valid()
    return data


def analyze(data, *, name="", sample_limit=1000):
    """Apply original Cartomize ArcGIS Pro field/role rules to GeoPandas data.

    Attribute profiles use the first sample_limit rows; geometry audit uses all rows.
    """
    data = frame(data)
    if not isinstance(sample_limit, int) or sample_limit < 1:
        raise ValueError("sample_limit must be a positive integer.")
    sample = data.head(sample_limit)
    profiles = []
    for column in sample.columns:
        if column == data.geometry.name:
            continue
        series = sample[column]
        kind = "Double" if pd.api.types.is_numeric_dtype(series) else "String"
        values = [None if not isinstance(v, (list, dict, tuple)) and pd.isna(v) else v for v in series]
        profiles.append(_profile_field(SimpleNamespace(name=str(column), type=kind), values, len(sample)))
    kinds = set(data.geom_type.dropna())
    geometry = "point" if kinds and all("Point" in k for k in kinds) else "line" if kinds and all("Line" in k for k in kinds) else "polygon" if kinds and all("Polygon" in k for k in kinds) else "unknown"
    role, confidence = _infer_role(name, "", geometry, profiles)
    return {**validate(data), "name": name, "sampled_features": len(sample),
            "role": role, "role_confidence": confidence,
            "label_field": _choose_label(profiles), "thematic_field": _choose_thematic(profiles),
            "fields": [asdict(p) for p in profiles]}
