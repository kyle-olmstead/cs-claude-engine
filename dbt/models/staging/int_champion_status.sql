{#-
    One row per account: the designated champion and their status.
      departed: CRM says they left, or enrichment shows a different employer
      at_risk:  no activity in 60 days
      active:   otherwise
      none:     no champion flagged
    replacement_identified: a second contact flagged champion who is still at the company.
-#}
with champions as (
    select
        c.*,
        row_number() over (partition by c.account_id order by (c.left_company_at is null) desc, c.contact_id) as rn
    from {{ ref('stg_crm__contacts') }} c
    join {{ ref('stg_crm__accounts') }} a on a.account_id = c.account_id
    where c.is_champion
),
primary_champion as (
    select * from champions where rn = 1
),
last_engaged as (
    select contact_id, max(occurred_at) as last_engaged_at
    from {{ ref('stg_crm__activities') }}
    group by 1
),
accounts as (
    select account_id, account_name from {{ ref('stg_crm__accounts') }}
)
select
    acc.account_id,
    pc.contact_id as champion_contact_id,
    case
        when pc.contact_id is null then 'none'
        when pc.left_company_at is not null then 'departed'
        when pc.enriched_employer is not null and lower(pc.enriched_employer) <> lower(acc.account_name) then 'departed'
        when le.last_engaged_at is null or {{ dbt.datediff('le.last_engaged_at', 'current_date', 'day') }} > 60 then 'at_risk'
        else 'active'
    end as champion_status,
    le.last_engaged_at as champion_last_engaged_at,
    coalesce((select count(*) from champions c2 where c2.account_id = acc.account_id and c2.rn > 1 and c2.left_company_at is null), 0) > 0 as replacement_identified,
    pc.tenure_months as champion_tenure_months
from accounts acc
left join primary_champion pc on pc.account_id = acc.account_id
left join last_engaged le on le.contact_id = pc.contact_id
