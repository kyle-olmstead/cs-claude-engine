# Chargebee

**Category:** `~~billing` · **Claude connector:** Chargebee · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Chargebee supplies the commercial facts the engine scores: ARR now and 90 days ago, contract term dates, seats, tier and modules, payment and dunning status, and contraction. These feed the commercial component of the health score, the renewal window, and seat utilization.

## What the connector exposes

The Claude connector is Chargebee's Data Lookup and Knowledge Base servers. Claude's directory lists 45 tools and shows 24 by name. Behavior below comes from Chargebee's Data Lookup MCP page, matched to each tool by its title. The engine uses only these read tools:

- `customer_lookup-retrieve_customer_tool`: one customer by Chargebee id.
- `customer_lookup-fetch_customers_via_email_tool`: customers by email address.
- `customer_lookup-fetch_customers_via_company_tool`: customers by company name. Candidates only.
- `customer_lookup-list_customers_tool`: customers in bulk, with selected fields.
- `subscription_lookup-list_subscriptions_for_customer_tool`: every subscription for one customer.
- `subscription_lookup-retrieve_subscription_tool`: one subscription in full, with `subscription_items`, `discounts` and `contract_term`.
- `subscription_lookup-list_subscriptions_tool`: subscriptions matching filters across the site.
- `invoice_lookup-list_invoices_by_customer_tool`, `invoice_lookup-list_invoices_by_subscription_tool`, `invoice_lookup-list_invoices_tool`, `invoice_lookup-retrieve_invoice_tool`: invoices with status, amounts, line items and dunning details.
- `products_lookup-retrieve_item_price_tool`, `products_lookup-retrieve_item_tool`: the item price and item behind each subscription line (name, type, pricing model, metered).
- `data_lookup-get_filter_conditions_metadata_tool`, `data_lookup-get_response_field_metadata_tool`: the filters and response fields a list lookup accepts. Call these before a filtered list.
- `docs_explanation_agent_as_tool`: optional, answers questions from Chargebee's docs without touching site data.

Named only by a third-party mirror of the directory, so **(unconfirmed)**: `event_lookup-fetch_events_by_customer_id_tool` and `transaction_lookup-list_transactions_by_customer_tool`.

Chargebee's Data Lookup server also documents "Fetch Subscription MRR History by subscription ID", "List Subscription Contract Terms", "List Subscription Ramps" and "Retrieve Subscription with Scheduled Changes". None of these appears in the directory listing seen on 2026-10-20. If a workspace exposes them, setup records it and the map prefers them where noted; otherwise the fallbacks below apply.

The engine never calls `code_generation_agent_as_tool`, any onboarding tool (`generate_...`, `import_...`, `customize_branding_tool`), any export job, or anything that creates or changes data. **The engine never writes to Chargebee.** It reads billing for ARR, seats, term and payment status only. It never computes prices, discounts or pricing advice, and no playbook proposes a billing change.

## Matching records to the CRM account

A Chargebee customer is tied to the CRM company in this order:

1. **CRM field holding the Chargebee customer id.** Chargebee's Salesforce integration writes a "Chargebee customer ID" field on the Account. Its HubSpot integration writes "Chargebee customer ID" on the *contact*, not the company (Chargebee does not create HubSpot companies), so read it from the company's associated contacts and require them to agree. Retrieve with `customer_lookup-retrieve_customer_tool`.
2. **Customer `meta_data` key holding the CRM id.** Setup names the key and checks with `data_lookup-get_filter_conditions_metadata_tool` that it can be filtered; if not, this step is skipped.
3. **Email.** `customer_lookup-fetch_customers_via_email_tool` for the CRM company's known contacts. Accept a customer only when its `email` domain is the company's domain and no other CRM company claims it.
4. **Company name.** `customer_lookup-fetch_customers_via_company_tool` returns candidates only. The user confirms; never auto-accept.

