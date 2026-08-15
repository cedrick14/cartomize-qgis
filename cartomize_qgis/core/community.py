"""Ouverture sécurisée du portail officiel Cartomize."""
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
            raise CartomizeError("Le portail officiel Cartomize est indisponible.")
        if not QDesktopServices.openUrl(QUrl(target)):
            raise CartomizeError(
                "Le navigateur n'a pas pu ouvrir la communauté Cartomize."
            )
