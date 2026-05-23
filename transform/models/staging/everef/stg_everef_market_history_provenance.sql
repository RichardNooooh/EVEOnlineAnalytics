with source as (
    select
        cast(date as date) as date,
        cast(region_id as bigint) as region_id,
        cast(type_id as bigint) as type_id,
        cast(_source_market_date as date) as source_market_date,
        cast(_source_url as varchar) as source_url,
        cast(_source_local_path as varchar) as source_local_path,
        cast(_source_sha256 as varchar) as source_sha256,
        cast(_source_content_length as bigint) as source_content_length,
        cast(_source_last_modified as varchar) as source_last_modified,
        cast(_source_downloaded_at as varchar) as source_downloaded_at,
        cast(_ingested_at as varchar) as ingested_at
    from {{ source('everef', 'raw_market_history') }}
)

select
    date,
    region_id,
    type_id,
    source_market_date,
    source_url,
    source_local_path,
    source_sha256,
    source_content_length,
    source_last_modified,
    source_downloaded_at,
    ingested_at
from source
