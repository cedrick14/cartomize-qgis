"""Accès explicite au portail communautaire Cartomize."""

import json
from urllib.request import Request, urlopen


def fetch_resources(url: str, timeout: float = 12.0) -> list[dict]:
    request = Request(url, headers={"User-Agent": "Cartomize-ArcGISPro/10.5.1"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("results", payload if isinstance(payload, list) else []))
