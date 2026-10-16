{#-
    Daily ARR snapshot joined to account attributes, with the 90-days-ago values the health mart
    needs for contraction and utilization drift. One row per account per day with arr > 0.
-#}
with arr as (
    select * from {{ ref('stg_billing__arr_daily') }}
),
joined as (
    select
        a.account_id,
        a.snapshot_date,
        a.arr,
        a.seats_purchased,
        a.term_start,
        a.term_end,
        a.payment_days_past_due,
        a.arr_change_reason,
        acc.segment,
        acc.csm_owner_id,
        p.arr             as arr_90d_ago,
        p.seats_purchased as seats_purchased_90d_ago
    from arr a
    join {{ ref('stg_crm__accounts') }} acc on acc.account_id = a.account_id
    left join arr p
      on p.account_id = a.account_id
     and p.snapshot_date = {{ dbt.dateadd('day', -90, 'a.snapshot_date') }}
)
select * from joined
