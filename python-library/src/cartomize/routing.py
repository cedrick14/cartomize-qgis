"""Metric shortest paths on noded line networks using Dijkstra's algorithm."""
import heapq
import numpy as np
import geopandas as gpd
from shapely.geometry import Point,LineString
from shapely.ops import unary_union
from scipy.spatial import cKDTree
from ._validation import frame,measurement_frame
from .imagery import _check_cancel


def shortest_path(source,start,end,*,points_crs=None,metric_crs=None,max_snap_m=1000,
                  node_intersections=True,progress=None,cancel=None):
    """Shortest bidirectional distance between nodes snapped to two coordinates.

    Coordinates default to the network CRS. Lines are split at vertices and,
    optionally, geometric intersections. Bridges at different levels require
    node_intersections=False and an already topologically prepared network.
    No turn restrictions or travel-time assumptions are inferred.
    """
    original=frame(source);work,factor=measurement_frame(original,metric_crs)
    if work.empty or not work.geom_type.isin(['LineString','MultiLineString']).all():raise ValueError('Le réseau doit contenir des lignes.')
    if work.geometry.isna().any() or work.geometry.is_empty.any() or not work.geometry.is_valid.all():raise ValueError('Le réseau contient des géométries invalides.')
    if not np.isfinite(max_snap_m) or max_snap_m<0:raise ValueError('La distance de rattachement doit être positive ou nulle.')
    coords=np.asarray([start,end],dtype=float)
    if coords.shape!=(2,2) or not np.isfinite(coords).all():raise ValueError('Départ et arrivée : deux coordonnées finies [x, y].')
    points=gpd.GeoSeries([Point(*coords[0]),Point(*coords[1])],crs=points_crs or original.crs).to_crs(work.crs)
    _check_cancel(cancel)
    geometries=list(work.geometry.explode(index_parts=False))
    if node_intersections:
        merged=unary_union(geometries);geometries=list(merged.geoms) if hasattr(merged,'geoms') else [merged]
    nodes={};locations=[];adj=[]
    def node(xy):
        key=tuple(map(float,xy[:2]))
        if key not in nodes:nodes[key]=len(locations);locations.append(key);adj.append({})
        return nodes[key]
    for number,line in enumerate(geometries):
        if number%1024==0:_check_cancel(cancel)
        pairs=list(line.coords)
        for a,b in zip(pairs,pairs[1:]):
            u,v=node(a),node(b);distance=float(np.linalg.norm(np.asarray(a[:2])-b[:2]))*factor
            if distance>0:adj[u][v]=min(adj[u].get(v,np.inf),distance);adj[v][u]=adj[u][v]
    if not nodes:raise ValueError('Le réseau ne contient aucun segment de longueur positive.')
    tree=cKDTree(locations);dist,index=tree.query([[p.x,p.y] for p in points]);dist=np.asarray(dist)*factor
    if (dist>max_snap_m).any():raise ValueError('Aucun nœud du réseau dans la distance de rattachement demandée.')
    first,last=map(int,index);cost={first:0.};previous={};heap=[(0.,first)];done=set()
    while heap:
        distance,u=heapq.heappop(heap)
        if u in done:continue
        done.add(u)
        if len(done)%1024==0:_check_cancel(cancel)
        if u==last:break
        for v,weight in adj[u].items():
            value=distance+weight
            if value<cost.get(v,np.inf):cost[v]=value;previous[v]=u;heapq.heappush(heap,(value,v))
    if last not in done:raise ValueError('Départ et arrivée appartiennent à des composantes déconnectées.')
    route=[last]
    while route[-1]!=first:route.append(previous[route[-1]])
    route.reverse();points_out=[locations[i] for i in route]
    if len(points_out)==1:points_out*=2
    result=gpd.GeoDataFrame(dict(distance_m=[cost[last]],start_snap_m=[dist[0]],end_snap_m=[dist[1]],nodes=[len(route)]),geometry=[LineString(points_out)],crs=work.crs).to_crs(original.crs)
    _check_cancel(cancel)
    if progress:progress(1,1)
    return result
