"""Choix d’échelles cartographiques lisibles."""

NICE_SCALES = (500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 2500000, 5000000, 10000000)


def recommended_scale(value: float) -> int:
    target = max(1.0, float(value or 1.0))
    return min(NICE_SCALES, key=lambda item: abs(item - target))
