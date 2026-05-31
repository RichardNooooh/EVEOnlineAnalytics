from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from eve_ingest.raw_objects.primitives import UpdateMode


def _enum_values(enum_cls: type[UpdateMode]) -> list[str]:
    return [member.value for member in enum_cls]


_METADATA = MetaData()

raw_objects = Table(
    "raw_objects",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column("source_name", Text, nullable=False),
    Column("dataset_name", Text, nullable=False),
    Column("identity_key", JSON().with_variant(JSONB, "postgresql"), nullable=False),
    Column("identity_hash", Text, nullable=False),
    Column(
        "update_mode",
        Enum(UpdateMode, native_enum=False, values_callable=_enum_values),
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_checked_at", DateTime(timezone=True)),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("content_length", Integer),
    UniqueConstraint(
        "source_name",
        "dataset_name",
        "identity_hash",
        name="raw_objects_source_dataset_identity_key",
    ),
)

raw_object_versions = Table(
    "raw_object_versions",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column(
        "raw_object_id",
        Text,
        ForeignKey("raw_objects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source_url", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("content_length", Integer),
    Column("sha256", Text, nullable=False),
    Column("local_path", Text, nullable=False),
    Column("storage_encoding", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
)

raw_object_publications = Table(
    "raw_object_publications",
    _METADATA,
    Column("id", Text, primary_key=True),
    Column("source_name", Text, nullable=False),
    Column("dataset_name", Text, nullable=False),
    Column("identity_hash", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("version_id", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("publication_scope", Text),
    Column("publisher_run_id", Text),
    UniqueConstraint(
        "source_name",
        "dataset_name",
        "identity_hash",
        "sha256",
        name="raw_object_publications_unique_version",
    ),
)

Index(
    "raw_object_versions_latest_idx",
    raw_object_versions.c.raw_object_id,
    raw_object_versions.c.fetched_at.desc(),
    raw_object_versions.c.id.desc(),
)
