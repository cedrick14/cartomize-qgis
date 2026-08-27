"""Contrat de planification Automatisation Cartomize 10.5.1."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AutomationPlan:
    objective: str
    template_id: str
    main_layer_name: str
    style_profile: str = "balanced"
    visible_only: bool = True

    def to_dict(self):
        return asdict(self)
