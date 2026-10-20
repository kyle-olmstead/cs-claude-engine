{{
    config(
        materialized = 'table',
        tags = ['cs_claude_engine', 'retention']
    )
}}

/*
    mart_retention_nrr_grr
    ----------------------
    Grain: one row per period_month × window × segment, where
        window  ∈ ('monthly', 'ttm')      -- cohort anchored 1 or 12 month-ends earlier
        segment ∈ (each CRM segment, 'ALL')

    Implements docs/02_METRICS_TAXONOMY.md Part A:
        NRR               = Σ cohort ARR at t1 / Σ cohort ARR at t0
        GRR               = Σ min(ARR_t1, ARR_t0) over cohort / Σ cohort ARR at t0   (≤ 1.0 by construction)
        Logo churn rate   = churned logos / cohort logos
        Dollar churn rate = churned ARR / cohort ARR
        Net dollar churn  = (churn + contraction − expansion) / cohort ARR  (= 1 − NRR)
        Churn concentration = dollar churn rate / logo churn rate

    Cohort = accounts with ARR > 0 at the period start (t0). New logos (ARR = 0 at t0, > 0 at t1)
    are reported in new_logo_arr / new_logos but excluded from every retention ratio.

    Ramp handling: ARR changes tagged `contract_ramp` in int_arr_daily_snapshot.arr_change_reason
    are reported separately (ramp_expansion_arr) and an ex-ramp NRR is provided, because a
    contracted ramp is not a CS outcome.

    Upstream: int_arr_daily_snapshot (account_id, snapshot_date, arr, segment, arr_change_reason)
    Dialect: dbt.last_day / dbt.dateadd cross-database macros; runs on DuckDB, Snowflake, BigQuery, Postgres, Databricks.

    This mart is cheap (month-end snapshots only) and is rebuilt fully each run; the Python
    mirror is src/models/metrics_calculator.py::cohort_retention.
*/

with

month_ends as (
    -- every month-end present in the snapshot table
    select distinct {{ dbt.last_day('snapshot_date', 'month') }} as month_end
    from {{ ref('int_arr_daily_snapshot') }}
),

snapshots as (
    -- ARR at each month-end per account (the last snapshot in the month, in case month-end itself is missing)
    select
        s.account_id,
        s.segment,
        {{ dbt.last_day('s.snapshot_date', 'month') }}                                   as month_end,
        s.arr,
        s.arr_change_reason,
        row_number() over (partition by s.account_id, {{ dbt.last_day('s.snapshot_date', 'month') }} order by s.snapshot_date desc) as rn
    from {{ ref('int_arr_daily_snapshot') }} s
),

month_end_arr as (
    select account_id, segment, month_end, arr, arr_change_reason
    from snapshots
    where rn = 1
),

-- ---------------------------------------------------------------------------------
-- Period definitions: for each t1 month-end, t0 is 1 month earlier (monthly) or 12 (ttm)
-- ---------------------------------------------------------------------------------
periods as (
    select m.month_end as t1, {{ dbt.last_day(dbt.dateadd('month', -1, 'm.month_end'), 'month') }} as t0, 'monthly' as window_type from month_ends m
    union all
    select m.month_end as t1, {{ dbt.last_day(dbt.dateadd('month', -12, 'm.month_end'), 'month') }} as t0, 'ttm'     as window_type from month_ends m
),

-- ---------------------------------------------------------------------------------
-- Account-level movement for every (period, account) present at t0 or t1.
-- Built as an explicit pair set + two LEFT JOINs rather than a FULL OUTER JOIN, which is
-- dialect-sensitive when both sides are filtered.
-- ---------------------------------------------------------------------------------
account_period_pairs as (
    select p.t1 as period_month, p.t0 as period_start, p.window_type, x.account_id
    from periods p
    join (
        select distinct account_id, month_end from month_end_arr
    ) x on x.month_end in (p.t0, p.t1)
),

movements_clean as (
    select
        ap.period_month,
        ap.period_start,
        ap.window_type,
        ap.account_id,
        coalesce(a0.segment, a1.segment)                            as segment,
        coalesce(a0.arr, 0)                                         as arr_t0,
        coalesce(a1.arr, 0)                                         as arr_t1,
        a1.arr_change_reason,
        case
            when coalesce(a0.arr, 0) > 0 and coalesce(a1.arr, 0) <= 0            then 'churn'
            when coalesce(a0.arr, 0) > 0 and coalesce(a1.arr, 0) >  a0.arr        then 'expansion'
            when coalesce(a0.arr, 0) > 0 and coalesce(a1.arr, 0) <  a0.arr        then 'contraction'
            when coalesce(a0.arr, 0) > 0                                          then 'flat'
            when coalesce(a0.arr, 0) <= 0 and coalesce(a1.arr, 0) > 0             then 'new'
            else 'none'
        end                                                         as movement
    from (select distinct period_month, period_start, window_type, account_id from account_period_pairs) ap
    left join month_end_arr a0 on a0.account_id = ap.account_id and a0.month_end = ap.period_start
    left join month_end_arr a1 on a1.account_id = ap.account_id and a1.month_end = ap.period_month
),

