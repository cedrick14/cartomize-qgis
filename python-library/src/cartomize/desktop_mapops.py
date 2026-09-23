"""Data fingerprints and cartographic review records."""
from pathlib import Path
import json
from PySide6.QtWidgets import QComboBox,QLineEdit,QPlainTextEdit
from .desktop import Page,PathField


class MapOpsPage(Page):
    engine=False
    def __init__(self,window):
        super().__init__('Révision cartographique','Contrôler la mise en page courante, détecter les changements de données et enregistrer une décision associée à son empreinte.')
        self.window=window;self.operation=QComboBox()
        for label,value in [('Créer un instantané','snapshot'),('Comparer à un instantané','compare'),('Enregistrer une révision','review')]:self.operation.addItem(label,value)
        self.previous=PathField(filter='Instantané (*.json)');self.reviewer=QLineEdit();self.decision=QComboBox()
        for label,value in [('Approuvé','approved'),('Corrections demandées','changes_requested'),('Rejeté','rejected')]:self.decision.addItem(label,value)
        self.comment=QPlainTextEdit();self.comment.setMaximumHeight(80);self.output.filter='Document JSON (*.json)'
        for label,widget in [('Opération',self.operation),('Instantané précédent',self.previous),('Responsable de la révision',self.reviewer),('Décision',self.decision),('Observation',self.comment)]:self.form.addRow(label,widget)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.form.addRow(self.report);self.finish()
    def job(self,options):
        from .mapops import snapshot_project,compare_snapshots,record_review
        from .recipes import map_from_config
        from .storage import save_json
        from .imagery import _check_cancel
        config=self.window.tool('mapping').capture_map();operation=self.operation.currentData();previous=self.previous.text();destination=self.destination()
        reviewer=self.reviewer.text();decision=self.decision.currentData();comment=self.comment.toPlainText();overwrite=options.get('overwrite',False)
        def run(progress,cancel):
            _check_cancel(cancel);snapshot=snapshot_project(config);_check_cancel(cancel)
            if operation=='review':
                quality=map_from_config(config).audit(visual=True)
                return record_review(snapshot,destination,reviewer=reviewer,decision=decision,comment=comment,quality=quality,overwrite=overwrite)
            report=compare_snapshots(previous,snapshot) if operation=='compare' else snapshot
            return save_json(report,destination,overwrite=overwrite,sources=([previous] if previous else [])+[item['path'] for item in snapshot['files']])
        return run
    def show_result(self,path):self.report.setPlainText(Path(path).read_text(encoding='utf-8'))
