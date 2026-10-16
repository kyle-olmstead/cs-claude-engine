select
    cast(id as varchar)                 as subscription_id,
    cast(company_id as varchar)         as account_id,
    cast(product_sku as varchar)        as product_sku,
    cast(seats_purchased as integer)    as seats_purchased,
    cast(mrr as double)                 as mrr,
    cast(term_start as date)            as term_start,
    cast(term_end as date)              as term_end,
    lower(cast(status as varchar))      as status
from {{ source('raw', 'billing_subscriptions') }}
