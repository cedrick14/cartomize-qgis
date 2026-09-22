"""Qt controls for page templates, map frames and cartographic elements."""
import pandas as pd
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QTabWidget)
import cartomize as cm


class LayoutDiagram(QWidget):
    """Monochrome structural preview; geographic rendering is a separate action."""
    def __init__(self):
        super().__init__();self.plan=None;self.page_size=(297,210)
        self.setMinimumHeight(170)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width,height=self.page_size;scale=min((self.width()-24)/width,(self.height()-24)/height)
        x=(self.width()-width*scale)/2;y=(self.height()-height*scale)/2
        painter.translate(x,y);painter.scale(scale,scale)
        painter.setPen(QPen(QColor('#555555'),.5));painter.setBrush(QColor('white'));painter.drawRect(QRectF(0,0,width,height))
        if self.plan:
            labels={'map_frame':'Carte','legend':'Légende','title':'Titre','subtitle':'Sous-titre','scale_bar':'Échelle','north_arrow':'Nord','table':'Tableau','chart':'Graphique','text':'Texte'}
            for item in self.plan.items:
                if item.kind=='shape':continue
                rect=QRectF(item.x_mm,item.y_mm,item.width_mm,item.height_mm)
                painter.setBrush(QColor('#eeeeee') if item.kind=='map_frame' else QColor('#ffffff'))
                painter.drawRect(rect)
                if item.height_mm>4:
                    font=painter.font();font.setPointSizeF(3.2);painter.setFont(font)
                    painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,labels.get(item.kind,item.kind))
        else:
            painter.setBrush(QColor('#eeeeee'));painter.drawRect(QRectF(16,38,width-86 if width>height else width-28,height-55 if width>height else height-99))
        painter.end()


class LayoutSettings(QWidget):
    def __init__(self,*,compact=False):
        super().__init__();outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.template=QComboBox();self.template.addItem('Mise en page standard',None)
        for item in cm.list_templates():self.template.addItem(item['name'],item['id'])
        self.format=QComboBox();self.format.addItems(['A4','A3'])
        self.orientation=QComboBox();self.orientation.addItem('Paysage','landscape');self.orientation.addItem('Portrait','portrait')
        self.legend=QCheckBox('Légende');self.scale=QCheckBox('Échelle graphique');self.north=QCheckBox('Orientation')
        toggles=QWidget();row=QHBoxLayout(toggles);row.setContentsMargins(0,0,0,0)
        for box in (self.legend,self.scale,self.north):box.setChecked(True);row.addWidget(box)
        row.addStretch()
        self.form=QFormLayout();self.form.addRow('Maquette',self.template)
        page=QWidget();row=QHBoxLayout(page);row.setContentsMargins(0,0,0,0);row.addWidget(self.format);row.addWidget(self.orientation)
        self.form.addRow('Format et orientation',page);self.form.addRow('Éléments cartographiques',toggles)
        self.summary=QLabel();self.summary.setWordWrap(True);self.form.addRow(self.summary);outer.addLayout(self.form)
        self.diagram=LayoutDiagram();self.diagram.setVisible(not compact);outer.addWidget(self.diagram)
        self.frames=QTableWidget(0,4);self.frames.setHorizontalHeaderLabels(['Cadre','Emprise : xmin, ymin, xmax, ymax','Système de coordonnées','Couches (noms séparés par ;)'])
        self.frames.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.frames.setMinimumHeight(150)
        self.elements=QTableWidget(0,5);self.elements.setHorizontalHeaderLabels(['Élément','Type','Texte ou fichier CSV','Libellés (graphique)','Valeurs (graphique)'])
        self.elements.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.elements.setColumnWidth(0,110);self.elements.setColumnWidth(1,80);self.elements.setColumnWidth(3,130);self.elements.setColumnWidth(4,130)
        self.elements.setMinimumHeight(150)
        self.template.currentIndexChanged.connect(self.refresh)
        self.format.currentIndexChanged.connect(self.refresh);self.orientation.currentIndexChanged.connect(self.refresh)
        self.refresh()
    def refresh(self):
        template=self.template.currentData();plan=cm.layout_plan(template) if template else None
        self.format.setEnabled(plan is None);self.orientation.setEnabled(plan is None)
        if plan:
            size=(plan.page_width_mm,plan.page_height_mm);ids=[x.item_id for x in plan.map_items]
            self.format.blockSignals(True);self.orientation.blockSignals(True)
            self.format.setCurrentText('A3' if max(size)>350 else 'A4')
            self.orientation.setCurrentIndex(0 if size[0]>size[1] else 1)
            self.format.blockSignals(False);self.orientation.blockSignals(False)
        else:
            size=(210,297) if self.format.currentText()=='A4' else (297,420)
            if self.orientation.currentData()=='landscape':size=size[::-1]
            ids=['main']
        self.summary.setText(f'{len(cm.list_templates())} maquettes disponibles · {size[0]:g} × {size[1]:g} mm · {len(ids)} cadre(s) cartographique(s)')
        self.diagram.plan=plan;self.diagram.page_size=size;self.diagram.update()
        self.frames.setRowCount(len(ids))
        for row,ident in enumerate(ids):
            for col,value in enumerate([ident,'','','']):
                item=QTableWidgetItem(value)
                if col==0:item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                self.frames.setItem(row,col,item)
        items=[(i.item_id,i.kind) for i in plan.items if i.kind in {'text','table','chart'}] if plan else []
        self.elements.setRowCount(len(items))
        for row,(ident,kind) in enumerate(items):
            for col,value in enumerate([ident,kind,'','','']):
                item=QTableWidgetItem(value)
                if col<2:item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                self.elements.setItem(row,col,item)
    def capture(self):
        frames=[]
        for row in range(self.frames.rowCount()):
            ident,bounds,crs,layers=[self.frames.item(row,col).text().strip() for col in range(4)]
            if not any((bounds,crs,layers)):continue
            extent=None
            if bounds:
                try:extent=tuple(float(v.strip()) for v in bounds.split(','))
                except ValueError:raise ValueError('Emprise : renseigner quatre nombres séparés par des virgules.') from None
                from .mapping import _extent
                extent=_extent(extent)
            frames.append(dict(frame_id=ident,extent=extent,crs=crs or None,layers=[v.strip() for v in layers.split(';') if v.strip()] or None))
        elements=[]
        for row in range(self.elements.rowCount()):
            ident,kind,content,labels,values=[self.elements.item(row,col).text().strip() for col in range(5)]
            if content:elements.append(dict(id=ident,kind=kind,content=content,labels=labels,values=values))
        return dict(template=self.template.currentData(),format=self.format.currentText(),orientation=self.orientation.currentData(),
            legend=self.legend.isChecked(),scale=self.scale.isChecked(),north=self.north.isChecked(),frames=frames,elements=elements)


def apply_layout(map_object,settings):
    map_object.add_legend(settings['legend']).add_scale_bar(settings['scale']).add_north_arrow(settings['north'])
    for frame in settings.get('frames',[]):map_object.set_frame(**frame)
    for item in settings.get('elements',[]):
        if item['kind']=='text':map_object.set_text(item['id'],item['content'])
        else:
            data=pd.read_csv(item['content'])
            if item['kind']=='table':map_object.set_table(item['id'],data)
            else:
                if not item['labels'] or not item['values']:raise ValueError('Renseigner les colonnes du graphique.')
                map_object.set_chart(item['id'],data[item['labels']],pd.to_numeric(data[item['values']],errors='raise'),color='#444444')
    return map_object
