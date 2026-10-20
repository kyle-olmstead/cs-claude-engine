{#-
  CI only. scripts/check_warehouses.py copies this file into a scratch copy of the project so the
  models can be compiled for Snowflake, BigQuery and Databricks without connecting to them. It is
  never part of the shipped project, and every override is inert unless --vars sets
  cse_offline_compile: true.

  - is_incremental(): normally asks the warehouse whether the table exists; offline, compile the
    full-refresh path.
  - databricks__dateadd / databricks__datediff: normally ask the live runtime whether timestampadd
    and timestampdiff exist; offline, assume a current SQL warehouse, which has both.
-#}

{% macro is_incremental() -%}
  {%- if var('cse_offline_compile', false) -%}
    {{ return(false) }}
  {%- else -%}
    {{ return(dbt.is_incremental()) }}
  {%- endif -%}
{%- endmacro %}

{% macro databricks__dateadd(datepart, interval, from_date_or_timestamp) -%}
  {%- if var('cse_offline_compile', false) -%}
    timestampadd({{ datepart }}, {{ interval }}, {{ from_date_or_timestamp }})
  {%- else -%}
    {{ return(dbt.databricks__dateadd(datepart, interval, from_date_or_timestamp)) }}
  {%- endif -%}
{%- endmacro %}

{% macro databricks__datediff(first_date, second_date, datepart) -%}
  {%- if var('cse_offline_compile', false) -%}
    timestampdiff({{ datepart }}, {{ date_trunc(datepart, first_date) }}, {{ date_trunc(datepart, second_date) }})
  {%- else -%}
    {{ return(dbt.databricks__datediff(first_date, second_date, datepart)) }}
  {%- endif -%}
{%- endmacro %}
