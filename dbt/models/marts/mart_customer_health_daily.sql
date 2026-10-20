{{
    config(
        materialized = 'incremental',
        unique_key   = ['account_id', 'as_of_date'],
        incremental_strategy = cse_incremental_strategy(),
        on_schema_change = 'append_new_columns',
        tags = ['cs_claude_engine', 'health']
    )
}}

/*
    mart_customer_health_daily
    --------------------------
    Grain: one row per account per day.

    Implements docs/02_METRICS_TAXONOMY.md §B1 (Customer Health Score) and the leading
    indicators it depends on (DAU/MAU, feature depth/breadth, seat utilization + drift,
    engagement, support, sentiment, relationship, commercial). The Python implementation
    in src/models/health_score.py must produce the same score (±0.5); the orchestrator
    asserts this daily.

    Weights come from dbt vars so SQL and Python share one source of truth:

        vars:
          health_weights: {adoption: 0.25, engagement: 0.15, support: 0.15,
                           sentiment: 0.15, relationship: 0.15, commercial: 0.15}
          health_core_feature_count: 4

    Upstream models (see docs/01_ARCHITECTURE.md §2):
        stg_crm__accounts, stg_crm__contacts, stg_crm__activities,
        int_arr_daily_snapshot, stg_product__daily_usage, stg_product__feature_events,
        stg_support__tickets, stg_survey__responses, int_champion_status,
        int_transcript_sentiment_daily (optional; from call_transcript_parser output)

    Dialect notes: date arithmetic uses dbt's cross-database macros (dbt.dateadd, dbt.datediff,
    dbt.concat, dbt.type_string); the median uses macros/median_of.sql. CI builds it on DuckDB from
    the seeds, and scripts/check_warehouses.py compiles it with the Snowflake, BigQuery and
    Databricks adapters and requires the same rows. Postgres/Redshift branches exist in the macros
    but are not checked.
*/

{% set w = var('health_weights', {'adoption': 0.25, 'engagement': 0.15, 'support': 0.15, 'sentiment': 0.15, 'relationship': 0.15, 'commercial': 0.15}) %}
{% set core_feature_count = var('health_core_feature_count', 4) %}

with

-- ---------------------------------------------------------------------------------
-- 0. Date spine: incremental runs recompute the last 3 days to absorb late-arriving data
-- ---------------------------------------------------------------------------------
dates as (
    select distinct snapshot_date as as_of_date
    from {{ ref('int_arr_daily_snapshot') }}
    {% if is_incremental() %}
    where snapshot_date >= {{ dbt.dateadd('day', -3, '(select max(as_of_date) from ' ~ this ~ ')') }}
    {% endif %}
),

accounts as (
    select
        a.account_id,
        a.account_name,
        a.segment,
        a.csm_owner_id,
        s.snapshot_date                         as as_of_date,
        s.arr,
        s.seats_purchased,
        s.term_start,
        s.term_end,
        {{ dbt.datediff('s.snapshot_date', 's.term_end', 'day') }} as days_to_renewal,
        s.payment_days_past_due,
        s.arr_90d_ago,
        case when s.arr < s.arr_90d_ago or s.seats_purchased < s.seats_purchased_90d_ago then true else false end as contraction_flag_90d
    from {{ ref('int_arr_daily_snapshot') }} s
    join {{ ref('stg_crm__accounts') }} a using (account_id)
    join dates d on d.as_of_date = s.snapshot_date
    where s.arr > 0
),

-- ---------------------------------------------------------------------------------
-- 1. ADOPTION inputs: DAU/MAU, feature depth, seat utilization (+ 90d ago for drift)
-- ---------------------------------------------------------------------------------
usage_30d as (
    select
        a.account_id,
        a.as_of_date,
        count(distinct u.user_email)                                              as mau_30d,
        count(distinct case when u.sessions > 0 then u.user_email end)           as active_users_30d,
        count(distinct {{ dbt.concat(["cast(u.usage_date as " ~ dbt.type_string() ~ ")", "'|'", 'u.user_email']) }}) / 30.0               as avg_dau_30d
    from accounts a
    left join {{ ref('stg_product__daily_usage') }} u
        on u.account_id = a.account_id
       and u.usage_date >  {{ dbt.dateadd('day', -30, 'a.as_of_date') }}
       and u.usage_date <= a.as_of_date
       and u.sessions > 0
    group by 1, 2
),

