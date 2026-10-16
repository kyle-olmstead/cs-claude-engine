select
    cast(call_id as varchar)            as call_id,
    cast(company_id as varchar)         as account_id,
    cast(occurred_at as date)           as occurred_at,
    cast(sentiment as double)           as sentiment
from {{ source('raw', 'transcript_sentiment') }}
