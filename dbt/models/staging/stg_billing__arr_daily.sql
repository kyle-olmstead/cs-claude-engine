select
    cast(company_id as varchar)         as account_id,
    cast(snapshot_date as date)         as snapshot_date,
    cast(arr as double)                 as arr,
    cast(seats_purchased as integer)    as seats_purchased,
    cast(term_start as date)            as term_start,
    cast(term_end as date)              as term_end,
    coalesce(cast(payment_days_past_due as integer), 0) as payment_days_past_due,
    cast(arr_change_reason as varchar)  as arr_change_reason
from {{ source('raw', 'billing_arr_daily') }}