Customers in a Chargebee account hierarchy carry `relationship.parent_id`. Sum child customers into a parent CRM company only when the user confirms the roll-up. When several customers match one CRM company, sum them and list every id in the evidence. When nothing matches, do not guess: fill the contract block from the CRM fallback in `field-sources.md` and flag `billing_account_unmatched`.

## Setup check

1. For one customer the user names, call `subscription_lookup-list_subscriptions_for_customer_tool`.
2. Call `invoice_lookup-list_invoices_by_customer_tool` for the same customer.

A pass is: step 1 returns a subscription with `subscription_items[].item_price_id`, `current_term_end` and `mrr`, and step 2 returns invoices with `status` and `due_date` (an empty list is fine). Ask the admin which MRR setting the site uses (Regular or Flexible) and record it. Record one of these status lines:

- `connected (mapped; confirmed)`
- `connected (mapped; MRR history tool available)` when the Data Lookup MRR history tool is exposed.
- `connected (mapped; Product Catalog 1.0, items not mapped)` when subscriptions carry no `subscription_items`. ARR then comes from `mrr` only, and seats, tier and modules from the CRM.
- `connected (mapped; test site)` when only a test site is connected. The engine then skips Chargebee for scoring.

## Field map

| Customer 360 field | Source in Chargebee | How to derive | If unavailable |
|---|---|---|---|
| `contract.arr` | `Subscription.mrr`, `Subscription.status`; cross-check with `Subscription.subscription_items[].amount`, `.item_type`, `.billing_period`, `.billing_period_unit` and `Item.metered` | Sum `mrr` x 12 over subscriptions with `status` `active` or `non_renewing`, in minor units, converted to major units. Cross-check: for `plan` and `addon` items that are not metered, annualize `amount` with the period table below, minus recurring discounts. Use the item sum when `mrr` is missing or 0 on an active subscription. If both exist and differ by more than 5 percent, keep `mrr` and flag `billing_mrr_mismatch`. | `billing_account_unmatched` (use the CRM ARR) |
| `contract.arr_90d_ago` | `Invoice.recurring`, `Invoice.line_items[].date_from`, `.date_to`, `.amount`, `.discount_amount`, `.entity_type` | Prefer the MRR history tool when setup found it: the record covering today minus 90 days, x 12. Otherwise let D = today minus 90 days, take recurring invoice lines with `entity_type` `plan_item_price` or `addon_item_price` whose `date_from` to `date_to` covers D, and annualize (`amount` minus `discount_amount`) by the line's period length. Include cancelled subscriptions. A subscription whose `started_at` is after D adds 0. | `arr_history_missing` (null) |
| `contract.currency` | `Subscription.currency_code`, `Subscription.exchange_rate`, `Subscription.base_currency_code` | Use the shared `currency_code`. If matched subscriptions use more than one currency, convert each with its own `exchange_rate` into `base_currency_code` and report ARR in the base currency. | `arr_multi_currency` |
| `contract.term_start` | `Subscription.contract_term.contract_start`; `Subscription.current_term_start`; `Subscription.started_at` | An active `contract_term`: its `contract_start`. No contract term and a billing period of 12 months or more: `current_term_start`. Monthly or shorter with no contract term: the CRM contract start, else the latest anniversary of `started_at`. | `term_dates_assumed` |
| `contract.term_end` | `Subscription.contract_term.contract_end`; `Subscription.current_term_end`; `Subscription.cancelled_at` | An active `contract_term`: its `contract_end`. Else `current_term_end` for periods of 12 months or more. Monthly or shorter: the CRM renewal date, else the next anniversary of `started_at`. When `status` is `non_renewing`, `cancelled_at` holds the scheduled cancel date; use it if earlier. | `term_dates_assumed` (today + 365) |
| `contract.term_months` | `Subscription.contract_term.billing_cycle`, `Subscription.billing_period`, `Subscription.billing_period_unit` | Months between `term_start` and `term_end`, rounded. | none |
| `contract.auto_renew` | `Subscription.status`, `Subscription.contract_term.action_at_term_end` | False when `status` is `non_renewing` or `action_at_term_end` is `cancel`. True for `renew`, `evergreen` and `renew_once` (a `renew_once` term renews one more time; note it in the evidence). | none |
| `contract.seats_purchased` | `Subscription.subscription_items[].quantity`, `Item Price.pricing_model` | The quantity on the `plan` item when its `pricing_model` is `per_unit`, `tiered`, `volume` or `stairstep`. A `flat_fee` plan has no seat count. Setup can name a seat add-on instead. Sum across matched subscriptions. | `seats_purchased_unknown` (set 0) |
| `contract.tier` | `Item.name` (or `Item.external_name`) of the `plan` item via `subscription_items[].item_price_id` | Chargebee requires exactly one `plan` item per subscription, so its item name is the tier. | none |
| `contract.modules_owned` | `Item.name` of `subscription_items[]` with `item_type` `addon` | Recurring add-on names, without duplicates. `charge` items are one-time and are left out. | none |
| `contract.payment_days_past_due` | `Invoice.status`, `Invoice.due_date`, `Invoice.amount_due`; fallback `Subscription.due_since` | Over invoices with `status` `payment_due` or `not_paid` and `amount_due` above 0: the maximum of today minus `due_date`, floored at 0. If invoices cannot be read, use today minus `due_since` when `due_invoices_count` is above 0. | `payment_status_unknown` (set 0) |
| `contract.contraction_flag_90d` | derived from the two ARR rows and `Invoice.line_items[].quantity` | True when ARR fell from `arr_90d_ago`, or the plan quantity is lower than on the invoice line that covered D. | `contraction_history_unknown` (set false) |
| `contract.contraction_detail` | `Subscription.subscription_items[]`, `Invoice.line_items[]` | One plain line: which item dropped, from what quantity or amount to what, and the dates. | `contraction_history_unknown` (null) |
| `contract.arr_change_reason` | `Subscription.exchange_rate`; subscription ramps when the ramp tool is exposed | `contract_ramp` when a ramp covers the change. `fx` when ARR moved in the base currency but not in the subscription currency. `price_change` when quantity held but price moved. `expansion` or `contraction` otherwise. | none (null) |
| `contract.consumed_units_run_rate_monthly` | `Invoice.line_items[].quantity` on items where `Item.metered` is true | Mean monthly quantity over the last three invoices. Null for seat-based accounts. | none (null) |

