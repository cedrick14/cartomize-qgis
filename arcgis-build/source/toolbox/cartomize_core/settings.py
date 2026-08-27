"""Paramètres persistants de Cartomize 10.5.1."""

from dataclasses import asdict, dataclass


@dataclass
class CartomizeSettings:
    visible_only: bool = True
    margin_percent: float = 3.0
    dpi: int = 600
    remove_basemap_from_legend: bool = True

    def to_dict(self):
        return asdict(self)
