"""Raster background diagnosis and reversible, blockwise validity masks."""
from array import array
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.ndimage import label
from .imagery import _check_cancel
from .raster import _writer


def _bands(src):
    return tuple(i for i,c in enumerate(src.colorinterp,1) if c.name!='alpha')


def _windows(src,size):
    for y in range(0,src.height,size):
        for x in range(0,src.width,size):
            yield Window(x,y,min(size,src.width-x),min(size,src.height-y))


def _matches(data,values):
    mask=np.zeros(data.shape[1:],dtype=bool)
    for value in values:mask|=np.all(data==value,axis=0)
    return mask


def detect_background(source,*,max_size=1024,keep_values=()):
    """Inspect spatial evidence; only conservative padding candidates are selected.

    NoData metadata remains authoritative. Binary 0/1 and uniform rasters never
    receive automatic additional masks. An ambiguous real class touching the
    border cannot be distinguished from padding without semantic information.
    """
    if not isinstance(max_size,int) or max_size<32:raise ValueError('max_size must be at least 32.')
    with rasterio.open(source) as src:
        bands=_bands(src)
        if not bands:raise ValueError('No data band found.')
        ratio=min(1,max_size/max(src.width,src.height))
        h,w=max(1,int(src.height*ratio)),max(1,int(src.width*ratio))
        data=src.read(bands,out_shape=(len(bands),h,w))
        valid=np.all(src.read_masks(bands,out_shape=(len(bands),h,w))>0,axis=0)&np.isfinite(data).all(axis=0)
        native_rgb=(len(bands)==3 and all(src.dtypes[i-1]=='uint8' for i in bands)
                    and tuple(c.name for c in src.colorinterp[:3])==('red','green','blue'))
        unique=np.unique(data[0][valid])
        binary=src.count==1 and 0<len(unique)<=2 and set(unique.tolist())<={0,1}
        categorical=src.count==1 and 1<len(unique)<=65 and np.isfinite(unique).all() and np.all(unique==np.round(unique))
        # Spatial evidence is sampled; the subsequent mask uses original pixels.
        border=np.zeros((h,w),bool);border[[0,-1],:]=True;border[:,[0,-1]]=True
        corners=np.zeros((h,w),bool);s=max(1,min(h,w)//10)
        corners[:s,:s]=True;corners[:s,-s:]=True;corners[-s:,:s]=True;corners[-s:,-s:]=True
        center=np.zeros((h,w),bool);center[h//4:max(h//4+1,3*h//4),w//4:max(w//4+1,3*w//4)]=True
        candidates=[]
        values=[0.,255.] if native_rgb else [float(v) for v in unique if v==0 or v==255 or v<=-999 or v>=9999] if categorical else []
        for value in values:
            matched=_matches(data,(value,))&valid
            b=float(matched[border].mean());c=float(matched[center].mean());k=float(matched[corners].mean())
            strong=b>=.8 and k>=.9 and c<=.35 and b-c>=.5
            automatic=strong and not binary and value not in keep_values and not matched.all()
            if b or k:
                candidates.append(dict(value=value,border_fraction=b,center_fraction=c,corner_fraction=k,
                    automatic=automatic,reason='Spatial padding pattern' if strong else 'Insufficient spatial evidence'))
        return dict(path=str(Path(source).resolve()),width=src.width,height=src.height,bands=src.count,
            bounds=list(src.bounds),descriptions=list(src.descriptions),product=src.tags().get('CARTOMIZE_PRODUCT'),
            valid_sample_pixels=int(valid.sum()),sample_values=[float(v) for v in unique] if len(unique)<=65 else None,
            sample_shape=[h,w],sampled_pixels=h*w,crs=str(src.crs),dtype=src.dtypes[0],
            declared_nodata=[float(v) if v is not None and np.isfinite(v) else 'NaN' if v is not None else None for v in src.nodatavals],
            mask_flags=[[v.name for v in flags] for flags in src.mask_flag_enums],
            candidates=candidates,automatic_border_values=[v['value'] for v in candidates if v['automatic']],
            binary_zero_preserved=binary,native_rgb=native_rgb,
            ambiguous_values=[v['value'] for v in candidates if not v['automatic'] and v['value'] not in keep_values],
            background_method='sampled_border_pattern',
            decision_required=bool(binary and 0 in unique or any(not v['automatic'] for v in candidates)),
            note='Background inference is heuristic; sources and interior disconnected values remain unchanged.')


class _Components:
    """Union/find of components touching tile edges, never full-image labels."""
    def __init__(self,limit):self.parents=array('q',[0]);self.edge=bytearray([0]);self.limit=limit
    def add(self):
        if len(self.parents)>self.limit:raise ValueError('Too many border components; increase max_components or specify declared NoData only.')
        ident=len(self.parents);self.parents.append(ident);self.edge.append(0);return ident
    def root(self,node):
        while self.parents[node]!=node:
            self.parents[node]=self.parents[self.parents[node]];node=self.parents[node]
        return node
    def union(self,a,b):
        a,b=self.root(int(a)),self.root(int(b))
        if a!=b:
            if a>b:a,b=b,a
            self.parents[b]=a;self.edge[a]|=self.edge[b]
    def join(self,a,b):
        valid=(a>0)&(b>0)
        if valid.any():
            for x,y in np.unique(np.column_stack((a[valid],b[valid])),axis=0):self.union(x,y)


def mask_background(source,destination,*,border_values=(),nodata_values=(),keep_values=(),
                    block_size=512,max_components=2_000_000,overwrite=False,progress=None,cancel=None,valid_footprint=None):
    """Copy all bands and write an internal mask without changing input pixels.

    Additional border values are removed only in 4-connected components touching
    the raster boundary. Explicit nodata_values apply globally. keep_values
    overrides these extra rules, never provider masks/NoData. Raster arrays are
    read in tiles; component metadata grows with tile and edge-component counts.
    max_components limits identifiers, not the process's total memory usage.
    """
    if not isinstance(block_size,int) or not 32<=block_size<=2048:raise ValueError('block_size must be 32..2048.')
    if not isinstance(max_components,int) or max_components<1:raise ValueError('max_components must be positive.')
    border_values=tuple(float(v) for v in border_values if v not in keep_values)
    nodata_values=tuple(float(v) for v in nodata_values if v not in keep_values)
    if not all(np.isfinite(v) for v in (*border_values,*nodata_values)):raise ValueError('Additional NoData values must be finite.')
    _check_cancel(cancel)
    with rasterio.open(source) as src:
        if src.crs is None:raise ValueError('The raster has no CRS.')
        if len(set(src.dtypes))!=1:raise ValueError('Bands with different data types require separate outputs.')
        footprint=None
        if valid_footprint is not None:
            from ._validation import frame
            footprint=frame(valid_footprint).to_crs(src.crs)
            if footprint.empty or not footprint.geom_type.isin(['Polygon','MultiPolygon']).all() or not footprint.geometry.is_valid.all():raise ValueError('L’emprise valide doit contenir des polygones valides.')
            footprint=list(footprint.geometry)
        bands=_bands(src);tiles=math.ceil(src.width/block_size)*math.ceil(src.height/block_size)
        total=tiles*(2 if border_values else 1);components=_Components(max_components);records=[]
        if border_values:
            top=np.zeros(src.width,dtype='int64');left=None;previous_y=-1
            for number,window in enumerate(_windows(src,block_size),1):
                _check_cancel(cancel);x,y,w,h=map(int,(window.col_off,window.row_off,window.width,window.height))
                if y!=previous_y:left=None;previous_y=y
                data=src.read(bands,window=window)
                labels,_=label(_matches(data,border_values))
                edge_labels=np.unique(np.concatenate((labels[0],labels[-1],labels[:,0],labels[:,-1])))
                edge_labels=edge_labels[edge_labels>0];nodes=np.array([components.add() for _ in edge_labels],dtype='int64')
                lookup=np.zeros(int(labels.max())+1,dtype='int64');lookup[edge_labels]=nodes
                grid=lookup[labels]
                if y>0:components.join(grid[0],top[x:x+w])
                if x>0:components.join(grid[:,0],left)
                if y==0:
                    for node in np.unique(grid[0]):
                        if node:components.edge[components.root(int(node))]=1
                if x==0:
                    for node in np.unique(grid[:,0]):
                        if node:components.edge[components.root(int(node))]=1
                if y+h==src.height:
                    for node in np.unique(grid[-1]):
                        if node:components.edge[components.root(int(node))]=1
                if x+w==src.width:
                    for node in np.unique(grid[:,-1]):
                        if node:components.edge[components.root(int(node))]=1
                top[x:x+w]=grid[-1];left=grid[:,-1].copy();records.append((edge_labels,nodes))
                if progress:progress(number,total)
        profile=src.profile.copy();profile.update(driver='GTiff',compress='lzw',tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER')
        profile.pop('photometric',None)
        counts=dict(provider_invalid=0,additional_border_masked=0,additional_value_masked=0,outside_footprint_masked=0,valid_pixels=0)
        # A single TIFF must retain its mask when moved to its final name.
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with _writer(destination,profile,overwrite=overwrite,sources=(source,)) as dst:
                for number,window in enumerate(_windows(src,block_size),1):
                    _check_cancel(cancel);all_data=src.read(window=window);data=all_data[np.array(bands)-1]
                    valid=np.all(src.read_masks(bands,window=window)>0,axis=0)&np.isfinite(data).all(axis=0)
                    counts['provider_invalid']+=int((~valid).sum())
                    border_mask=np.zeros(valid.shape,bool)
                    if border_values:
                        labels,_=label(_matches(data,border_values));edge_labels,nodes=records[number-1]
                        remove=[ident for ident,node in zip(edge_labels,nodes) if components.edge[components.root(int(node))]]
                        border_mask=np.isin(labels,remove)
                    explicit=_matches(data,nodata_values)
                    counts['additional_border_masked']+=int((border_mask&valid).sum())
                    counts['additional_value_masked']+=int((explicit&valid&~border_mask).sum())
                    valid&=~border_mask&~explicit
                    if footprint is not None:
                        from rasterio.features import geometry_mask
                        inside=geometry_mask(footprint,out_shape=valid.shape,transform=src.window_transform(window),invert=True)
                        counts['outside_footprint_masked']+=int((valid&~inside).sum());valid&=inside
                    counts['valid_pixels']+=int(valid.sum())
                    dst.write(all_data,window=window);dst.write_mask(valid.astype('uint8')*255,window=window)
                    if progress:progress((tiles if border_values else 0)+number,total)
                dst.descriptions=src.descriptions;dst.scales=src.scales;dst.offsets=src.offsets;dst.colorinterp=src.colorinterp
                dst.update_tags(**src.tags())
                for band in src.indexes:
                    if src.units[band-1]:dst.set_band_unit(band,src.units[band-1])
                    dst.update_tags(band,**src.tags(band))
                    try:dst.write_colormap(band,src.colormap(band))
                    except ValueError:pass
                dst.update_tags(CARTOMIZE_MASK='provider_and_border_connected',CARTOMIZE_SOURCE=str(Path(source).resolve()))
                _check_cancel(cancel)
    return dict(path=str(Path(destination).resolve()),border_values=border_values,nodata_values=nodata_values,**counts)
