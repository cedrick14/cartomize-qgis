"""Technical map checks and complete, blockwise thematic-code validation."""
from pathlib import Path
import numpy as np
import rasterio


def audit_map(map_object):
    issues=[]
    def issue(severity,code,message,layer=None):issues.append(dict(severity=severity,code=code,message=message,layer=layer))
    if not map_object.layers:issue('error','empty_map','Ajouter au moins une couche.')
    if not map_object.title.strip():issue('warning','missing_title','Le titre de la carte est vide.')
    if not map_object.credits.strip():issue('warning','missing_sources','Renseigner les sources et l’auteur.')
    if not map_object.legend_enabled:issue('info','legend_disabled','La légende est désactivée.')
    for layer in map_object.layers:
        if layer.kind=='vector':
            data=layer.data
            usable=data.geometry.notna()&~data.geometry.is_empty
            if not usable.any():issue('warning','empty_layer','Couche sans géométrie représentable.',layer.name)
            invalid=int((usable&~data.geometry.is_valid).sum())
            if invalid:issue('error','invalid_geometry',f'{invalid} géométries invalides : réparer avant export.',layer.name)
            if layer.column and layer.column not in data:issue('error','missing_field','Champ thématique absent.',layer.name)
        else:
            try:
                with rasterio.open(layer.data) as src:
                    ratio=min(1,256/max(src.width,src.height));shape=(max(1,int(src.height*ratio)),max(1,int(src.width*ratio)))
                    sample=np.ma.masked_invalid(src.read(layer.band,out_shape=shape,masked=True))
                    values=sample.compressed()
                    if not values.size:issue('warning','empty_raster_sample','Aucun pixel valide dans l’échantillon de contrôle ; vérifier l’emprise.',layer.name)
                    if layer.classes:
                        from .nodata import _windows
                        for window in _windows(src,512):
                            codes=np.ma.masked_invalid(src.read(layer.band,window=window,masked=True)).compressed()
                            unknown=codes[~np.isin(codes,list(layer.classes))]
                            if unknown.size:
                                issue('error','unmapped_classes','Codes absents de la nomenclature : '+', '.join(map(str,np.unique(unknown)[:20])),layer.name)
                                break
            except (OSError,rasterio.errors.RasterioError,ValueError,IndexError) as exc:
                issue('error','unreadable_raster',str(exc),layer.name)
        if layer.classes and any(str(v[0]).startswith('Classe ') for v in layer.classes.values()):
            issue('warning','generic_labels','Vérifier les libellés génériques de la nomenclature.',layer.name)
    if map_object.plan:
        for item in map_object.plan.items:
            if item.kind=='table' and item.item_id not in map_object.tables:issue('warning','empty_table',f'Tableau non renseigné : {item.item_id}')
            if item.kind=='chart' and item.item_id not in map_object.charts:issue('warning','empty_chart',f'Graphique non renseigné : {item.item_id}')
    return dict(schema='cartomize.map.audit.v1',valid=not any(i['severity']=='error' for i in issues),issues=issues,
                layer_plan=map_object.layer_plan(),scope='Geometry validity, fields, full raster class coverage and layout metadata.',
                limitations=['Not a certification of scientific accuracy or completeness.','Raster emptiness uses a sample; class coverage is checked by blocks.',
                             'Label collisions, text overflow and all spatial relations are not exhaustively checked.'])
