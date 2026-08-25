{% macro cleanup_untracked_relations(apply=false, curated_writer_lock_held=false, max_drop_count=20) %}
    {% if apply is not boolean %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: apply must be a boolean') %}
    {% endif %}

    {% if curated_writer_lock_held is not boolean %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: curated_writer_lock_held must be a boolean') %}
    {% endif %}

    {% if apply and not curated_writer_lock_held %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: apply requires curated_writer_lock_held=true after the caller establishes curated-writer serialization') %}
    {% endif %}

    {% if max_drop_count is not number or max_drop_count < 0 %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: max_drop_count must be a non-negative number') %}
    {% endif %}

    {% set raw_alias = env_var('DBT_DUCKLAKE_ALIAS', 'raw_lake') %}
    {% set curated_database = env_var('CURATED_DUCKLAKE_ALIAS', 'curated_lake') %}
    {% set curated_schema = env_var('CURATED_DUCKLAKE_SCHEMA', 'curated') %}
    {% set managed_pairs = [] %}
    {% set managed_pair_inputs = [
        {'database': target.database, 'schema': target.schema},
        {'database': curated_database, 'schema': curated_schema}
    ] %}

    {% for pair in managed_pair_inputs %}
        {% if pair.database is none or pair.schema is none %}
            {% do exceptions.raise_compiler_error('cleanup_untracked_relations: managed database and schema must be configured') %}
        {% endif %}

        {% if pair.database | lower in ['raw_lake', raw_alias | lower] %}
            {% do exceptions.raise_compiler_error('cleanup_untracked_relations: refusing to inspect the raw DuckLake catalog') %}
        {% endif %}

        {% set duplicate = namespace(value=false) %}
        {% for managed_pair in managed_pairs %}
            {% if managed_pair.database | lower == pair.database | lower and managed_pair.schema | lower == pair.schema | lower %}
                {% set duplicate.value = true %}
            {% endif %}
        {% endfor %}
        {% if not duplicate.value %}
            {% do managed_pairs.append({'database': pair.database, 'schema': pair.schema}) %}
        {% endif %}
    {% endfor %}

    {% set desired_relations = [] %}
    {% for node in graph.nodes.values() %}
        {% if node.config.enabled and node.resource_type in ['model', 'seed', 'snapshot'] and node.config.materialized != 'ephemeral' %}
            {% if node.database is none or node.schema is none or node.alias is none %}
                {% do exceptions.raise_compiler_error('cleanup_untracked_relations: enabled node ' ~ node.unique_id ~ ' has an unresolved relation') %}
            {% endif %}
            {% do desired_relations.append({'database': node.database, 'schema': node.schema, 'identifier': node.alias}) %}
        {% endif %}
    {% endfor %}

    {% if desired_relations | length == 0 %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: refusing to run with an empty desired graph') %}
    {% endif %}

    {% set managed_predicates = [] %}
    {% for pair in managed_pairs %}
        {% do managed_predicates.append("(lower(table_catalog) = '" ~ (pair.database | lower | replace("'", "''")) ~ "' and lower(table_schema) = '" ~ (pair.schema | lower | replace("'", "''")) ~ "')") %}
    {% endfor %}

    {% set inspection_sql %}
        select table_catalog, table_schema, table_name, table_type
        from system.information_schema.tables
        where {{ managed_predicates | join(' or ') }}
        order by lower(table_catalog), lower(table_schema), lower(table_name), table_type
    {% endset %}
    {% set inspected = run_query(inspection_sql) %}
    {% if inspected is none %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: relation inspection returned no result') %}
    {% endif %}

    {% set eligible_candidates = [] %}
    {% for row in inspected.rows %}
        {% set candidate = {
            'database': row['table_catalog'],
            'schema': row['table_schema'],
            'identifier': row['table_name'],
            'table_type': row['table_type']
        } %}
        {% if candidate.table_type | upper in ['BASE TABLE', 'VIEW'] %}
            {% set desired = namespace(value=false) %}
            {% for relation in desired_relations %}
                {% if relation.database | lower == candidate.database | lower and relation.schema | lower == candidate.schema | lower and relation.identifier | lower == candidate.identifier | lower %}
                    {% set desired.value = true %}
                {% endif %}
            {% endfor %}
            {% if not desired.value %}
                {% do eligible_candidates.append(candidate) %}
            {% endif %}
        {% else %}
            {% do log('cleanup_untracked_relations: preserving unsupported ' ~ candidate.table_type ~ ' ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
        {% endif %}
    {% endfor %}

    {% if eligible_candidates | length > max_drop_count | int %}
        {% do exceptions.raise_compiler_error('cleanup_untracked_relations: eligible candidate count ' ~ (eligible_candidates | length) ~ ' exceeds max_drop_count ' ~ (max_drop_count | int)) %}
    {% endif %}

    {% if not apply %}
        {% do log('cleanup_untracked_relations: dry run; eligible candidates: ' ~ (eligible_candidates | length), info=true) %}
        {% for candidate in eligible_candidates %}
            {% do log('cleanup_untracked_relations: would drop ' ~ candidate.table_type ~ ' ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
        {% endfor %}
    {% else %}
        {% do log('cleanup_untracked_relations: apply mode; eligible candidates: ' ~ (eligible_candidates | length), info=true) %}
        {% for candidate in eligible_candidates %}
            {% set desired = namespace(value=false) %}
            {% for relation in desired_relations %}
                {% if relation.database | lower == candidate.database | lower and relation.schema | lower == candidate.schema | lower and relation.identifier | lower == candidate.identifier | lower %}
                    {% set desired.value = true %}
                {% endif %}
            {% endfor %}

            {% if desired.value %}
                {% do log('cleanup_untracked_relations: skipping now-tracked ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
            {% else %}
                {% set recheck_sql %}
                    select table_type
                    from system.information_schema.tables
                    where lower(table_catalog) = '{{ candidate.database | lower | replace("'", "''") }}'
                      and lower(table_schema) = '{{ candidate.schema | lower | replace("'", "''") }}'
                      and lower(table_name) = '{{ candidate.identifier | lower | replace("'", "''") }}'
                {% endset %}
                {% set rechecked = run_query(recheck_sql) %}
                {% if rechecked is none %}
                    {% do exceptions.raise_compiler_error('cleanup_untracked_relations: relation recheck returned no result') %}
                {% elif rechecked.rows | length == 0 %}
                    {% do log('cleanup_untracked_relations: skipping missing ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
                {% elif rechecked.rows[0]['table_type'] | upper not in ['BASE TABLE', 'VIEW'] %}
                    {% do log('cleanup_untracked_relations: preserving rechecked unsupported ' ~ rechecked.rows[0]['table_type'] ~ ' ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
                {% else %}
                    {% set relation_type = 'table' if rechecked.rows[0]['table_type'] | upper == 'BASE TABLE' else 'view' %}
                    {% set relation = api.Relation.create(database=candidate.database, schema=candidate.schema, identifier=candidate.identifier, type=relation_type) %}
                    {% do adapter.drop_relation(relation) %}
                    {% do log('cleanup_untracked_relations: dropped ' ~ rechecked.rows[0]['table_type'] ~ ' ' ~ candidate.database ~ '.' ~ candidate.schema ~ '.' ~ candidate.identifier, info=true) %}
                {% endif %}
            {% endif %}
        {% endfor %}
    {% endif %}
{% endmacro %}
