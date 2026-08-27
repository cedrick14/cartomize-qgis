"""État versionné de la visite guidée Cartomize.

Le module reste indépendant de Qt afin que la décision d'affichage puisse être
testée hors d'une installation QGIS.
"""
from __future__ import annotations

ONBOARDING_VERSION = "1"
COMPLETED_STATUS = "completed"
SKIPPED_STATUS = "skipped"
KNOWN_STATUSES = {COMPLETED_STATUS, SKIPPED_STATUS}


def should_offer_tour(stored_version: object, stored_status: object) -> bool:
    """Indique si la visite doit être proposée automatiquement.

    Une nouvelle version du parcours est reproposée, tandis qu'une visite
    terminée ou volontairement ignorée ne revient pas à chaque ouverture.
    """

    version = str(stored_version or "").strip()
    status = str(stored_status or "").strip().casefold()
    return version != ONBOARDING_VERSION or status not in KNOWN_STATUSES


def normalise_completion_status(status: object) -> str:
    """Valide le statut écrit dans QSettings."""

    value = str(status or "").strip().casefold()
    if value not in KNOWN_STATUSES:
        raise ValueError("Statut de visite guidée invalide.")
    return value
