"""Catalogue web facultatif, avec repli intégral sur un cache local.

Ce module n'envoie aucune donnée du projet QGIS et ne conserve aucun secret.
Le catalogue embarqué reste la source de travail lorsque le réseau ou le site
Cartomize ne répond pas.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.client import HTTPSConnection
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import tempfile
from typing import Callable
from urllib.parse import urlencode, urljoin, urlparse

from .constants import (
    COMMUNITY_CATALOG_CACHE_MAX_BYTES,
    COMMUNITY_CATALOG_MAX_ITEMS,
    COMMUNITY_CATALOG_MAX_PAGES,
    COMMUNITY_CATALOG_TIMEOUT_SECONDS,
    PLUGIN_VERSION,
)


@dataclass(frozen=True)
class CommunityResource:
    resource_id: int
    title: str
    description: str
    category: str
    page_format: str
    resource_format: str
    qgis_min_version: str
    plugin_min_version: str
    updated_at: str
    detail_url: str


@dataclass(frozen=True)
class CommunityCatalogSnapshot:
    resources: tuple[CommunityResource, ...] = ()
    fetched_at: str = ""
    source: str = "empty"
    warning: str = ""

    @property
    def is_cached(self) -> bool:
        return self.source == "cache"


class CommunityCatalogClient:
    """Lit uniquement des métadonnées publiques et garde le dernier succès."""

    def __init__(
        self,
        base_url: str,
        cache_path: Path,
        *,
        timeout: int = COMMUNITY_CATALOG_TIMEOUT_SECONDS,
        fetcher: Callable[[str, int], bytes] | None = None,
    ):
        self.base_url = _validated_base_url(base_url)
        self.cache_path = Path(cache_path)
        self.timeout = max(2, min(int(timeout), 30))
        self._fetcher = fetcher or self._download

    def load_cached(self) -> CommunityCatalogSnapshot:
        try:
            if (
                not self.cache_path.is_file()
                or self.cache_path.is_symlink()
                or self.cache_path.stat().st_size > COMMUNITY_CATALOG_CACHE_MAX_BYTES
            ):
                return CommunityCatalogSnapshot()
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            resources = self._normalise_resources(payload.get("resources"), from_cache=True)
            return CommunityCatalogSnapshot(
                resources=resources,
                fetched_at=_text(payload.get("fetched_at"), 40),
                source="cache" if resources else "empty",
            )
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            return CommunityCatalogSnapshot()

    def refresh(self) -> CommunityCatalogSnapshot:
        """Actualise le cache; toute erreur rend le dernier cache exploitable."""

        if not self.base_url:
            return self._fallback("Le portail Cartomize est indisponible.")
        query = urlencode({"type": "layout", "ordering": "recent"})
        url = urljoin(f"{self.base_url}/", f"api/templates/?{query}")
        collected: list[dict] = []
        try:
            for _page in range(COMMUNITY_CATALOG_MAX_PAGES):
                self._assert_same_origin(url)
                raw = self._fetcher(url, self.timeout)
                if len(raw) > COMMUNITY_CATALOG_CACHE_MAX_BYTES:
                    raise ValueError("Réponse du catalogue trop volumineuse")
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, list):
                    page_items, next_url = payload, ""
                elif isinstance(payload, dict):
                    page_items, next_url = payload.get("results"), payload.get("next") or ""
                else:
                    raise ValueError("Réponse du catalogue invalide")
                if not isinstance(page_items, list):
                    raise ValueError("Liste de ressources invalide")
                collected.extend(item for item in page_items if isinstance(item, dict))
                if len(collected) >= COMMUNITY_CATALOG_MAX_ITEMS or not next_url:
                    break
                url = str(next_url)
            resources = self._normalise_resources(collected[:COMMUNITY_CATALOG_MAX_ITEMS])
            fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            snapshot = CommunityCatalogSnapshot(resources, fetched_at, "network", "")
            self._write_cache(snapshot)
            return snapshot
        except Exception as exc:
            return self._fallback(f"Portail indisponible : {str(exc).strip()[:180]}")

    def _fallback(self, warning: str) -> CommunityCatalogSnapshot:
        cached = self.load_cached()
        return CommunityCatalogSnapshot(
            resources=cached.resources,
            fetched_at=cached.fetched_at,
            source="cache" if cached.resources else "empty",
            warning=warning,
        )

    def _normalise_resources(self, values, *, from_cache: bool = False) -> tuple[CommunityResource, ...]:
        if not isinstance(values, list):
            return ()
        clean: list[CommunityResource] = []
        seen: set[int] = set()
        for value in values[:COMMUNITY_CATALOG_MAX_ITEMS]:
            if not isinstance(value, dict):
                continue
            try:
                resource_id = int(value.get("resource_id") if from_cache else value.get("id"))
            except (TypeError, ValueError):
                continue
            if resource_id <= 0 or resource_id in seen:
                continue
            if not from_cache and value.get("asset_type") not in (None, "layout"):
                continue
            title = _text(value.get("title"), 160)
            if not title:
                continue
            seen.add(resource_id)
            clean.append(
                CommunityResource(
                    resource_id=resource_id,
                    title=title,
                    description=_text(value.get("description"), 800),
                    category=_text(value.get("category"), 64),
                    page_format=_text(value.get("page_format"), 40),
                    resource_format=_text(value.get("resource_format"), 32),
                    qgis_min_version=_text(value.get("qgis_min_version"), 24),
                    plugin_min_version=_text(value.get("plugin_min_version"), 24),
                    updated_at=_text(value.get("updated_at"), 40),
                    detail_url=f"{self.base_url}/galerie/{resource_id}/",
                )
            )
        return tuple(clean)

    def _write_cache(self, snapshot: CommunityCatalogSnapshot) -> None:
        payload = {
            "schema_version": 1,
            "fetched_at": snapshot.fetched_at,
            "resources": [asdict(item) for item in snapshot.resources],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > COMMUNITY_CATALOG_CACHE_MAX_BYTES:
            raise ValueError("Cache du catalogue trop volumineux")
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=self.cache_path.parent, prefix="catalog-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
        temporary.replace(self.cache_path)

    def _assert_same_origin(self, url: str) -> None:
        base = urlparse(self.base_url)
        target = urlparse(url)
        if target.scheme != "https" or target.hostname != base.hostname or target.port != base.port:
            raise ValueError("Pagination externe refusée")

    @staticmethod
    def _download(url: str, timeout: int) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Seules les adresses HTTPS sont autorisées")
        _require_public_host(parsed.hostname, parsed.port or 443)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        connection = HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "application/json",
                    "User-Agent": f"Cartomize-QGIS/{PLUGIN_VERSION}",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f"Réponse HTTP inattendue : {response.status}")
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "json" not in content_type:
                raise ValueError("Le serveur n'a pas renvoyé de JSON")
            return response.read(COMMUNITY_CATALOG_CACHE_MAX_BYTES + 1)
        finally:
            connection.close()


def _text(value, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _require_public_host(hostname: str, port: int) -> None:
    """Refuse les destinations locales avant toute connexion réseau."""

    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise ValueError("Le nom du portail ne peut pas être résolu") from exc
    if not addresses:
        raise ValueError("Le portail ne possède aucune adresse réseau")
    for _family, _kind, _protocol, _canonical, socket_address in addresses:
        address = ipaddress.ip_address(socket_address[0])
        if not address.is_global:
            raise ValueError("Une adresse réseau privée ou locale a été refusée")


def _validated_base_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        return ""
    hostname = (parsed.hostname or "").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return ""
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return ""
    except ValueError:
        pass
    return f"https://{parsed.netloc}"
