with pub_categories as (
  select
    category_id,
    name_en
  from {{ ref("stg_everef_ref_categories") }}
  where published = true
)

select * from pub_categories
