"""Raw object acquisition package, designed for everef.net bulk archive downloads
and similar file-object sources.

This module is NOT intended for streaming or REST API pagination-style sources
(such as ESI endpoints). Those should use dlt-based ingestion instead.

Public API types are re-exported here for convenience:

    from eve_ingest.raw_objects import RawObjectRequest, AcquiredRawObject, AcquisitionMode
    from eve_ingest.raw_objects import RawObjectStore
"""

from eve_ingest.raw_objects.models import RawObjectRequest as RawObjectRequest
from eve_ingest.raw_objects.models import AcquiredRawObject as AcquiredRawObject
from eve_ingest.raw_objects.models import AcquisitionStatus as AcquisitionStatus
from eve_ingest.raw_objects.models import AcquisitionMode as AcquisitionMode
from eve_ingest.raw_objects.primitives import IdentityKey as IdentityKey
from eve_ingest.raw_objects.primitives import IdentityScalar as IdentityScalar
from eve_ingest.raw_objects.primitives import UpdateMode as UpdateMode
from eve_ingest.raw_objects.downloader import RawObjectDownloader as RawObjectDownloader
from eve_ingest.raw_objects.file_store import RawObjectFileStore as RawObjectFileStore
from eve_ingest.raw_objects.publishing import PublicationTracker as PublicationTracker
from eve_ingest.raw_objects.repository import RawObjectRepository as RawObjectRepository
from eve_ingest.raw_objects.store import RawObjectStore as RawObjectStore
