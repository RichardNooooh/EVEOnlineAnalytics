"""HTTP read result types for the raw object store.

These types describe the outcome of an HTTP fetch: whether the origin
returned new content (``ModifiedRead``) or confirmed the stored version
is current (``NotModifiedRead``).  The store's ``HttpRawObjectClient``
produces these; ``RawObjectStore`` consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias


class ReadStatus(StrEnum):
    """Low-level HTTP read status from store client.

    ``NOT_MODIFIED`` means origin confirmed existing stored version still current.
    ``MODIFIED`` means client wrote fresh content to temporary storage.
    """

    NOT_MODIFIED = "not_modified"
    MODIFIED = "modified"


@dataclass(frozen=True)
class RevalidationMetadata:
    """HTTP revalidation metadata used for conditional requests.

    Carries ``ETag``, ``Last-Modified``, and ``Content-Length`` observed from the
    origin so that mutable objects can be re-fetched with ``If-None-Match`` or
    ``If-Modified-Since`` headers.
    """

    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None

    def request_headers(self) -> dict[str, str]:
        """Return conditional request headers for revalidation.

        Prefers ``If-None-Match`` when ``etag`` is present, otherwise falls back
        to ``If-Modified-Since``. Returns an empty dict when neither is set.

        Returns:
            Dict with zero or one conditional header.
        """
        if self.etag:
            return {"If-None-Match": self.etag}
        if self.last_modified:
            return {"If-Modified-Since": self.last_modified}
        return {}


@dataclass(frozen=True)
class NotModifiedRead:
    """Result when origin reports 304 Not Modified."""

    status: Literal[ReadStatus.NOT_MODIFIED]
    fetched_at: datetime
    revalidation: RevalidationMetadata = RevalidationMetadata()


@dataclass(frozen=True)
class ModifiedRead:
    """Result when origin returns new content."""

    status: Literal[ReadStatus.MODIFIED]
    fetched_at: datetime
    temp_path: str
    sha256: str
    revalidation: RevalidationMetadata = RevalidationMetadata()


ReadResult: TypeAlias = NotModifiedRead | ModifiedRead
