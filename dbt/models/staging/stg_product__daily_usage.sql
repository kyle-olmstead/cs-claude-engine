select
    cast(company_id as varchar)         as account_id,
    lower(cast(user_email as varchar))  as user_email,
    cast(usage_date as date)            as usage_date,
    cast(sessions as integer)           as sessions,
    cast(events as integer)             as events,
    cast(minutes_active as double)      as minutes_active
from {{ source('raw', 'product_daily_usage') }}
