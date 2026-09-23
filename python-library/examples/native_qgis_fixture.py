"""Create a synthetic QGIS project using QGIS's own Python interpreter."""
import json,sys
from pathlib import Path
from qgis.core import (QgsApplication,QgsProject,QgsVectorLayer,QgsPrintLayout,
    QgsLayoutItemMap,QgsLayoutItemLabel,QgsLayoutSize,QgsLayoutPoint,QgsRectangle,
    QgsGraduatedSymbolRenderer,QgsRendererRange,QgsFillSymbol)


def main(destination):
    app=QgsApplication([],False);app.initQgis()
    try:
        root=Path(destination);root.mkdir(parents=True,exist_ok=True)
        features=[]
        for i in range(2):
            x=13+i*.5
            features.append(dict(type='Feature',properties={'population':50+i*100},geometry=dict(type='Polygon',coordinates=[[[x,-4],[x+.4,-4],[x+.4,-3.6],[x,-3.6],[x,-4]]])))
        data=root/'zones.geojson';data.write_text(json.dumps(dict(type='FeatureCollection',features=features)))
        layer=QgsVectorLayer(str(data),'Zones','ogr');assert layer.isValid()
        ranges=[QgsRendererRange(0,100,QgsFillSymbol.createSimple({'color':'0,100,0,255'}),'Faible'),QgsRendererRange(100,200,QgsFillSymbol.createSimple({'color':'230,180,50,255'}),'Élevée')]
        layer.setRenderer(QgsGraduatedSymbolRenderer('population',ranges))
        project=QgsProject.instance();project.addMapLayer(layer)
        layout=QgsPrintLayout(project);layout.initializeDefaults();layout.setName('Validation')
        frame=QgsLayoutItemMap(layout);frame.setId('carte');layout.addLayoutItem(frame);frame.attemptMove(QgsLayoutPoint(10,30));frame.attemptResize(QgsLayoutSize(180,130));frame.setLayers([layer]);frame.zoomToExtent(QgsRectangle(12.9,-4.1,14,-3.5))
        label=QgsLayoutItemLabel(layout);label.setId('titre');label.setText('Validation QGIS');layout.addLayoutItem(label);label.attemptMove(QgsLayoutPoint(10,10));label.adjustSizeToText()
        project.layoutManager().addLayout(layout)
        assert project.write(str(root/'project.qgz'))
    finally:
        QgsProject.instance().clear()
        app.exitQgis()


if __name__=='__main__':main(sys.argv[1])
