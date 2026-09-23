"""Priority-Flood depression filling and acyclic D8 catchment analysis.

Boundary cells and cells adjacent to NoData are open outlets. Flat cells follow
the Priority-Flood parent tree; descending cells use the steepest D8 gradient.
Accumulation includes the cell itself. This is terrain drainage, not discharge
or hydraulic simulation. Global arrays require an explicit memory budget.
"""
from pathlib import Path
from collections import deque
import heapq
import numpy as np
import rasterio
from scipy.ndimage import binary_erosion
from .storage import new_directory,save_json
from ._validation import linear_factor
from .imagery import _check_cancel

_D8=((0,1,1),(1,1,2),(1,0,4),(1,-1,8),(0,-1,16),(-1,-1,32),(-1,0,64),(-1,1,128))


def hydrology(source,destination,*,band=1,stream_threshold=1000,outlets=None,outlet_field=None,
              memory_limit_mb=512,progress=None,cancel=None):
    """Produce filled DEM, directions, accumulation, streams and watersheds.

    Optional outlet points must lie in valid cells. They are not silently snapped
    to a stream. With nested outlets a cell belongs to its first downstream outlet.
    """
    if not np.isfinite(stream_threshold) or stream_threshold<1:raise ValueError('Le seuil hydrographique doit être au moins un pixel.')
    if not np.isfinite(memory_limit_mb) or memory_limit_mb<16:raise ValueError('Budget mémoire insuffisant.')
    _check_cancel(cancel)
    with rasterio.open(source) as src:
        factor=linear_factor(src.crs);t=src.transform
        if t.b or t.d or t.a<=0 or t.e>=0:raise ValueError('Reprojeter le MNT sur une grille orientée au nord.')
        if src.width*src.height*240>memory_limit_mb*1024**2:raise ValueError('MNT trop grand pour le budget global ; augmenter memory_limit_mb ou découper un bassin complet.')
        z=src.read(band,masked=True).astype('float64')*src.scales[band-1]+src.offsets[band-1]
        valid=~np.ma.getmaskarray(z)&np.isfinite(z.data);profile=src.profile.copy();crs=src.crs
    if not valid.any():raise ValueError('Le MNT ne contient aucun pixel valide.')
    height,width=valid.shape;n=height*width;filled=z.filled(np.nan).ravel();mask=valid.ravel()
    boundary=valid&~binary_erosion(valid,structure=np.ones((3,3)),border_value=0)
    seen=boundary.ravel().copy();parent=np.full(n,-1,dtype='int64');rank=np.full(n,-1,dtype='int64')
    heap=[(filled[int(i)],int(i)) for i in np.flatnonzero(boundary)];heapq.heapify(heap);visited=0
    while heap:
        level,i=heapq.heappop(heap);rank[i]=visited;visited+=1;y,x=divmod(i,width)
        if visited%4096==0:_check_cancel(cancel)
        for dy,dx,_ in _D8:
            ny,nx=y+dy,x+dx
            if 0<=ny<height and 0<=nx<width:
                j=ny*width+nx
                if mask[j] and not seen[j]:
                    seen[j]=True;parent[j]=i;filled[j]=max(level,filled[j]);heapq.heappush(heap,(filled[j],j))
    if progress:progress(1,4)
    downstream=np.full(n,-1,dtype='int64');direction=np.zeros(n,dtype='uint8')
    dxm=t.a*factor;dym=-t.e*factor
    elevations=filled.reshape(height,width);best=np.zeros((height,width),dtype='float64')
    indexes=np.arange(n,dtype='int64').reshape(height,width)
    receiver=downstream.reshape(height,width);codes=direction.reshape(height,width)
    for dy,dx,d in _D8:
        _check_cancel(cancel)
        y0,y1=max(0,-dy),min(height,height-dy);x0,x1=max(0,-dx),min(width,width-dx)
        region=(slice(y0,y1),slice(x0,x1));neighbour=(slice(y0+dy,y1+dy),slice(x0+dx,x1+dx))
        gradient=(elevations[region]-elevations[neighbour])/np.hypot(dx*dxm,dy*dym)
        take=valid[region]&valid[neighbour]&(gradient>best[region])
        best[region][take]=gradient[take];receiver[region][take]=indexes[neighbour][take];codes[region][take]=d
    flats=np.flatnonzero(mask&(downstream<0)&(parent>=0));downstream[flats]=parent[flats]
    for dy,dx,d in _D8:
        select=(parent[flats]//width-flats//width==dy)&(parent[flats]%width-flats%width==dx)
        direction[flats[select]]=d
    degree=np.zeros(n,dtype='int32');targets=downstream[downstream>=0];np.add.at(degree,targets,1)
    queue=deque(int(i) for i in np.flatnonzero(mask&(degree==0)));order=[];accumulation=mask.astype('float64')
    while queue:
        i=queue.popleft();order.append(i);j=downstream[i]
        if len(order)%4096==0:_check_cancel(cancel)
        if j>=0:
            accumulation[j]+=accumulation[i];degree[j]-=1
            if degree[j]==0:queue.append(int(j))
    if len(order)!=int(mask.sum()):raise RuntimeError('Cycle détecté dans les directions d’écoulement.')
    if progress:progress(2,4)
    basins=np.zeros(n,dtype='int32');pour_points={}
    if outlets is not None:
        from ._validation import frame
        points=frame(outlets).to_crs(crs)
        if points.empty or not points.geom_type.eq('Point').all():raise ValueError('Les exutoires doivent être des points.')
        if outlet_field is not None and outlet_field not in points:raise ValueError('Champ des exutoires absent.')
        for number,(_,row) in enumerate(points.iterrows(),1):
            y,x=rasterio.transform.rowcol(t,row.geometry.x,row.geometry.y)
            if not (0<=y<height and 0<=x<width and valid[y,x]):raise ValueError('Exutoire en dehors du MNT valide.')
            cell=y*width+x
            if cell in pour_points:raise ValueError('Plusieurs exutoires occupent le même pixel.')
            pour_points[cell]=dict(code=number,label=str(row[outlet_field]) if outlet_field else str(number));basins[cell]=number
    else:
        for number,i in enumerate(np.flatnonzero(mask&(downstream<0)),1):basins[i]=number
    for i in reversed(order):
        if not basins[i] and downstream[i]>=0:basins[i]=basins[downstream[i]]
    profile.update(driver='GTiff',count=1,tiled=True,blockxsize=256,blockysize=256,compress='lzw',BIGTIFF='IF_SAFER')
    profile.pop('photometric',None)
    destination=Path(destination).resolve()
    with new_directory(destination) as work:
        def write(name,data,dtype,nodata):
            _check_cancel(cancel);p=dict(profile,dtype=dtype,nodata=nodata)
            values=data.reshape(height,width).astype(dtype);values[~valid]=nodata
            with rasterio.open(work/(name+'.tif'),'w',**p) as dst:dst.write(values,1);dst.set_band_description(1,name)
        write('filled',filled,'float64',np.nan);write('direction',direction,'uint16',65535)
        write('accumulation',accumulation,'float64',np.nan)
        write('streams',accumulation>=stream_threshold,'uint8',255);write('watersheds',basins,'int32',-1)
        report=dict(schema='cartomize.hydrology.v1',method='Priority-Flood / steepest D8; flat parent tree',
            accumulation_includes_cell=True,valid_cells=int(mask.sum()),outlet_count=int((mask&(downstream<0)).sum()),
            contributing_area_per_cell_m2=dxm*dym,pour_points=list(pour_points.values()),stream_threshold=stream_threshold,
            boundaries='Raster edge and NoData neighbours are open outlets.',
            outputs={name:str(destination/(name+'.tif')) for name in ('filled','direction','accumulation','streams','watersheds')})
        save_json(report,work/'hydrology.json');_check_cancel(cancel)
    if progress:progress(4,4)
    return destination/'accumulation.tif'
