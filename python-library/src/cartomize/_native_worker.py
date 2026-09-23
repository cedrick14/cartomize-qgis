"""Standalone JSON bridge. Runs under the vendor's Python, not Cartomize's."""
import json
import sys
from pathlib import Path


def choose(items,name,kind):
    matching=[x for x in items if name is None or x.name==name] if kind=='arcgis' else [x for x in items if name is None or x.name()==name]
    if len(matching)!=1:raise ValueError('Choisir une mise en page unique parmi celles du projet.')
    return matching[0]


def arcgis(request):
    import arcpy
    project=arcpy.mp.ArcGISProject(request['project'])
    if request.get('template'):project.importDocument(request['template'])
    layers=[]
    for mapping in project.listMaps():
        for layer in mapping.listLayers():
            layers.append(dict(id=layer.URI,name=layer.name,map=mapping.name,source=layer.dataSource if layer.supports('DATASOURCE') else None,visible=layer.visible,broken=layer.isBroken,kind='raster' if layer.isRasterLayer else 'vector' if layer.isFeatureLayer else 'group'))
    layouts=project.listLayouts()
    if request['action']=='inspect':return dict(schema='cartomize.native.inventory.v1',engine='arcgis',layers=layers,layouts=[dict(name=x.name,width=x.pageWidth,height=x.pageHeight,units=x.pageUnits) for x in layouts])
    if request['action']=='export' or request['texts'] or request['extents']:
        layout=choose(layouts,request['layout'],'arcgis')
        for name,text in request['texts'].items():
            found=[x for x in layout.listElements('TEXT_ELEMENT') if x.name==name]
            if len(found)!=1:raise ValueError('Élément texte introuvable ou ambigu : '+name)
            found[0].text=text
        for name,bounds in request['extents'].items():
            found=[x for x in layout.listElements('MAPFRAME_ELEMENT') if x.name==name]
            if len(found)!=1:raise ValueError('Cadre cartographique introuvable ou ambigu : '+name)
            found[0].camera.setExtent(arcpy.Extent(*bounds))
    destination=request['destination']
    if request['action']=='copy':project.saveACopy(destination)
    else:
        suffix=Path(destination).suffix.lower()
        if suffix=='.pagx':layout.exportToPAGX(destination)
        else:getattr(layout,{'.pdf':'exportToPDF','.png':'exportToPNG','.svg':'exportToSVG'}[suffix])(destination,resolution=request['dpi'])
    return dict(engine='arcgis',output=destination)


def qgis(request):
    from qgis.core import QgsApplication,QgsProject,QgsLayoutExporter,QgsLayoutItemLabel,QgsLayoutItemMap,QgsRectangle,QgsReadWriteContext
    from qgis.PyQt.QtXml import QDomDocument
    if request.get('prefix'):QgsApplication.setPrefixPath(request['prefix'],True)
    app=QgsApplication([],False);app.initQgis()
    try:
        project=QgsProject.instance()
        if not project.read(request['project']):raise ValueError('Le moteur QGIS ne peut pas ouvrir le projet.')
        # Save copies with absolute references so moving the project does not break its sources.
        from qgis.core import Qgis
        project.setFilePathStorage(Qgis.FilePathType.Absolute)
        if request.get('template'):
            from qgis.core import QgsPrintLayout
            document=QDomDocument();loaded=document.setContent(Path(request['template']).read_text(encoding='utf-8'))
            if isinstance(loaded,tuple) and not loaded[0]:raise ValueError('Maquette QPT invalide.')
            layout=QgsPrintLayout(project);layout.initializeDefaults();layout.loadFromTemplate(document,QgsReadWriteContext())
            project.layoutManager().addLayout(layout)
        layouts=project.layoutManager().printLayouts()
        if request['action']=='inspect':
            layers=[];ordered=project.layerTreeRoot().layerOrder()
            for i,x in enumerate(ordered):
                document=QDomDocument('qgis');node=document.createElement('maplayer');document.appendChild(node)
                x.writeLayerXml(node,document,QgsReadWriteContext())
                layers.append(dict(id=x.id(),name=x.name(),source=x.source(),provider=x.providerType(),visible=project.layerTreeRoot().findLayer(x.id()).isVisible() if project.layerTreeRoot().findLayer(x.id()) else True,broken=not x.isValid(),kind='vector' if int(x.type())==0 else 'raster',style_xml=document.toString(),zorder=len(ordered)-i))
            return dict(schema='cartomize.native.inventory.v1',engine='qgis',runtime_version=Qgis.QGIS_VERSION,layers=layers,layouts=[dict(name=x.name()) for x in layouts])
        if request['action']=='export' or request['texts'] or request['extents']:
            layout=choose(layouts,request['layout'],'qgis')
            for name,text in request['texts'].items():
                item=layout.itemById(name)
                if not isinstance(item,QgsLayoutItemLabel):raise ValueError('Élément texte introuvable : '+name)
                item.setText(text)
            for name,bounds in request['extents'].items():
                item=layout.itemById(name)
                if not isinstance(item,QgsLayoutItemMap):raise ValueError('Cadre cartographique introuvable : '+name)
                item.zoomToExtent(QgsRectangle(*bounds))
        destination=request['destination']
        if request['action']=='copy':
            if not project.write(destination):raise RuntimeError('Enregistrement QGIS impossible.')
        else:
            suffix=Path(destination).suffix.lower();exporter=QgsLayoutExporter(layout)
            if suffix=='.qpt':
                if not layout.saveAsTemplate(destination,QgsReadWriteContext()):raise RuntimeError('Enregistrement QPT impossible.')
            else:
                cls,method={'.pdf':('PdfExportSettings','exportToPdf'),'.png':('ImageExportSettings','exportToImage'),'.svg':('SvgExportSettings','exportToSvg')}[suffix]
                settings=getattr(QgsLayoutExporter,cls)();settings.dpi=request['dpi']
                if getattr(exporter,method)(destination,settings)!=QgsLayoutExporter.Success:raise RuntimeError('Export QGIS impossible.')
        return dict(engine='qgis',output=destination)
    finally:
        QgsProject.instance().clear()
        app.exitQgis()


if __name__=='__main__':
    try:
        request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result=arcgis(request) if request['engine']=='arcgis' else qgis(request)
        response=dict(ok=True,result=result)
    except Exception as exc:response=dict(ok=False,error=type(exc).__name__+': '+str(exc))
    Path(sys.argv[2]).write_text(json.dumps(response,ensure_ascii=False),encoding='utf-8')
    raise SystemExit(0 if response['ok'] else 1)