usage_90d_ago as (
    select
        a.account_id,
        a.as_of_date,
        count(distinct u.user_email) as active_users_30d_at_90d_ago
    from accounts a
    left join {{ ref('stg_product__daily_usage') }} u
        on u.account_id = a.account_id
       and u.usage_date >  {{ dbt.dateadd('day', -120, 'a.as_of_date') }}
       and u.usage_date <= {{ dbt.dateadd('day', -90, 'a.as_of_date') }}
       and u.sessions > 0
    group by 1, 2
),

usage_presence as (
    -- the product source has produced at least one row for the account, ever. Without a row the
    -- adoption inputs are unknown (null), not zero: a dormant account with history still scores 0.
    -- The last login is the latest one ever, not the latest inside 30 days, so an account nobody
    -- has opened in two months reads "60 days since last login", not "unknown".
    select
        a.account_id,
        a.as_of_date,
        count(u.user_email) > 0                                                  as usage_observed,
        max(case when u.sessions > 0 then u.usage_date end)                      as last_login_date
    from accounts a
    left join {{ ref('stg_product__daily_usage') }} u
        on u.account_id = a.account_id and u.usage_date <= a.as_of_date
    group by 1, 2
),

features_30d as (
    select
        a.account_id,
        a.as_of_date,
        count(distinct case when f.is_core_feature then f.feature_key end)   as core_features_used_30d,
        count(distinct f.feature_key)                                         as all_features_used_30d
    from accounts a
    left join {{ ref('stg_product__feature_events') }} f
        on f.account_id = a.account_id
       and f.event_at >  {{ dbt.dateadd('day', -30, 'a.as_of_date') }}
       and f.event_at <= a.as_of_date
    group by 1, 2
),

feature_universe as (
    select count(distinct feature_key) as all_feature_count
    from {{ ref('stg_product__feature_events') }}
),

-- ---------------------------------------------------------------------------------
-- 2. ENGAGEMENT + RELATIONSHIP inputs: contacts engaged, exec engagement, CSM touch, depth
-- ---------------------------------------------------------------------------------
contact_engagement as (
    select
        a.account_id,
        a.as_of_date,
        count(distinct case when act.occurred_at > {{ dbt.dateadd('day', -90, 'a.as_of_date') }} then act.contact_id end)                       as engaged_contacts_90d,
        count(distinct case when act.occurred_at > {{ dbt.dateadd('day', -90, 'a.as_of_date') }} then coalesce(c.function, c.persona) end)     as functions_engaged_90d,
        count(distinct case when act.occurred_at > {{ dbt.dateadd('day', -90, 'a.as_of_date') }} then c.seniority end)                        as seniorities_engaged_90d,
        max(case when c.is_exec_sponsor and act.occurred_at > {{ dbt.dateadd('day', -180, 'a.as_of_date') }} then 1 else 0 end) = 1           as exec_sponsor_engaged_180d,
        max(case when act.direction = 'outbound' and act.owner_id = a.csm_owner_id then act.occurred_at end)                     as last_csm_touch_at
    from accounts a
    left join {{ ref('stg_crm__activities') }} act
        on act.account_id = a.account_id
       and act.occurred_at <= a.as_of_date
       and act.occurred_at >  {{ dbt.dateadd('day', -180, 'a.as_of_date') }}
    left join {{ ref('stg_crm__contacts') }} c
        on c.contact_id = act.contact_id
    group by 1, 2, a.csm_owner_id
),

champion as (
    select
        account_id,
        champion_status,
        champion_last_engaged_at,
        replacement_identified
    from {{ ref('int_champion_status') }}
),

