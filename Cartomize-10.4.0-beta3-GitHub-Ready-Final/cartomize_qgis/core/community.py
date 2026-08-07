"""Ouverture du service communautaire configuré par l'utilisateur."""
from __future__ import annotations

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from .errors import CartomizeError
from .settings import CartomizeSettings, validate_community_url


class CommunityClient:
    def open_in_browser(self, value: str | None = None) -> None:
        settings = CartomizeSettings.load()
        target = validate_community_url(
            value if value is not None else settings.community_url
        )
        if not target:
            raise CartomizeError(
                "L'adresse HTTPS de la communauté n'est pas configurée."
            )
        if not QDesktopServices.openUrl(QUrl(target)):
            raise CartomizeError(
                "Le navigateur n'a pas pu ouvrir la communauté Cartomize."
            )