-- ---------------------------------------------------------------------------------
-- Aggregate by segment and ALL
-- ---------------------------------------------------------------------------------
agg_base as (
    select
        period_month,
        period_start,
        window_type,
        segment,
        count(distinct case when arr_t0 > 0 then account_id end)                                             as cohort_logos,
        sum(case when arr_t0 > 0 then arr_t0 else 0 end)                                                      as start_arr,
        sum(case when arr_t0 > 0 then arr_t1 else 0 end)                                                      as end_arr_cohort,
        sum(case when movement = 'expansion' then arr_t1 - arr_t0 else 0 end)                                 as expansion_arr,
        sum(case when movement = 'expansion' and arr_change_reason = 'contract_ramp' then arr_t1 - arr_t0 else 0 end) as ramp_expansion_arr,
        sum(case when movement = 'contraction' then arr_t0 - arr_t1 else 0 end)                               as contraction_arr,
        sum(case when movement = 'churn' then arr_t0 else 0 end)                                              as churn_arr,
        count(distinct case when movement = 'churn' then account_id end)                                      as churned_logos,
        count(distinct case when movement = 'expansion' then account_id end)                                  as expanded_logos,
        count(distinct case when movement = 'contraction' then account_id end)                                as contracted_logos,
        sum(case when movement = 'new' then arr_t1 else 0 end)                                                as new_logo_arr,
        count(distinct case when movement = 'new' then account_id end)                                        as new_logos,
        sum(arr_t1)                                                                                           as end_arr_total
    from movements_clean
    group by 1, 2, 3, 4

    union all

    select
        period_month,
        period_start,
        window_type,
        'ALL'                                                                                                 as segment,
        count(distinct case when arr_t0 > 0 then account_id end),
        sum(case when arr_t0 > 0 then arr_t0 else 0 end),
        sum(case when arr_t0 > 0 then arr_t1 else 0 end),
        sum(case when movement = 'expansion' then arr_t1 - arr_t0 else 0 end),
        sum(case when movement = 'expansion' and arr_change_reason = 'contract_ramp' then arr_t1 - arr_t0 else 0 end),
        sum(case when movement = 'contraction' then arr_t0 - arr_t1 else 0 end),
        sum(case when movement = 'churn' then arr_t0 else 0 end),
        count(distinct case when movement = 'churn' then account_id end),
        count(distinct case when movement = 'expansion' then account_id end),
        count(distinct case when movement = 'contraction' then account_id end),
        sum(case when movement = 'new' then arr_t1 else 0 end),
        count(distinct case when movement = 'new' then account_id end),
        sum(arr_t1)
    from movements_clean
    group by 1, 2, 3
),

ratios as (
    select
        a.*,
        -- core ratios
        case when start_arr > 0 then end_arr_cohort / start_arr end                                           as nrr,
        case when start_arr > 0 then least(1.0, (start_arr - contraction_arr - churn_arr) / start_arr) end         as grr,   -- explicit null: least() swallows nulls on some engines
        churned_logos / cast(nullif(cohort_logos, 0) as double)                                                        as logo_churn_rate,
        churn_arr / nullif(start_arr, 0)                                                                      as dollar_churn_rate,
        (churn_arr + contraction_arr - expansion_arr) / nullif(start_arr, 0)                                   as net_dollar_churn,
        -- ex-ramp NRR: remove ramp-driven expansion from the numerator
        (end_arr_cohort - ramp_expansion_arr) / nullif(start_arr, 0)                                           as nrr_ex_ramp,
        -- expansion share of cohort
        expansion_arr / nullif(start_arr, 0)                                                                  as expansion_rate,
        contraction_arr / nullif(start_arr, 0)                                                                as contraction_rate
    from agg_base a
)

select
    period_month,
    period_start,
    window_type,
    segment,
    cohort_logos,
    start_arr,
    end_arr_cohort,
    end_arr_total,
    expansion_arr,
    ramp_expansion_arr,
    contraction_arr,
    churn_arr,
    churned_logos,
    expanded_logos,
    contracted_logos,
    new_logos,
    new_logo_arr,
    nrr,
    nrr_ex_ramp,
    grr,
    logo_churn_rate,
    dollar_churn_rate,
    net_dollar_churn,
    expansion_rate,
    contraction_rate,
    dollar_churn_rate / nullif(logo_churn_rate, 0)                                                            as churn_concentration,
    case
        when dollar_churn_rate / nullif(logo_churn_rate, 0) > 1.5 then 'large_account_skew'
        when dollar_churn_rate / nullif(logo_churn_rate, 0) < 0.7 then 'small_account_skew'
        when logo_churn_rate is null then 'no_churn'
        else 'balanced'
    end                                                                                                       as churn_concentration_label,
    -- peer-quartile context for the EBR generator: where does this segment's NRR sit across trailing periods?
    -- ranked only among periods that have an NRR: warehouses disagree on where NULLs sort (BigQuery and
    -- Databricks put them first, Snowflake and DuckDB last), and a NULL period is not a low one
    case when nrr is not null then
        percent_rank() over (partition by window_type, segment, case when nrr is null then 1 else 0 end order by nrr)
    end                                                                                                       as nrr_percentile_within_segment_history,
    current_timestamp                                                                                         as computed_at
from ratios
where cohort_logos > 0 or new_logos > 0
order by period_month desc, window_type, segment