-- ---------------------------------------------------------------------------------
-- 3. SUPPORT inputs
-- ---------------------------------------------------------------------------------
support as (
    select
        a.account_id,
        a.as_of_date,
        count(t.ticket_id) > 0                                                                                                  as support_observed,
        count(case when t.status not in ('solved', 'closed') and t.priority in ('P1', 'P2') then 1 end)                          as open_p1_p2,
        max(case when t.status not in ('solved', 'closed') and t.priority = 'P1'
                  then {{ dbt.datediff('t.created_at', 'a.as_of_date', 'day') }} end)                                                          as oldest_open_p1_age_days,
        count(case when t.created_at > {{ dbt.dateadd('day', -30, 'a.as_of_date') }} then 1 end)                                             as tickets_30d,
        avg(case when t.csat_score is not null and t.resolved_at > {{ dbt.dateadd('day', -90, 'a.as_of_date') }} then t.csat_score end)      as avg_csat_90d,
        {{ median_of("case when t.first_response_at is not null and t.created_at > " ~ dbt.dateadd('day', -90, 'a.as_of_date') ~ "
                    then " ~ dbt.datediff('t.created_at', 't.first_response_at', 'minute') ~ " / 60.0 end") }}                               as median_first_response_hours_90d
    from accounts a
    left join {{ ref('stg_support__tickets') }} t
        on t.account_id = a.account_id
       and t.created_at <= a.as_of_date
    group by 1, 2
),

-- ---------------------------------------------------------------------------------
-- 4. SENTIMENT inputs: seniority-weighted relationship NPS (latest per contact, 180d), trend, transcripts
-- ---------------------------------------------------------------------------------
nps_latest_per_contact as (
    select
        r.account_id,
        a.as_of_date,
        r.contact_id,
        r.score,
        r.responded_at,
        case c.seniority when 'c_level' then 2.0 when 'vp' then 2.0 when 'director' then 1.5 when 'manager' then 1.5 else 1.0 end as w,
        row_number() over (partition by r.account_id, a.as_of_date, r.contact_id order by r.responded_at desc) as rn
    from accounts a
    join {{ ref('stg_survey__responses') }} r
        on r.account_id = a.account_id
       and r.survey_type = 'nps'
       and r.responded_at <= a.as_of_date
       and r.responded_at >  {{ dbt.dateadd('day', -180, 'a.as_of_date') }}
    left join {{ ref('stg_crm__contacts') }} c on c.contact_id = r.contact_id
),

nps_account as (
    select
        account_id,
        as_of_date,
        round(100.0 * (sum(case when score >= 9 then w else 0 end) - sum(case when score <= 6 then w else 0 end)) / nullif(sum(w), 0)) as latest_nps,
        max(responded_at) as latest_nps_at
    from nps_latest_per_contact
    where rn = 1
    group by 1, 2
),

nps_prior as (
    -- the same calculation anchored 90 days earlier, for the trend
    select
        r.account_id,
        a.as_of_date,
        round(100.0 * (sum(case when r.score >= 9 then 1 else 0 end) - sum(case when r.score <= 6 then 1 else 0 end)) / nullif(count(*), 0)) as prior_nps
    from accounts a
    join {{ ref('stg_survey__responses') }} r
        on r.account_id = a.account_id
       and r.survey_type = 'nps'
       and r.responded_at <= {{ dbt.dateadd('day', -90, 'a.as_of_date') }}
       and r.responded_at >  {{ dbt.dateadd('day', -270, 'a.as_of_date') }}
    group by 1, 2
),

transcripts as (
    select
        a.account_id,
        a.as_of_date,
        avg(ts.sentiment) as transcript_sentiment_30d
    from accounts a
    left join {{ ref('int_transcript_sentiment_daily') }} ts
        on ts.account_id = a.account_id
       and ts.occurred_at >  {{ dbt.dateadd('day', -30, 'a.as_of_date') }}
       and ts.occurred_at <= a.as_of_date
    group by 1, 2
),

-- ---------------------------------------------------------------------------------
-- 5. Assemble raw inputs
-- ---------------------------------------------------------------------------------
inputs as (
    select
        a.*,
        -- adoption (null, not 0, when the product source has never reported this account; mirrors usage.* = null in Python)
        coalesce(up.usage_observed, false)                                                                      as usage_observed,
        case when not up.usage_observed then null when u.mau_30d > 0 then least(u.avg_dau_30d / u.mau_30d, 1.0) else 0 end as dau_mau_30d,
        case when up.usage_observed then u.mau_30d end                                                           as mau_30d,
        case when up.usage_observed then u.active_users_30d end                                                  as active_users_30d,
        case when up.usage_observed then f.core_features_used_30d / cast({{ core_feature_count }} as double) end        as feature_depth_30d,
        case when up.usage_observed then f.all_features_used_30d / cast(nullif(fu.all_feature_count, 0) as double) end  as feature_breadth_30d,
        case when up.usage_observed and a.seats_purchased > 0 then u.active_users_30d / cast(a.seats_purchased as double) end             as seat_utilization,
        case when up.usage_observed and a.seats_purchased > 0 then u90.active_users_30d_at_90d_ago / cast(a.seats_purchased as double) end as seat_utilization_90d_ago,
        case when up.usage_observed then {{ dbt.datediff('up.last_login_date', 'a.as_of_date', 'day') }} end                 as days_since_last_login,
        -- engagement / relationship
        ce.engaged_contacts_90d,
        case when ce.functions_engaged_90d >= 2 or ce.seniorities_engaged_90d >= 2 then ce.engaged_contacts_90d
             when ce.engaged_contacts_90d > 0 then 1 else 0 end                                                 as multithreading_depth,
        coalesce(ce.exec_sponsor_engaged_180d, false)                                                            as exec_sponsor_engaged_180d,
        {{ dbt.datediff('ce.last_csm_touch_at', 'a.as_of_date', 'day') }}                                                       as days_since_last_csm_touch,
        coalesce(ch.champion_status, 'none')                                                                     as champion_status,
        coalesce(ch.replacement_identified, false)                                                               as replacement_identified,
        -- support (support_observed = the desk produced any row for this account; mirrors support.open_tickets null vs [] in Python)
        coalesce(s.support_observed, false)                                                                      as support_observed,
        coalesce(s.open_p1_p2, 0)                                                                                as open_p1_p2,
        s.oldest_open_p1_age_days,
        case when coalesce(s.support_observed, false) and a.seats_purchased > 0 then 100.0 * coalesce(s.tickets_30d, 0) / a.seats_purchased end as tickets_per_100_seats_30d,
        s.avg_csat_90d,
        s.median_first_response_hours_90d,
        -- sentiment
        n.latest_nps,
        n.latest_nps_at,
        case when n.latest_nps is null or np.prior_nps is null then null
             when n.latest_nps - np.prior_nps >= 10 then 'improving'
             when np.prior_nps - n.latest_nps >= 10 then 'worsening'
             else 'stable' end                                                                                   as nps_trend,
        t.transcript_sentiment_30d
    from accounts a
    left join usage_30d u          on u.account_id = a.account_id and u.as_of_date = a.as_of_date
    left join usage_presence up    on up.account_id = a.account_id and up.as_of_date = a.as_of_date
    left join usage_90d_ago u90    on u90.account_id = a.account_id and u90.as_of_date = a.as_of_date
    left join features_30d f       on f.account_id = a.account_id and f.as_of_date = a.as_of_date
    cross join feature_universe fu
    left join contact_engagement ce on ce.account_id = a.account_id and ce.as_of_date = a.as_of_date
    left join champion ch           on ch.account_id = a.account_id
    left join support s             on s.account_id = a.account_id and s.as_of_date = a.as_of_date
    left join nps_account n         on n.account_id = a.account_id and n.as_of_date = a.as_of_date
    left join nps_prior np          on np.account_id = a.account_id and np.as_of_date = a.as_of_date
    left join transcripts t         on t.account_id = a.account_id and t.as_of_date = a.as_of_date
),

-- ---------------------------------------------------------------------------------
-- 6. Normalize each input to 0..100 (mirrors src/models/health_score.py exactly)
-- ---------------------------------------------------------------------------------
normalized as (
    select
        i.*,
        -- adoption sub-scores. Explicit null guards: greatest()/least() ignore NULLs on DuckDB and Postgres
        -- (greatest(0, NULL) = 0), which would turn a missing input into a score of 0.
        case when dau_mau_30d is null then null else least(100, greatest(0, (dau_mau_30d - 0.05) * 100.0 / 0.35)) end       as n_dau_mau,
        case when feature_depth_30d is null then null else least(100, greatest(0, feature_depth_30d * 100.0)) end             as n_depth,
        case when seat_utilization is null then null else least(100, greatest(0, (seat_utilization - 0.30) * 100.0 / 0.60)) end as n_util,
        -- engagement sub-scores
        case when days_since_last_login is null then null
             when days_since_last_login <= 0 then 100
             when days_since_last_login <= 14 then 100 - days_since_last_login * (50.0 / 14)
             when days_since_last_login <= 30 then 50 - (days_since_last_login - 14) * (50.0 / 16)
             else 0 end                                                                                          as n_login,
        case when engaged_contacts_90d is null then null
             when engaged_contacts_90d <= 0 then 0
             when engaged_contacts_90d = 1 then 20
             when engaged_contacts_90d = 2 then 50
             when engaged_contacts_90d = 3 then 75
             else 100 end                                                                                        as n_contacts,
        case when exec_sponsor_engaged_180d then 100 else 0 end                                                  as n_exec,
        -- support sub-scores
        case when not support_observed then null when open_p1_p2 = 0 then 100 when open_p1_p2 = 1 then 60 else 20 end as n_p1p2,
        case when tickets_per_100_seats_30d is null then null
             else least(100, greatest(0, 100 - (tickets_per_100_seats_30d - 2.0) * 100.0 / 8.0)) end           as n_volume,
        case when avg_csat_90d is null then null else least(100, greatest(0, (avg_csat_90d - 1) / 4.0 * 100)) end as n_csat,
        case when median_first_response_hours_90d is null then null
             else least(100, greatest(0, 100 - (median_first_response_hours_90d - 4.0) * 100.0 / 44.0)) end     as n_frt,
        -- sentiment sub-scores
        case when latest_nps is null then null else least(100, greatest(0, (latest_nps + 100) / 2.0)) end        as n_nps,
        case nps_trend when 'improving' then 100 when 'worsening' then 0 when 'stable' then 50 else null end     as n_trend,
        case when transcript_sentiment_30d is null then null
             else least(100, greatest(0, (transcript_sentiment_30d + 1) / 2.0 * 100)) end                        as n_transcript,
        -- relationship sub-scores
        case champion_status when 'active' then 100 when 'at_risk' then 50 when 'none' then 30 when 'departed' then 0 end as n_champion,
        case when multithreading_depth is null then null
             when multithreading_depth <= 0 then 0 when multithreading_depth = 1 then 20
             when multithreading_depth = 2 then 50 when multithreading_depth = 3 then 75 else 100 end            as n_depth_rel,
        case when days_since_last_csm_touch is null then null
             else least(100, greatest(0, 100 - (days_since_last_csm_touch - 14) * 100.0 / 31.0)) end           as n_csm_touch,
        -- commercial sub-scores
        case when days_to_renewal is null then null
             when days_to_renewal <= 0 then 40
             when days_to_renewal <= 30 then 40 + days_to_renewal * (20.0 / 30)
             when days_to_renewal <= 90 then 60 + (days_to_renewal - 30) * (20.0 / 60)
             when days_to_renewal <= 180 then 80 + (days_to_renewal - 90) * (20.0 / 90)
             else 100 end                                                                                        as n_renewal,
        case when coalesce(payment_days_past_due, 0) <= 0 then 100
             when payment_days_past_due <= 30 then 100 - payment_days_past_due * (40.0 / 30)
             when payment_days_past_due <= 60 then 60 - (payment_days_past_due - 30) * (60.0 / 30)
             else 0 end                                                                                          as n_past_due
    from inputs i
),

-- ---------------------------------------------------------------------------------
-- 7. Component scores (mean / weighted mean over available inputs, re-normalized)
-- ---------------------------------------------------------------------------------
components as (
    select
        n.*,
        -- adoption: mean of available
        (coalesce(n_dau_mau, 0) + coalesce(n_depth, 0) + coalesce(n_util, 0))
            / nullif((case when n_dau_mau is not null then 1 else 0 end) + (case when n_depth is not null then 1 else 0 end) + (case when n_util is not null then 1 else 0 end), 0) as c_adoption,
        -- engagement: weighted .4/.3/.3
        (coalesce(n_login * 0.4, 0) + coalesce(n_contacts * 0.3, 0) + coalesce(n_exec * 0.3, 0))
            / nullif((case when n_login is not null then 0.4 else 0 end) + (case when n_contacts is not null then 0.3 else 0 end) + (case when n_exec is not null then 0.3 else 0 end), 0) as c_engagement,
        -- support: mean of available
        (coalesce(n_p1p2, 0) + coalesce(n_volume, 0) + coalesce(n_csat, 0) + coalesce(n_frt, 0))
            / nullif((case when n_p1p2 is not null then 1 else 0 end) + (case when n_volume is not null then 1 else 0 end) + (case when n_csat is not null then 1 else 0 end) + (case when n_frt is not null then 1 else 0 end), 0) as c_support,
        -- sentiment: weighted .5/.1/.4
        (coalesce(n_nps * 0.5, 0) + coalesce(n_trend * 0.1, 0) + coalesce(n_transcript * 0.4, 0))
            / nullif((case when n_nps is not null then 0.5 else 0 end) + (case when n_trend is not null then 0.1 else 0 end) + (case when n_transcript is not null then 0.4 else 0 end), 0) as c_sentiment,
        -- relationship: weighted .5/.3/.2
        (coalesce(n_champion * 0.5, 0) + coalesce(n_depth_rel * 0.3, 0) + coalesce(n_csm_touch * 0.2, 0))
            / nullif((case when n_champion is not null then 0.5 else 0 end) + (case when n_depth_rel is not null then 0.3 else 0 end) + (case when n_csm_touch is not null then 0.2 else 0 end), 0) as c_relationship,
        -- commercial: mean of renewal + past due, minus 30 for contraction
        least(100, greatest(0,
            (coalesce(n_renewal, 0) + coalesce(n_past_due, 0))
                / nullif((case when n_renewal is not null then 1 else 0 end) + (case when n_past_due is not null then 1 else 0 end), 0)
            - case when contraction_flag_90d then 30 else 0 end)) as c_commercial
    from normalized n
),

observed as (
    select
        c.*,
        -- share of the total weight whose components had at least one input (mirrors HealthScoreResult.coverage)
        (case when c_adoption     is not null then {{ w['adoption'] }}     else 0 end)
      + (case when c_engagement   is not null then {{ w['engagement'] }}   else 0 end)
      + (case when c_support      is not null then {{ w['support'] }}      else 0 end)
      + (case when c_sentiment    is not null then {{ w['sentiment'] }}    else 0 end)
      + (case when c_relationship is not null then {{ w['relationship'] }} else 0 end)
      + (case when c_commercial   is not null then {{ w['commercial'] }}   else 0 end) as observed_weight
    from components c
),

weighted as (
    select
        o.*,
        observed_weight / ({{ w['adoption'] }} + {{ w['engagement'] }} + {{ w['support'] }} + {{ w['sentiment'] }} + {{ w['relationship'] }} + {{ w['commercial'] }}) as health_coverage,
        -- an unobserved component contributes 0 and its weight is redistributed over the observed ones
        coalesce(c_adoption     * {{ w['adoption'] }}     / nullif(observed_weight, 0), 0) as contrib_adoption,
        coalesce(c_engagement   * {{ w['engagement'] }}   / nullif(observed_weight, 0), 0) as contrib_engagement,
        coalesce(c_support      * {{ w['support'] }}      / nullif(observed_weight, 0), 0) as contrib_support,
        coalesce(c_sentiment    * {{ w['sentiment'] }}    / nullif(observed_weight, 0), 0) as contrib_sentiment,
        coalesce(c_relationship * {{ w['relationship'] }} / nullif(observed_weight, 0), 0) as contrib_relationship,
        coalesce(c_commercial   * {{ w['commercial'] }}   / nullif(observed_weight, 0), 0) as contrib_commercial
    from observed o
),

raw_scores as (
    select
        w.*,
        contrib_adoption + contrib_engagement + contrib_support + contrib_sentiment + contrib_relationship + contrib_commercial as raw_weighted_sum
    from weighted w
),

-- ---------------------------------------------------------------------------------
-- 8. Trend adjustment, overrides, band
-- ---------------------------------------------------------------------------------
-- Prior-day lookups come from this run's rows plus, on incremental runs, the existing table.
-- A date-anchored self-join (not a row LAG) so gaps in the spine cannot shift the window.
-- The trend reads the prior raw sum; the prior *scores* are looked up after the final score
-- exists (see `history` below), so a full refresh and an incremental run agree.
prior_rows as (
    select account_id, as_of_date, raw_weighted_sum
    from raw_scores
    {% if is_incremental() %}
    union all
    select account_id, as_of_date, raw_weighted_sum
    from {{ this }}
    where as_of_date < (select min(as_of_date) from dates)
    {% endif %}
),

scored as (
    select
        r.*,
        p30.raw_weighted_sum                                                                                    as prior_raw_30d,
        case when p30.raw_weighted_sum is null then 0
             else least(8, greatest(-8, (r.raw_weighted_sum - p30.raw_weighted_sum) * 0.25)) end                 as trend_adjustment_calc
    from raw_scores r
    left join prior_rows p30 on p30.account_id = r.account_id and p30.as_of_date = {{ dbt.dateadd('day', -30, 'r.as_of_date') }}
),

final as (
    select
        account_id,
        account_name,
        segment,
        csm_owner_id,
        as_of_date,
        arr,
        seats_purchased,
        days_to_renewal,
        payment_days_past_due,
        contraction_flag_90d,

        -- raw inputs (for Customer 360 export and explainability)
        dau_mau_30d, mau_30d, active_users_30d, feature_depth_30d, feature_breadth_30d,
        seat_utilization, seat_utilization_90d_ago,
        seat_utilization - seat_utilization_90d_ago                     as utilization_drift_90d,
        days_since_last_login, engaged_contacts_90d, multithreading_depth, exec_sponsor_engaged_180d,
        days_since_last_csm_touch, champion_status, replacement_identified,
        open_p1_p2, oldest_open_p1_age_days, tickets_per_100_seats_30d, avg_csat_90d, median_first_response_hours_90d,
        latest_nps, latest_nps_at, nps_trend, transcript_sentiment_30d,

        -- components
        c_adoption, c_engagement, c_support, c_sentiment, c_relationship, c_commercial,
        contrib_adoption, contrib_engagement, contrib_support, contrib_sentiment, contrib_relationship, contrib_commercial,
        raw_weighted_sum,
        health_coverage,
        support_observed,
        usage_observed,
        prior_raw_30d                                                     as raw_weighted_sum_30d_ago,
        coalesce(trend_adjustment_calc, 0)                               as trend_adjustment,

        -- overrides (caps)
        champion_status = 'departed' and not replacement_identified      as ovr_champion_departed,
        coalesce(payment_days_past_due, 0) > 60                           as ovr_payment_past_due,
        coalesce(oldest_open_p1_age_days, 0) > 5                          as ovr_open_p1_aged,
        seat_utilization < 0.20 and seat_utilization_90d_ago < 0.20 and arr > 50000 as ovr_utilization_under_20,

        -- final score
        least(
            least(100, greatest(0, raw_weighted_sum + coalesce(trend_adjustment_calc, 0))),
            case when champion_status = 'departed' and not replacement_identified then 60 else 100 end,
            case when coalesce(payment_days_past_due, 0) > 60 then 50 else 100 end,
            case when coalesce(oldest_open_p1_age_days, 0) > 5 then 65 else 100 end,
            case when seat_utilization < 0.20 and seat_utilization_90d_ago < 0.20 and arr > 50000 then 55 else 100 end
        )                                                                 as health_score
    from scored
),

-- Final scores from this run plus, on incremental runs, the stored history: the 30- and 90-day
-- lookbacks always read a final (capped) score, whichever way the table was built.
history as (
    select account_id, as_of_date, health_score
    from final
    {% if is_incremental() %}
    union all
    select account_id, as_of_date, health_score
    from {{ this }}
    where as_of_date < (select min(as_of_date) from dates)
    {% endif %}
)

select
    f.*,
    h30.health_score                                                  as health_score_30d_ago,
    h90.health_score                                                  as health_score_90d_ago,
    case when f.health_coverage < 0.60 then 'insufficient_data'
         when f.health_score >= 75 then 'green' when f.health_score >= 50 then 'yellow' else 'red' end as health_band,
    case when h30.health_score >= 75 then 'green' when h30.health_score >= 50 then 'yellow' when h30.health_score is not null then 'red' end as health_band_30d_ago,
    current_timestamp as computed_at
from final f
left join history h30 on h30.account_id = f.account_id and h30.as_of_date = {{ dbt.dateadd('day', -30, 'f.as_of_date') }}
left join history h90 on h90.account_id = f.account_id and h90.as_of_date = {{ dbt.dateadd('day', -90, 'f.as_of_date') }}
