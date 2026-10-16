select
    cast(company_id as varchar)         as account_id,
    lower(cast(user_email as varchar))  as user_email,
    cast(feature_key as varchar)        as feature_key,
    coalesce(cast(is_core_feature as boolean), false) as is_core_feature,
    cast(event_at as date)              as event_at
from {{ source('raw', 'product_feature_events') }}
