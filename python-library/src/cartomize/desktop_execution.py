"""Execution choices shared by independent tools and cartographic plans."""
from PySide6.QtWidgets import QWidget,QFormLayout,QComboBox,QLineEdit,QLabel,QPushButton


class ExecutionSettings(QWidget):
    def __init__(self):
        super().__init__();form=QFormLayout(self);form.setContentsMargins(0,0,0,0)
        self.execution=QComboBox();self.execution.addItem('Threads locaux','threads');self.execution.addItem('Processus distribués Dask','distributed')
        self.device=QComboBox();self.device.addItem('CPU','cpu');self.device.addItem('GPU NVIDIA · CUDA','cuda')
        self.scheduler=QLineEdit();self.scheduler.setPlaceholderText('Vide : processus locaux ; sinon adresse du cluster de confiance')
        self.report=QLabel();self.report.setWordWrap(True);button=QPushButton('Vérifier les moteurs de calcul');button.clicked.connect(self.diagnose)
        form.addRow('Exécution',self.execution);form.addRow('Algèbre, indices et agrégations',self.device);form.addRow('Ordonnanceur Dask',self.scheduler);form.addRow(button);form.addRow(self.report)
        self.execution.currentIndexChanged.connect(lambda:self.scheduler.setEnabled(self.execution.currentData()=='distributed'))
        self.scheduler.setEnabled(False)
    def parameters(self,*,gpu=True):
        result=dict(execution=self.execution.currentData(),scheduler_address=self.scheduler.text().strip() or None if self.execution.currentData()=='distributed' else None)
        if gpu:result['device']=self.device.currentData()
        return result
    def diagnose(self):
        from .execution import execution_capabilities
        report=execution_capabilities();self.report.setText('Dask : '+('disponible' if report['distributed']['available'] else 'dépendance à installer')+'\nCUDA : '+(report['cuda'].get('name') or report['cuda'].get('reason','indisponible')))
