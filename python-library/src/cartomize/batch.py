"""Export one reproducible map page per vector feature."""
import copy
import re
from pathlib import Path

from ._validation import frame


def atlas(map_object, zones, directory, *, name_column, format="pdf", dpi=300,
          padding=.08, overwrite=False, progress=None, cancel=None):
    """Export each feature extent; keep source data and the input Map unchanged.

    Zones must have nonempty geometries. Duplicate sanitized names are rejected
    before any page is written. Explicit per-frame extents are preserved.
    """
    if format not in {"pdf", "png", "svg"}:
        raise ValueError("format must be pdf, png or svg.")
    if not 0 <= padding <= 1:
        raise ValueError("padding must be between zero and one.")
    if map_object.crs is None:
        raise ValueError("Add layers to the Map first.")
    zones = frame(zones).to_crs(map_object.crs)
    if name_column not in zones.columns:
        raise KeyError(name_column)
    if zones.geometry.isna().any() or zones.geometry.is_empty.any():
        raise ValueError("Atlas zones must have nonempty geometries.")
    if not zones.geometry.is_valid.all():raise ValueError('Repair invalid atlas geometries before export.')
    names = [re.sub(r"[^\w.-]+", "_", str(value), flags=re.UNICODE).strip("._") for value in zones[name_column]]
    if any(not n for n in names) or len(set(n.casefold() for n in names)) != len(names):
        raise ValueError("Atlas page names must be nonempty and unique after filename sanitizing.")
    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    if any(n.split('.')[0].upper() in reserved or len(n)>180 for n in names):
        raise ValueError('Atlas page names must be portable filenames, without reserved device names.')
    paths = [Path(directory)/f"{name}.{format}" for name in names]
    if not overwrite and any(p.exists() for p in paths):
        raise FileExistsError("An atlas output already exists.")
    bounds = []
    for geom in zones.geometry:
        x0, y0, x1, y1 = geom.bounds
        if x0 == x1 or y0 == y1:
            raise ValueError("Atlas zones need a nonzero extent; buffer point/line zones first.")
        dx, dy = (x1-x0)*padding, (y1-y0)*padding
        bounds.append((x0-dx, y0-dy, x1+dx, y1+dy))
    from .imagery import _check_cancel
    _check_cancel(cancel)
    for number,(label, extent, path) in enumerate(zip(zones[name_column], bounds, paths),1):
        _check_cancel(cancel)
        page = copy.copy(map_object)
        page.frames = copy.deepcopy(map_object.frames)
        page.title = f"{map_object.title} — {label}" if map_object.title else str(label)
        page.set_extent(extent).export(path, dpi=dpi, overwrite=overwrite)
        if progress:progress(number,len(paths))
    _check_cancel(cancel)
    return paths
