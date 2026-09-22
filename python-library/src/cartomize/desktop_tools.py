"""Desktop access to the existing vector and raster processing APIs."""
from pathlib import Path
import json
import os
import tempfile
import math
import numpy as np
from PySide6.QtWidgets import QComboBox,QLineEdit,QLabel,QPlainTextEdit,QPushButton
import cartomize as cm
from .desktop import Page,PathField,spin,real,RASTER_FILTER,VECTOR_FILTER
from ._validation import output_path


def _json_value(value):
    if isinstance(value,dict):return {str(k):_json_value(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_json_value(v) for v in value]
    if isinstance(value,np.generic):return _json_value(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,(str,int,float,bool)) or value is None:return value
    return str(value)


def write_result(result,destination,*,sources=(),overwrite=False):
    """Stage a single table/vector/report file; never overwrite an input."""
    destination=output_path(destination,overwrite,sources)
    suffix=destination.suffix.lower()
    if suffix not in {'.json','.csv','.geojson','.gpkg'}:raise ValueError('Choisir un fichier JSON, CSV, GeoJSON ou GeoPackage selon le résultat.')
    with tempfile.TemporaryDirectory(prefix='.cartomize-output-',dir=destination.parent) as temporary:
        staged=Path(temporary)/destination.name
        if isinstance(result,dict):
            if suffix!='.json':raise ValueError('Le rapport doit être enregistré en JSON.')
            staged.write_text(json.dumps(_json_value(result),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        elif hasattr(result,'geometry'):
            if suffix not in {'.gpkg','.geojson'}:raise ValueError('Une couche vectorielle exige un fichier .gpkg ou .geojson.')
            result.to_file(staged,driver='GPKG' if suffix=='.gpkg' else 'GeoJSON',index=False)
        else:
            if suffix!='.csv':raise ValueError('Le tableau doit être enregistré en CSV.')
            result.to_csv(staged,index=False)
        os.replace(staged,destination)
    return destination


class InspectionPage(Page):
    engine=False
    cancellable=False
    def __init__(self):
        super().__init__('Analyse des couches','Contrôle des géométries, des attributs, des systèmes de coordonnées, des bandes et du NoData.')
        self.kind=QComboBox();self.kind.addItem('Couche vectorielle','vector');self.kind.addItem('Raster','raster')
        self.source=PathField(filter=VECTOR_FILTER);self.band=spin();self.report=QPlainTextEdit();self.report.setReadOnly(True)
        self.report.setMinimumHeight(260);self.report.setPlaceholderText('Le rapport sera affiché ici après analyse.')
        self.form.addRow('Type de données',self.kind);self.form.addRow('Couche',self.source);self.form.addRow('Bande raster',self.band)
        note=QLabel('Les diagnostics raster reposent sur un échantillon. Les valeurs NoData suggérées ne sont pas appliquées aux données.')
        note.setWordWrap(True);self.form.addRow(note);self.form.addRow(self.report)
        self.output.filter='Rapport JSON (*.json)';self.finish()
        self.kind.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        raster=self.kind.currentData()=='raster';self.source.filter=RASTER_FILTER if raster else VECTOR_FILTER
        self.band.setVisible(raster);self.form.labelForField(self.band).setVisible(raster)
    def job(self,options):
        source=self.source.text();kind=self.kind.currentData();band=self.band.value();destination=self.destination()
        def run(progress,cancel):
            result=cm.raster.inspect(source,band=band) if kind=='raster' else cm.vector.analyze(source,name=Path(source).stem)
            return write_result(result,destination,sources=(source,),overwrite=options['overwrite'])
        return run
    def show_result(self,path):self.report.setPlainText(Path(path).read_text(encoding='utf-8'))


class VectorPage(Page):
    engine=False
    cancellable=False
    OPERATIONS=[('Découpage','clip'),('Zone tampon','buffer'),('Intersection','intersection'),('Union','union'),
                ('Différence','difference'),('Différence symétrique','symmetric_difference'),('Jointure spatiale','sjoin'),
                ('Dissolution','dissolve'),('Reprojection','reproject'),('Réparation des géométries','make_valid'),
                ('Calcul des superficies','area'),('Calcul des longueurs','length'),('Proximité','nearest')]
    def __init__(self):
        super().__init__('Traitements vectoriels','Opérations géométriques, superpositions, jointures spatiales et mesures.')
        self.operation=QComboBox()
        for label,value in self.OPERATIONS:self.operation.addItem(label,value)
        self.source=PathField(filter=VECTOR_FILTER);self.secondary=PathField(filter=VECTOR_FILTER)
        self.crs=QLineEdit();self.crs.setPlaceholderText('Exemple : EPSG:32733');self.distance=real(100)
        self.maximum=real(0);self.maximum.setMinimum(0);self.maximum.setSpecialValueText('Sans limite')
        self.field=QLineEdit();self.field.setPlaceholderText('Vide : dissolution de toutes les entités')
        self.predicate=QComboBox();self.predicate.addItems(['intersects','within','contains','touches','overlaps'])
        self.join=QComboBox();self.join.addItem('Conserver les correspondances','inner');self.join.addItem('Conserver toutes les entités de gauche','left')
        self.unit=QComboBox();self.unit.addItems(['ha','m2','km2'])
        for label,widget in [('Opération',self.operation),('Couche source',self.source),('Couche de superposition',self.secondary),
            ('Système de coordonnées projeté',self.crs),('Distance (m)',self.distance),('Champ de dissolution',self.field),
            ('Distance maximale (m)',self.maximum),('Relation spatiale',self.predicate),('Type de jointure',self.join),('Unité',self.unit)]:self.form.addRow(label,widget)
        self.output.filter='GeoPackage (*.gpkg);;GeoJSON (*.geojson)';self.finish()
        self.operation.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        op=self.operation.currentData()
        show={self.secondary:op in {'clip','intersection','union','difference','symmetric_difference','sjoin','nearest'},
            self.crs:op in {'buffer','reproject','area','length','nearest'},self.distance:op=='buffer',self.field:op=='dissolve',self.maximum:op=='nearest',
            self.predicate:op=='sjoin',self.join:op in {'sjoin','nearest'},self.unit:op in {'area','length'}}
        for widget,visible in show.items():widget.setVisible(visible);self.form.labelForField(widget).setVisible(visible)
        self.unit.clear();self.unit.addItems(['m','km'] if op=='length' else ['ha','m2','km2'])
    def job(self,options):
        op=self.operation.currentData();source=self.source.text();other=self.secondary.text();crs=self.crs.text().strip() or None
        distance=self.distance.value();field=self.field.text().strip() or None;unit=self.unit.currentText()
        predicate=self.predicate.currentText();how=self.join.currentData();destination=self.destination()
        needs_other=op in {'clip','intersection','union','difference','symmetric_difference','sjoin','nearest'}
        maximum=self.maximum.value() or None
        if not source or (needs_other and not other):raise ValueError('Renseigner les couches nécessaires au traitement.')
        if op=='reproject' and not crs:raise ValueError('Renseigner le système de coordonnées cible.')
        def run(progress,cancel):
            if op=='clip':result=cm.clip(source,other)
            elif op=='buffer':result=cm.buffer(source,distance,metric_crs=crs)
            elif op in {'intersection','union','difference','symmetric_difference'}:result=cm.overlay(source,other,how=op)
            elif op=='sjoin':result=cm.sjoin(source,other,how=how,predicate=predicate)
            elif op=='nearest':result=cm.nearest(source,other,metric_crs=crs,max_distance=maximum,how=how)
            elif op=='dissolve':result=cm.dissolve(source,by=field)
            elif op=='reproject':result=cm.reproject(source,crs)
            elif op=='make_valid':result=cm.make_valid(source)
            else:
                result=cm.read_file(source);values=cm.area(result,unit,metric_crs=crs) if op=='area' else cm.length(result,unit,metric_crs=crs)
                if values.name in result.columns:raise ValueError(f'Le champ {values.name} existe déjà.')
                result[values.name]=values
            sources=(source,other) if needs_other else (source,)
            return write_result(result,destination,sources=sources,overwrite=options['overwrite'])
        return run


class RasterToolsPage(Page):
    engine=False
    cancellable=False
    def __init__(self):
        super().__init__('Traitements raster','Découpage, reprojection, reclassification, statistiques zonales, surfaces et transitions.')
        self.operation=QComboBox()
        for label,value in [('Extraction par masque','clip'),('Reprojection','reproject'),('Reclassification','reclassify'),
            ('Statistiques zonales','zonal_stats'),('Superficies par classe','class_areas'),('Matrice de transition','change_matrix')]:self.operation.addItem(label,value)
        self.source=PathField();self.secondary=PathField(filter=VECTOR_FILTER);self.band=spin()
        self.crs=QLineEdit();self.crs.setPlaceholderText('Exemple : EPSG:32733');self.resolution=real(0);self.resolution.setMinimum(0);self.resolution.setSpecialValueText('Automatique')
        self.resampling=QComboBox()
        for label,value in [('Plus proche voisin','nearest'),('Bilinéaire','bilinear'),('Cubique','cubic')]:self.resampling.addItem(label,value)
        self.mapping=QPlainTextEdit();self.mapping.setPlaceholderText('Valeur initiale = nouvelle valeur\n1 = 1\n2 = 0\n3 = 0');self.mapping.setMaximumHeight(140)
        self.unmatched=QComboBox();self.unmatched.addItem('Affecter NoData','nodata');self.unmatched.addItem('Conserver la valeur','keep')
        self.unit=QComboBox();self.unit.addItems(['ha','m2','km2'])
        for label,widget in [('Opération',self.operation),('Raster source',self.source),('Bande',self.band),('Masque ou raster de comparaison',self.secondary),
            ('Système de coordonnées cible',self.crs),('Résolution (unités du système cible)',self.resolution),('Rééchantillonnage',self.resampling),
            ('Correspondance des classes',self.mapping),('Valeurs sans correspondance',self.unmatched),('Unité de superficie',self.unit)]:self.form.addRow(label,widget)
        self.finish();self.operation.currentIndexChanged.connect(self.changed);self.changed()
    def changed(self):
        op=self.operation.currentData()
        show={self.secondary:op in {'clip','zonal_stats','change_matrix'},self.crs:op=='reproject',self.resolution:op=='reproject',
            self.resampling:op=='reproject',self.mapping:op=='reclassify',self.unmatched:op=='reclassify',self.unit:op=='class_areas'}
        for widget,visible in show.items():widget.setVisible(visible);self.form.labelForField(widget).setVisible(visible)
        self.secondary.filter=RASTER_FILTER if op=='change_matrix' else VECTOR_FILTER
        self.output.filter='Tableau CSV (*.csv)' if op in {'class_areas','change_matrix'} else 'GeoPackage (*.gpkg);;GeoJSON (*.geojson)' if op=='zonal_stats' else 'GeoTIFF (*.tif)'
        suffix='.csv' if op in {'class_areas','change_matrix'} else '.gpkg' if op=='zonal_stats' else '.tif'
        if self.output.text():self.output.edit.setText(str(Path(self.output.text()).with_suffix(suffix)))
    def job(self,options):
        op=self.operation.currentData();source=self.source.text();other=self.secondary.text();band=self.band.value();destination=self.destination()
        crs=self.crs.text().strip();resolution=self.resolution.value() or None;resampling=self.resampling.currentData();unit=self.unit.currentText();unmatched=self.unmatched.currentData()
        mapping={}
        if op=='reclassify':
            for line in self.mapping.toPlainText().splitlines():
                if not line.strip():continue
                try:key,value=[float(v.strip()) for v in line.split('=')]
                except ValueError:raise ValueError('Reclassification : une ligne par correspondance, sous la forme 1 = 0.') from None
                if key in mapping:raise ValueError('Une valeur initiale ne peut avoir deux correspondances.')
                mapping[key]=value
        if op=='reproject' and not crs:raise ValueError('Renseigner le système de coordonnées cible.')
        sources=(source,other) if op in {'clip','zonal_stats','change_matrix'} else (source,)
        # Check all inputs, including the vector mask, before invoking any writer.
        output_path(destination,options['overwrite'],sources)
        def run(progress,cancel):
            kwargs=dict(band=band,overwrite=options['overwrite'])
            if op=='clip':return cm.raster.clip(source,other,destination,**kwargs)
            if op=='reproject':return cm.raster.reproject(source,destination,crs,resolution=resolution,resampling=resampling,**kwargs)
            if op=='reclassify':return cm.raster.reclassify(source,destination,mapping,unmatched=unmatched,**kwargs)
            if op=='zonal_stats':result=cm.raster.zonal_stats(source,other,band=band)
            elif op=='class_areas':result=cm.raster.class_areas(source,band=band,unit=unit)
            else:result=cm.raster.change_matrix(source,other,band=band)
            return write_result(result,destination,sources=sources,overwrite=options['overwrite'])
        return run