## Vocabulary

**Subscription status to ARR treatment**

| Chargebee `status` | Counts in `contract.arr` | Note |
|---|---|---|
| `active` | yes | |
| `non_renewing` | yes | Cancels at term end. Sets `auto_renew: false`. |
| `in_trial` | no | If only trials exist, ARR is 0; flag `billing_trial_only` so the stage is not read as churned. |
| `future` | no | Not started yet. |
| `paused` | as reported in `mrr` | Will not renew while paused. Mention it in `contraction_detail`. |
| `cancelled` | no | Used only for the 90-day-ago value. |
| `transferred` | no | Moved to another business entity; read the target entity's subscription. |

**Billing period to annual multiplier** (`billing_period` and `billing_period_unit`; item-level values appear only when multi-frequency billing is on)

| `billing_period_unit` | Multiplier |
|---|---|
| `day` | 365 / `billing_period` |
| `week` | 52 / `billing_period` |
| `month` | 12 / `billing_period` |
| `year` | 1 / `billing_period` |

**Discount duration to ARR treatment** (`Subscription.discounts[]`)

| `duration_type` | Treatment |
|---|---|
| `forever` | Subtract. |
| `limited_period` | Subtract while `apply_till` is in the future. |
| `one_time` | Ignore. Chargebee removes it from the list after one use. |

**Invoice status to payment state**

| `status` | Meaning for the engine |
|---|---|
| `paid` | Settled. |
| `posted` | Issued, not yet due. Not past due. |
| `payment_due` | Unpaid and being retried. Counts toward days past due. |
| `not_paid` | Every collection attempt failed. Counts toward days past due. |
| `voided` | Ignore. |
| `pending` | Not yet closed. Ignore. |

