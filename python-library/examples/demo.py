"""Reproducible demonstration using synthetic data only; no download needed."""
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, LineString
import cartomize as cm


def main():
    out = Path("output/demo")
    out.mkdir(parents=True, exist_ok=True)
    crs = "EPSG:32733"
    villages = cm.from_xy({"nom": ["Village A", "Village B", "Village C"],
                           "x": [301200, 303200, 305900], "y": [9501700, 9505100, 9503300]}, x="x", y="y", crs=crs)
    zones = cm.GeoDataFrame({"nom": ["Ouest", "Est"]}, geometry=[box(300000, 9500000, 304000, 9508000), box(304000, 9500000, 308000, 9508000)], crs=crs)
    roads = cm.GeoDataFrame(geometry=[LineString([(300200, 9500500), (301200, 9501700), (303200, 9505100), (305900, 9503300), (307800, 9505500)])], crs=crs)
    y, x = np.indices((100, 100))
    data = np.where(x + 15*np.sin(y/14) < 48, 1, 2).astype("uint8")
    data[(x-65)**2+(y-35)**2 < 190] = 3
    data[(x < 5) & (y < 20)] = 255
    raster_path = out/"occupation_fictive.tif"
    with rasterio.open(raster_path, "w", driver="GTiff", width=100, height=100, count=1,
                       dtype="uint8", crs=crs, transform=from_origin(300000, 9508000, 80, 80), nodata=255) as dst:
        dst.write(data, 1)
    villages.to_file(out/"villages_fictifs.gpkg", driver="GPKG")
    carte = cm.Map(title="Cartomize Python", subtitle="Occupation du sol · exemple de mise en page automatique",
                    credits="Données fictives — démonstration | Cartomize / Cédrick Belmich | UTM 33S", crs=crs)
    carte.add_layer(raster_path, name="Occupation du sol", classes={1:("Forêt dense", "#24634d"), 2:("Forêt secondaire", "#95bba0"), 3:("Agriculture", "#e1b96c")})
    carte.add_layer(roads, name="Route", color="#b16a3d", linewidth=1.5)
    carte.add_layer(villages, name="Villages", labels="nom", color="#172d38", markersize=30)
    for extension in ("png", "pdf", "svg"):
        carte.export(out/f"cartomize_demo.{extension}", dpi=180, overwrite=True)
    cm.raster.class_areas(raster_path).to_csv(out/"surfaces_fictives.csv", index=False)
    cm.atlas(carte, zones, out/"atlas", name_column="nom", dpi=100, overwrite=True)
    print(out.resolve())


if __name__ == "__main__":
    main()
