with types as (
  select
    type_id,
    name_en as type_name,
    description_en as type_description,
    published as type_published,
    group_id,
    category_id,
    market_group_id,
    volume
  from {{ ref('stg_everef_ref_types') }}
),

groups as (
  select
    group_id,
    name_en as group_name,
    published as group_published
  from {{ ref('stg_everef_ref_groups') }}
),

categories as (
  select
    category_id,
    name_en as category_name,
    published as category_published
  from {{ ref('stg_everef_ref_categories') }}
),

market_groups as (
  select
    market_group_id,
    name_en as market_group_name,
    description_en as market_group_description
  from {{ ref('stg_everef_ref_market_groups') }}
)

select
  t.type_id,
  t.type_name,
  t.type_description,
  g.group_id,
  g.group_name,
  c.category_id,
  c.category_name,
  mg.market_group_id,
  mg.market_group_name,
  mg.market_group_description
from types as t
inner join groups as g
  on t.group_id = g.group_id
inner join categories as c
  on t.category_id = c.category_id
left join market_groups as mg
  on t.market_group_id = mg.market_group_id
