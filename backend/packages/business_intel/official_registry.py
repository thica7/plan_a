"""Operator-reviewed exact documents; requests and model output cannot register authority."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

REGISTRY_PATH = Path(__file__).with_name("official_sources.json")


def product_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def document_key(value: str) -> tuple[str, str, int, str, str]:
    url = urlsplit(value)
    host = (url.hostname or "").casefold()
    if (url.scheme != "https" or not host or url.username or url.password or url.fragment
            or url.port not in (None, 443) or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))):
        raise ValueError("official document requires public HTTPS URL without credentials or fragment")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("literal IP cannot establish product authority")
    return url.scheme, host, url.port or 443, url.path or "/", url.query


class ReviewedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1)
    url: str
    dimension: str
    reviewed_by: str = Field(min_length=1)
    reviewed_at: str
    review_basis: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        document_key(value)
        return value

    @field_validator("reviewed_at")
    @classmethod
    def valid_time(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("review time must include UTC timezone")
        return value

    @field_validator("title", "dimension", "reviewed_by", "review_basis")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("blank registry field")
        return value


class RegisteredProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    documents: tuple[ReviewedDocument, ...] = Field(min_length=1)


def _distinct_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_registry(path: Path) -> tuple[RegisteredProduct, ...]:
    return _parse_registry(path.read_bytes())


def _parse_registry(data: bytes) -> tuple[RegisteredProduct, ...]:
    from packages.business_intel.entity_resolver import _IDENTITY_BY_KEY
    rows = json.loads(data, object_pairs_hook=_distinct_object)
    if not isinstance(rows, list):
        raise ValueError("registry must be a list")
    products = tuple(RegisteredProduct.model_validate(row) for row in rows)
    names, urls = set(), set()
    for product in products:
        for name in (product.product, *product.aliases):
            key = product_key(name)
            if key in _IDENTITY_BY_KEY:
                raise ValueError("reviewed product registry collides with built-in identity")
            if not key or key in names:
                raise ValueError("duplicate or empty product identity")
            names.add(key)
        for document in product.documents:
            key = document_key(document.url)
            if key in urls:
                raise ValueError("duplicate official document URL")
            urls.add(key)
    return products


@lru_cache(maxsize=1)
def registry_snapshot() -> tuple[tuple[RegisteredProduct, ...], str]:
    """Freeze the deployment-controlled file for this process; reload on restart."""
    data = REGISTRY_PATH.read_bytes()
    return _parse_registry(data), hashlib.sha256(data).hexdigest()


def registered_product(name: str) -> RegisteredProduct | None:
    key = product_key(name)
    return next((p for p in registry_snapshot()[0]
                 if key in {product_key(n) for n in (p.product, *p.aliases)}), None)


def registered_document(name: str, url: str) -> ReviewedDocument | None:
    product = registered_product(name)
    try:
        key = document_key(url)
    except ValueError:
        return None
    return next((d for d in product.documents if document_key(d.url) == key), None) if product else None
