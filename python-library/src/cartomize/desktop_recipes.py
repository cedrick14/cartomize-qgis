"""Recipe capture and batch execution from the current map."""
import json
from pathlib import Path
from PySide6.QtWidgets import QComboBox,QLineEdit,QPlainTextEdit,QPushButton,QFileDialog,QCheckBox
from .desktop import Page,PathField,spin
from .recipes import safe_name


class RecipesPage(Page):
    engine=False
    staged=True
    def __init__(self,window):
        super().__init__('Recettes et production en série','Réutiliser les couches et la mise en page, appliquer des variables et produire plusieurs cartes.')
        self.window=window;self.mode=QComboBox();self.mode.addItem('Recette cartographique','recipe');self.mode.addItem('Manifeste de production','batch')
        self.source=PathField(filter='Document JSON (*.json)');self.bindings=QPlainTextEdit('{}');self.variables=QPlainTextEdit('{}')
        self.bindings.setMaximumHeight(90);self.variables.setMaximumHeight(90);self.dpi=spin(150,72,600)
        self.reviewed=QCheckBox('Plan de production vérifié');self.output=PathField('directory');self.name=QLineEdit('production-serie')
        for label,widget in [('Document',self.mode),('Fichier',self.source),('Associations de couches (JSON)',self.bindings),('Variables (JSON)',self.variables),('Résolution (ppp)',self.dpi),('Vérification',self.reviewed),('Répertoire parent',self.output),('Nom du résultat',self.name)]:self.form.addRow(label,widget)
        save=QPushButton('Enregistrer la mise en page comme recette');save.clicked.connect(self.save_current);self.form.addRow(save)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.form.addRow(self.report);self.layout.addStretch()
    def save_current(self):
        from .recipes import save_recipe
        from PySide6.QtWidgets import QMessageBox
        path=QFileDialog.getSaveFileName(self,'Enregistrer la recette',filter='Recette Cartomize (*.json)')[0]
        if path:
            try:save_recipe(self.window.tool('mapping').capture_map(),path,overwrite=True);self.source.edit.setText(path)
            except Exception as exc:QMessageBox.warning(self,'Recette',str(exc))
    def job(self,options):
        from .recipes import run_recipe,run_batch
        source=self.source.text();destination=Path(self.destination())/safe_name(self.name.text())
        bindings=json.loads(self.bindings.toPlainText());variables=json.loads(self.variables.toPlainText());dpi=self.dpi.value();reviewed=self.reviewed.isChecked()
        if not isinstance(bindings,dict) or not isinstance(variables,dict):raise ValueError('Saisir des objets JSON pour les associations et les variables.')
        if self.mode.currentData()=='batch':return lambda progress,cancel,stage:run_batch(source,destination,bindings=bindings,reviewed=reviewed,progress=progress,cancel=cancel,stage=stage)
        return lambda progress,cancel,stage:run_recipe(source,destination,bindings=bindings,variables=variables,dpi=dpi,progress=progress,cancel=cancel)
    def show_result(self,path):self.report.setPlainText(Path(path).read_text(encoding='utf-8'))
