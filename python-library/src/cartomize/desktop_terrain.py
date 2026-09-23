"""Block-based terrain and convolution controls."""
import json
from PySide6.QtWidgets import QComboBox,QPlainTextEdit
from .desktop import Page,PathField,spin,real


class TerrainPage(Page):
    def __init__(self):
        super().__init__('Analyse de terrain et convolution','Dérivées du MNT selon Horn, indices topographiques et filtrage par noyau ; calcul par blocs avec marges de voisinage.')
        self.source=PathField();self.band=spin();self.operation=QComboBox()
        for label,value in [('Pente, exposition et ombrage','terrain'),('Indice de position topographique','tpi'),('Indice de rugosité topographique','tri'),('Rugosité altimétrique','roughness'),('Convolution','convolve')]:self.operation.addItem(label,value)
        self.z_factor=real(1);self.azimuth=real(315);self.altitude=real(45);self.kernel=QPlainTextEdit('[[0, -1, 0], [-1, 5, -1], [0, -1, 0]]');self.kernel.setMaximumHeight(100)
        for label,widget in [('Raster',self.source),('Bande',self.band),('Opération',self.operation),('Conversion verticale vers le mètre',self.z_factor),('Azimut solaire (°)',self.azimuth),('Hauteur solaire (°)',self.altitude),('Matrice de convolution (JSON)',self.kernel)]:self.form.addRow(label,widget)
        self.finish()
    def job(self,options):
        from .terrain import terrain,convolve
        source=self.source.text();destination=self.destination();operation=self.operation.currentData();band=self.band.value()
        if operation=='convolve':
            kernel=json.loads(self.kernel.toPlainText());return lambda progress,cancel:convolve(source,destination,kernel,band=band,progress=progress,cancel=cancel,**options)
        parameters=dict(products=['slope','aspect','hillshade'] if operation=='terrain' else [operation],band=band,z_factor=self.z_factor.value(),azimuth=self.azimuth.value(),altitude=self.altitude.value())
        return lambda progress,cancel:terrain(source,destination,progress=progress,cancel=cancel,**parameters,**options)
