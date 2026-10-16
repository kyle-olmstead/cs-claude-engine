select
    cast(id as varchar)                 as call_id,
    cast(company_id as varchar)         as account_id,
    cast(occurred_at as date)           as occurred_at,
    cast(duration_sec as integer)       as duration_sec,
    cast(transcript_uri as varchar)     as transcript_uri,
    cast(participants_json as varchar)  as participants_json
from {{ source('raw', 'conversation_calls') }}
