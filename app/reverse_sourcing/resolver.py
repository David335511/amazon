"""ASIN resolution seam for reverse sourcing.

An ``AsinResolver`` turns an Amazon ASIN into a product identity (UPC, title)
so the engine can look the same product up at every supplier. It is pluggable:
a Keepa / Marketplace / product-catalog resolver can be swapped in without
changing the engine. The default passthrough returns the ASIN and any UPC the
caller supplied.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ProductIdentity(BaseModel):
    """Resolved identity for an Amazon ASIN."""

    asin: str
    upc: str | None = None
    title: str | None = None


class AsinResolver(ABC):
    """Resolves an Amazon ASIN into a product identity."""

    @abstractmethod
    async def resolve(self, asin: str, upc: str | None = None) -> ProductIdentity | None:
        """Return the product identity for an ASIN, or None if unresolvable."""


class PassthroughAsinResolver(AsinResolver):
    """Default resolver: returns the ASIN and whatever UPC the caller supplied.

    Plug in a richer resolver (product catalog, Keepa, Marketplace) to
    auto-derive the UPC and title from the ASIN.
    """

    async def resolve(self, asin: str, upc: str | None = None) -> ProductIdentity | None:
        if not asin:
            return None
        return ProductIdentity(asin=asin, upc=upc)
