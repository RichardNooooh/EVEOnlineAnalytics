"""Fetch plan types for raw object cache resolution.

Plans are built from ``CacheObject`` inputs and resolved against the ledger.
An ``UnresolvedFetchPlan`` means the ledger hasn't seen this identity before;
a ``ResolvedFetchPlan`` carries current ledger state so the cache can attempt
a local hit or a conditional revalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ingest.cache.primitives import IdentityKey, UpdateMode
from ingest.cache.ledger.types import RawObjectEntry, RawObjectRef, RawObjectVersion


@dataclass(frozen=True)
class BaseFetchPlan:
    """Immutable fetch plan built from a ``CacheObject`` before ledger resolution.

    Carries everything needed to perform an HTTP read: URL, identity, policy,
    and the temporary path where the response body should be streamed.
    """

    ref: RawObjectRef
    source_url: str
    source_relative_path: str
    update_mode: UpdateMode
    identity_key: IdentityKey
    temp_path: str


@dataclass(frozen=True)
class UnresolvedFetchPlan(BaseFetchPlan):
    """Fetch plan for an object not yet known to the ledger.

    The ledger has never recorded this identity hash, so no ``raw_object``
    entry or ``current_version`` exists. A full fetch is required.
    """

    pass


@dataclass(frozen=True)
class ResolvedFetchPlan(BaseFetchPlan):
    """Fetch plan enriched with complete ledger state.

    Both ``raw_object`` and ``current_version`` are guaranteed present.
    """

    raw_object: RawObjectEntry
    current_version: RawObjectVersion


FetchPlan: TypeAlias = UnresolvedFetchPlan | ResolvedFetchPlan
