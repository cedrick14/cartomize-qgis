"""Data-driven cartographic recommendations with explicit reasons and limits."""
from pathlib import Path
import rasterio
from .project import analyze_project
from .scenes import discover_scenes
from .templates import list_templates
from ._validation import frame
from .imagery import _check_cancel

GOALS={'general':'Carte générale','administrative':'Carte administrative','landcover':'Occupation du sol','atlas':'Atlas cartographique'}
TOOL_LABELS={'processing':'Chaîne de traitements','classification':'Classification', 'recipes':'Recettes et production en série', 'native':'Projets SIG', 'mapops':'Révision cartographique', 'terrain':'Analyse de terrain', 'project':'Analyse du projet','prepare':'Prétraitement multispectral','composite':'Composition colorée',
             'vector':'Traitements vectoriels','raster':'Traitements raster','indices':'Indices spectraux',
             'calculator':'Calculatrice raster','focal':'Statistiques focales','temporal':'Statistiques multirasters',
             'mapping':'Mise en page','atlas':'Atlas cartographique','workflow':'Production automatisée','inspect':'Analyse des couches'}


def assess_project(inputs,*,data_kind='layers',goal='general',aoi=None,progress=None,cancel=None):
    """Read-only preflight and ordered proposals; no classification is inferred.

    Each unreadable input becomes an error in the report rather than a false
    success. Raster metadata are sampled by analyze_project; vector geometry
    validity is checked in full. Scenarios are recommendations, not execution.
    """
    if goal not in GOALS:raise ValueError('Objectif cartographique inconnu.')
    if data_kind not in {'layers','scenes'}:raise ValueError('Choisir des couches ou des scènes.')
    inputs=[inputs] if isinstance(inputs,(str,Path)) else list(inputs)
    if not inputs:raise ValueError('Importer les données du projet.')
    paths=[str(Path(x['data'] if isinstance(x,dict) else x).expanduser().resolve()) for x in inputs];issues=[];layers=[];scenes=[];steps=[]
    def issue(severity,code,message,tool=None):issues.append(dict(severity=severity,code=code,message=message,tool=tool))
    def step(tool,reason,optional=False):
        if tool not in {s['tool'] for s in steps}:steps.append(dict(tool=tool,title=TOOL_LABELS[tool],reason=reason,optional=optional))
    _check_cancel(cancel)
    if data_kind=='scenes':
        try:
            found=discover_scenes(paths)
            for i,scene in enumerate(found,1):
                _check_cancel(cancel)
                for band in scene.bands.values():
                    with rasterio.open(band.path) as src:
                        if src.crs is None:issue('error','missing_crs',f'Système de coordonnées absent : {band.path}')
                scenes.append(dict(id=scene.scene_id,sensor=scene.sensor,date=scene.acquired,bands=list(scene.bands),quality=bool(scene.quality)))
                if not scene.quality:issue('warning','missing_quality',f'Masque QA/SCL absent : {scene.scene_id}.','prepare')
                if progress:progress(i,len(found))
            if len({s.sensor for s in found})>1 or len({s.level for s in found})>1:issue('error','mixed_sensors','Harmoniser les capteurs et niveaux avant mosaïque.')
            if len({s.acquired for s in found})>1:issue('warning','mixed_dates','Les dates diffèrent ; confirmer une mosaïque multitemporelle.','prepare')
            step('prepare','Calibrer, appliquer la qualité, aligner les scènes, mosaïquer et découper.')
            step('composite','Produire le RVB depuis le multibande scientifique.')
            step('project','Préparer les couches complémentaires et leur symbologie.')
        except (OSError,ValueError,rasterio.errors.RasterioError) as exc:issue('error','scene_discovery',str(exc),'prepare')
    else:
        needs_composite=False
        for i,path in enumerate(paths,1):
            _check_cancel(cancel)
            try:
                layer_input={**inputs[i-1],'data':path} if isinstance(inputs[i-1],dict) else path
                record=analyze_project([layer_input],cancel=cancel)['layers'][0];layers.append(record);diagnostic=record['diagnostic']
                if record['kind']=='vector':
                    if diagnostic['invalid_geometries']:issue('error','invalid_geometry',f"{record['name']} : géométries invalides à réparer.",'vector')
                    if diagnostic['missing_geometries'] or diagnostic['empty_geometries']:issue('warning','empty_geometry',f"{record['name']} : géométries vides ou absentes.",'vector')
                else:
                    if not diagnostic['valid_sample_pixels']:issue('warning','empty_sample',f"{record['name']} : aucun pixel valide dans l’échantillon.",'inspect')
                    if record['border_values']:issue('warning','background_candidate',f"{record['name']} : fond périphérique proposé {record['border_values']}. Vérifier les valeurs à conserver.",'project')
                    if diagnostic['bands']>=3 and not diagnostic['native_rgb']:needs_composite=True
            except (OSError,ValueError,rasterio.errors.RasterioError) as exc:issue('error','unreadable_input',f'{Path(path).name} : {exc}')
            if progress:progress(i,len(paths))
        if any(i['tool']=='vector' for i in issues):step('vector','Corriger les géométries signalées avant la production.')
        step('project','Contrôler le NoData, la nomenclature et les rôles des couches.')
        if needs_composite:step('composite','Choisir les canaux de visualisation ; conserver le multibande scientifique.')
        systems={r['diagnostic']['crs'] for r in layers}
        if len(systems)>1:issue('info','multiple_crs','Les systèmes diffèrent ; choisir le système cible. La superposition les reprojette au rendu.','mapping')
    if aoi:
        try:
            zones=frame(aoi)
            if zones.empty or not zones.geom_type.isin(['Polygon','MultiPolygon']).all() or not zones.geometry.is_valid.all():
                issue('error','invalid_aoi','La zone d’étude doit contenir des polygones valides.','vector')
        except (OSError,ValueError) as exc:issue('error','aoi',str(exc))
    if goal=='landcover':issue('info','classification_scope','Une composition colorée n’est pas une classification. Fournir une couche classifiée et sa nomenclature.','project')
    step('mapping','Composer les couches, choisir l’habillage, contrôler la carte et exporter.')
    if goal=='atlas':step('atlas','Définir la couche d’index et produire une page par entité.')
    category={'landcover':'occupation_sol','administrative':'administrative'}.get(goal)
    candidates=list_templates(category) if category else []
    recommendation=min(candidates,key=lambda t:(t['map_frames'],t['id'])) if candidates else None
    if recommendation and recommendation['map_frames']>1:
        issue('info','template_frames','La maquette proposée comporte plusieurs cadres ; préciser leurs emprises et leurs couches.','mapping')
    return dict(schema='cartomize.assistant.v1',data_kind=data_kind,goal=goal,inputs=paths,aoi=str(aoi) if aoi else None,
                layers=layers,scenes=scenes,issues=issues,steps=steps,ready=not any(i['severity']=='error' for i in issues),
                recommended_template=recommendation,
                limitations=['Rule-based recommendations; no LLM or supervised land-cover classifier.',
                             'No complete native APRX/QGZ or spatial-relationship audit.',
                             'Scientific correctness and final cartographic design require user review.'])
