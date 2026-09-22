import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


@pytest.fixture
def write_raster(tmp_path):
    def write(name, data, nodata=-9999, transform=None, crs="EPSG:32733", mask=None):
        data = np.asarray(data)
        if data.ndim == 2:
            data = data[np.newaxis]
        path = tmp_path/name
        with rasterio.open(path, "w", driver="GTiff", width=data.shape[2], height=data.shape[1],
                           count=data.shape[0], dtype=data.dtype, nodata=nodata,
                           transform=transform or from_origin(300000, 9500000, 10, 10), crs=crs) as dst:
            dst.write(data)
            if mask is not None:
                dst.write_mask(np.asarray(mask, dtype="uint8")*255)
        return path
    return write
