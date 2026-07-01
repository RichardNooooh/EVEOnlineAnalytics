with history as (
    select
        cast(date as date) as market_date,
        cast(region_id as bigint) as region_id,
        cast(type_id as bigint) as type_id,
        cast(source_ref_id as varchar) as source_ref_id,
        cast(source_market_date as date) as row_source_market_date
    from {{ source('everef', 'raw_market_history') }}
),

objects as (
    select
        cast(source_ref_id as varchar) as source_ref_id,
        cast(source_market_date as date) as source_market_date,
        cast(source_url as varchar) as source_url,
        cast(storage_uri as varchar) as storage_uri,
        cast(sha256 as varchar) as source_sha256,
        cast(content_length as bigint) as source_content_length,
        cast(last_modified as timestamp) as source_last_modified,
        cast(downloaded_at as timestamp) as source_downloaded_at,
        cast(parsed_at as timestamp) as parsed_at,
        cast(ingested_at as timestamp) as ingested_at,
        cast(status as varchar) as status
    from {{ source('everef', 'raw_market_history_objects') }}
)

select
    history.market_date,
    history.region_id,
    history.type_id,
    history.source_ref_id,
    history.row_source_market_date,
    objects.source_market_date,
    objects.source_url,
    objects.storage_uri,
    objects.source_sha256,
    objects.source_content_length,
    objects.source_last_modified,
    objects.source_downloaded_at,
    objects.parsed_at,
    objects.ingested_at,
    objects.status
from history
left join objects
    on history.source_ref_id = objects.source_ref_id
