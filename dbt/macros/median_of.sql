{#- Cross-database median. dbt ships dateadd/datediff/last_day/concat; it does not ship median. -#}
{% macro median_of(expr) -%}
  {%- if target.type in ('duckdb', 'snowflake') -%}
    median({{ expr }})
  {%- elif target.type == 'bigquery' -%}
    approx_quantiles({{ expr }}, 2)[offset(1)]
  {%- elif target.type in ('postgres', 'redshift') -%}
    percentile_cont(0.5) within group (order by {{ expr }})
  {%- else -%}
    median({{ expr }})
  {%- endif -%}
{%- endmacro %}
