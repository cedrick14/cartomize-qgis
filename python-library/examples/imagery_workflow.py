"""End-to-end example with SYNTHETIC scenes, no satellite download required."""
from pathlib import Path
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, LineString
import cartomize as cm


def write(path, values, transform, nodata=None):
    with rasterio.open(path,"w",driver="GTiff",width=values.shape[1],height=values.shape[0],
                       count=1,dtype=values.dtype,crs=32733,transform=transform,nodata=nodata,
                       compress="lzw") as dst:
        dst.write(values,1)
    return path


def main(output="output/imagery"):
    out=Path(output).resolve(); inputs=out/"scenes_fictives"
    inputs.mkdir(parents=True,exist_ok=True)
    scenes=[]
    for ident,start in [("A",0),("B",120)]:
        bands={}
        for band,resolution,reflectance in [
            ("blue",10,(.04,.13,.035)),("green",10,(.12,.23,.09)),
            ("red",10,(.06,.30,.025)),("nir",10,(.48,.38,.015)),
            ("swir1",20,(.23,.40,.009))]:
            ratio=resolution//10
            y,x=np.indices((160//ratio,180//ratio))
            gx=x*ratio+start+ratio/2;gy=y*ratio+ratio/2
            forest=gx < 128+20*np.sin(gy/31)
            water=np.abs(gx-(155+22*np.sin(gy/32)))<4
            base=np.where(forest,reflectance[0],reflectance[1])
            texture=1+.08*np.sin(gx/4)*np.cos(gy/7)+.05*np.sin(gy/13)
            values=np.where(water,reflectance[2],base*texture)
            raw=np.round(values*10000).astype("uint16")
            path=write(inputs/f"{ident}_{band}.tif",raw,from_origin(300000+start*10,9500000,resolution,resolution),nodata=0)
            bands[band]=cm.Band(path,scale=.0001,nodata=0,unit="synthetic reflectance")
        y,x=np.indices((160,180));gx=x+start
        # A cloud in scene A's overlap can be filled by clear scene B.
        cloudy=((gx-145)**2+(y-45)**2<14**2) if ident=="A" else ((gx-268)**2+(y-125)**2<8**2)
        quality=write(inputs/f"{ident}_valid.tif",(~cloudy).astype("uint8"),from_origin(300000+start*10,9500000,10,10))
        scenes.append(cm.Scene(ident,bands,sensor="synthetic-demo",acquired="2026-08-17",
                               quality=quality,quality_kind="valid_mask"))
    aoi=cm.GeoDataFrame({"nom":["Zone fictive"]},geometry=[Polygon([
        (300150,9498500),(302450,9498470),(302850,9498770),
        (302800,9499870),(300500,9499930),(300100,9499500)])],crs=32733)
    aoi.to_file(out/"zone_fictive.geojson",driver="GeoJSON")
    product=cm.prepare_imagery(scenes,out/"multibande.tif",aoi=aoi,
              band_order=["blue","green","red","nir","swir1"],overwrite=True)
    cm.color_composite(product.path,out/"couleurs_naturelles.tif",bands="natural",overwrite=True)
    cm.color_composite(product.path,out/"fausses_couleurs.tif",bands="vegetation",overwrite=True)
    cm.raster.ndvi(product.path,out/"ndvi.tif",red=3,nir=4,overwrite=True)
    roads=cm.GeoDataFrame(geometry=[LineString([
        (300250,9498720),(300650,9499100),(301350,9499480),(302120,9499150),(302750,9498900)])],crs=32733)
    villages=cm.from_xy({"nom":["Localité A","Localité B","Localité C"],
        "x":[300650,301350,302120],"y":[9499100,9499480,9499150]},x="x",y="y",crs=32733)
    line_y=np.linspace(9498450,9499950,160)
    river=cm.GeoDataFrame(geometry=[LineString(zip(300000+(155+22*np.sin((9500000-line_y)/320))*10,line_y))],crs=32733)
    roads.to_file(out/"routes_fictives.geojson",driver="GeoJSON")
    villages.to_file(out/"localites_fictives.geojson",driver="GeoJSON")
    # Deliberately unordered: Cartomize derives drawing order from roles.
    layers=[{"data":villages,"name":"Localités","labels":"auto","markersize":25},
            {"data":roads,"name":"Routes"},
            {"data":aoi,"name":"Limite de la zone"},
            {"data":product.path,"name":"Image multibande","rgb":"natural"},
            {"data":river,"name":"Rivière","linewidth":1.3}]
    carte=cm.compose_map(layers,aoi=aoi,crs=32733,
        title="De deux scènes à une carte",
        subtitle="Démonstration fictive · mosaïque, bandes, découpage et superposition",
        credits="Données entièrement synthétiques | Cartomize / Cédrick Belmich | WGS 84 / UTM 33S")
    carte.export(out/"carte_automatique.png",dpi=180,overwrite=True)
    carte.export(out/"carte_automatique.pdf",dpi=180,overwrite=True)
    (out/"ordre_des_couches.json").write_text(json.dumps(carte.layer_plan(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import ListedColormap
    fig=Figure(figsize=(12,4.5),dpi=140,facecolor="#f7f8f5");FigureCanvasAgg(fig)
    for i,(filename,title) in enumerate([
        ("couleurs_naturelles.tif","Couleurs naturelles · R, V, B"),
        ("fausses_couleurs.tif","Végétation · PIR, R, V"),
        ("multibande_source_index.tif","Origine des pixels · A / B")],1):
        ax=fig.add_subplot(1,3,i)
        if i<3:
            rgba,extent,_=cm.read_rgb(out/filename,bands="native")
            ax.imshow(rgba,extent=extent)
        else:
            with rasterio.open(out/filename) as src:
                ax.imshow(src.read(1,masked=True),cmap=ListedColormap(["#39776a","#c8a45e"]),vmin=1,vmax=2)
        ax.set_title(title,fontsize=10,pad=15,color="#203b36");ax.axis("off")
    fig.suptitle("Un GeoTIFF multibande, plusieurs usages",fontsize=18,x=.5,y=.96,color="#203b36")
    fig.text(.5,.13,"Données synthétiques — le blanc indique les zones exclues ou sans pixel valide.",ha="center",fontsize=10,color="#52635c")
    fig.text(.5,.07,f"Résolution commune : 20 m · 5 bandes · couverture valide de la zone : {product.report['coverage_percent']:.1f} %",ha="center",fontsize=10,color="#52635c")
    fig.subplots_adjust(left=.03,right=.97,top=.82,bottom=.22,wspace=.08)
    fig.savefig(out/"comparaison.png",dpi=140)
    print(json.dumps({"output":str(out),"coverage_percent":product.report["coverage_percent"],
                      "scene_contributions":{s["id"]:s["contributed_pixels"] for s in product.report["scenes"]}},indent=2))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="output/imagery")
    main(parser.parse_args().output)
