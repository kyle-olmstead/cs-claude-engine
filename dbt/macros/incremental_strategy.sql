{#- Pick an incremental strategy every supported adapter accepts. -#}
{% macro cse_incremental_strategy() -%}
  {{ return('merge' if target.type in ('snowflake', 'bigquery', 'databricks') else 'delete+insert') }}
{%- endmacro %}
