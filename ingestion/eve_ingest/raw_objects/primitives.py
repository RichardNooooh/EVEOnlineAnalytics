"""Primitive types for the raw object store.

Leaf module with zero store-package dependencies. All three types are re-exported
through ``models.py`` and ``__init__.py`` — import them from there or from here
depending on whether you need the full public API or just the primitives.

Dep graph:

    primitives.py ← models.py, ledger/types.py, plans.py, __init__.py
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

type IdentityScalar = str | int | float | bool | None
"""A single value in an identity key — must be a JSON-compatible scalar."""

type IdentityKey = Mapping[str, IdentityScalar]
"""Logical identity of a raw object.

Identity keys are deterministic dicts of scalar values (``str | int | float |
bool | None``) used for change detection and deduplication across acquisition runs.
"""


class UpdateMode(StrEnum):
    """Store behavior for how source object changes over time.

    ``SNAPSHOT`` means the URL points at immutable content, so the store can
    trust the local file once stored. ``MUTABLE`` means the URL may change in
    place, so the store must re-check the origin with conditional requests.
    """

    SNAPSHOT = "snapshot"
    MUTABLE = "mutable"
