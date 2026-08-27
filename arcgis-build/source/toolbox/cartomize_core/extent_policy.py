"""Politique d’emprise partagée par automatisation et mise en page."""


def margin_factor(percent: float, *, locator: bool = False) -> float:
    value = 1.0 + max(0.0, min(50.0, float(percent or 0.0))) / 100.0
    return max(3.0, value) if locator else value
