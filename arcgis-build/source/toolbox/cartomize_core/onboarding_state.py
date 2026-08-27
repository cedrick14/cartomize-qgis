"""État d’accueil partagé avec la version QGIS."""

from dataclasses import dataclass


@dataclass
class OnboardingState:
    completed: bool = False
    selected_tab: str = "Automatisation"
    last_template_id: str = ""