`dunning_status` `in_progress` or `exhausted` on an unpaid invoice confirms the payment risk; cite it in the evidence.

## Limits and gotchas

- **What `mrr` means depends on the site.** Regular MRR uses the renewal estimate and leaves out charges, non-recurring add-ons, metered components and one-time coupons. Flexible MRR can include some of these through site toggles. RevenueStory's Total MRR includes recurring plans and add-ons, configured recurring coupons and metered charges, and excludes setup fees, credit adjustments, ad hoc charges and tax. Setup records which setting is on so the 5 percent cross-check is read correctly.
- **`mrr` lags.** Chargebee updates it asynchronously, so it can trail a recent change. The item cross-check catches this.
- **Amounts are in minor units** ("in cents"). Confirm zero-decimal currency handling on the first real account.
- **Product Catalog 1.0 sites** return a plan plus add-ons instead of `subscription_items`. This map covers Product Catalog 2.0 only.
- **Consolidated invoices** have no `Invoice.subscription_id`. Use `line_items[].subscription_id`.
- **Line item fields** `date_from`, `date_to`, `quantity`, `amount` and `discount_amount` appear in Chargebee's invoice sample but are not defined field by field. Confirm them on the first real invoice.
- **Rate limits** are per site per minute: Starter 150, Performance 1,000, Enterprise 3,500 by default, test sites 150. A 40-account book at about 5 calls each is about 200 calls, so on Starter spread a book review over two minutes or more. A limit hit returns HTTP 429.
- **Access.** An admin turns on MCP access under Settings > Configure Chargebee > Agentic AI > MCP Servers and picks the toolsets. With OAuth, tools are limited to what the signed-in user can see. OAuth does not work on sites with Multi-Business Entity enabled; those need an API key. Admins can also constrain tool inputs per tool.
- **Regions.** The connector has separate US, EU and AU endpoints. Connect the one the site lives in.
- **Timestamps** are UTC seconds. Convert to dates in UTC.
- **Event retention** is not stated in the docs opened for this map, so events are not used for the 90-day value.

## Sources

- Chargebee connector in Claude's directory: https://claude.com/connectors/chargebee
- Chargebee MCP servers overview: https://www.chargebee.com/docs/billing/2.0/ai-in-chargebee/chargebee-mcp.md
- Data Lookup MCP server (toolsets, auth, endpoints): https://www.chargebee.com/docs/billing/2.0/ai-in-chargebee/data-lookup-agent
- Third-party mirror of the full 45-tool list (used only for names marked unconfirmed): https://hackceleration.com/resources/integrations/claude/chargebee
- Subscriptions API: https://apidocs.chargebee.com/docs/api/subscriptions
- Subscription object (items, contract term, discounts): https://apidocs.chargebee.com/docs/api/subscriptions/subscription-object.md
- Invoice object: https://apidocs.chargebee.com/docs/api/invoices/invoice-object.md
- Customer object: https://apidocs.chargebee.com/docs/api/customers/customer-object.md
- Item object: https://apidocs.chargebee.com/docs/api/items/item-object.md
- Item price object: https://apidocs.chargebee.com/docs/api/item_prices/item-price-object.md
- Events: https://apidocs.chargebee.com/docs/api/events.md
- Regular vs Flexible MRR: https://www.chargebee.com/docs/billing/2.0/reports-and-analytics/flexi-mrr-vs-regular-mrr
- RevenueStory Total MRR: https://www.chargebee.com/docs/billing/2.0/kb/reports-and-analytics/how-is-total-mrr-metric-in-revenuestory-calculated
- API limits: https://www.chargebee.com/docs/billing/2.0/kb/platform/what-are-the-chargebee-api-limits
- HubSpot integration: https://www.chargebee.com/docs/billing/2.0/integrations/hubspot
- Salesforce integration: https://www.chargebee.com/docs/billing/2.0/integrations/salesforce-integration-guide
