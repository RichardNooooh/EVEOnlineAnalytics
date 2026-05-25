install postgres;
load postgres;
install ducklake;
load ducklake;

attach '${CURATED_DUCKLAKE_ATTACH_PATH}' as ${CURATED_DUCKLAKE_ALIAS} (
  data_path '${CURATED_DUCKLAKE_DATA_PATH}',
  metadata_schema '${CURATED_DUCKLAKE_METADATA_SCHEMA}',
  override_data_path ${CURATED_DUCKLAKE_OVERRIDE_DATA_PATH},
  read_only
);

select *
from ${CURATED_DUCKLAKE_ALIAS}.${CURATED_DUCKLAKE_SCHEMA}.curated_trade_volume
