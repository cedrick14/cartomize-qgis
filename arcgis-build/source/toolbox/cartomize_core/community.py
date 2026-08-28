"""Accès explicite au portail communautaire Cartomize."""

import json
import webbrowser
from urllib.request import Request, urlopen

from .constants import DEFAULT_COMMUNITY_URL
from .errors import CartomizeError
from .settings import CartomizeSettings, validate_community_url


def fetch_resources(url: str, timeout: float = 12.0) -> list[dict]:
    request = Request(url, headers={"User-Agent": "Cartomize-ArcGISPro/10.5.1"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("results", payload if isinstance(payload, list) else []))


class CommunityClient:
    def __init__(self, settings: CartomizeSettings | None = None):
        self.settings = settings or CartomizeSettings.load()

    def open_in_browser(self, value: str | None = None) -> None:
        try:
            url = validate_community_url(
                value if value is not None else self.settings.community_url or DEFAULT_COMMUNITY_URL
            )
        except ValueError as exc:
            raise CartomizeError(str(exc)) from exc
        if not url:
            raise CartomizeError("Le portail Cartomize n'est pas configuré.")
        if not webbrowser.open(url, new=2):
            raise CartomizeError("Le navigateur n'a pas pu ouvrir la communauté Cartomize.")
