select
    cast(id as varchar)                 as response_id,
    cast(company_id as varchar)         as account_id,
    cast(contact_id as varchar)         as contact_id,
    lower(cast(survey_type as varchar)) as survey_type,
    cast(score as integer)              as score,
    cast(verbatim as varchar)           as verbatim,
    cast(responded_at as date)          as responded_at
from {{ source('raw', 'survey_responses') }}
