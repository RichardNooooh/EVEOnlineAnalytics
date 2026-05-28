"""Raw object cache package, designed for everef.net bulk archive downloads
and similar file-object sources.

This module is NOT intended for streaming or REST API pagination-style sources
(such as ESI endpoints). Those should use dlt-based ingestion instead.

Public API types are re-exported here for convenience:

    from ingest.cache import Cache, CacheObject, CacheResult, GetMode
"""

from ingest.cache.models import CacheObject as CacheObject
from ingest.cache.models import CacheResult as CacheResult
from ingest.cache.models import CacheResultStatus as CacheResultStatus
from ingest.cache.models import GetMode as GetMode
from ingest.cache.primitives import IdentityKey as IdentityKey
from ingest.cache.primitives import IdentityScalar as IdentityScalar
from ingest.cache.primitives import UpdateMode as UpdateMode
from ingest.cache.publishing import PublicationTracker as PublicationTracker
from ingest.cache.store import Cache as Cache
