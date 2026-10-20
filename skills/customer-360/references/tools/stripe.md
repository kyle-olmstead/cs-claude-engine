# Stripe

**Category:** `~~billing` · **Claude connector:** Stripe · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Stripe supplies the commercial facts the engine scores: ARR now and 90 days ago, term dates, seats, tier and modules, payment status, and contraction. These feed the commercial component of the health score, the renewal window, and seat utilization.

## What the connector exposes

The Stripe connector is a general gateway to the Stripe API. The engine uses only these read tools:

- `list_available_accounts_or_orgs`: lists the connected Stripe accounts with their `stripe_context` and `livemode`. Every other call needs both values. This tool appears in the connector's own tool schema; Stripe's MCP docs table names `get_stripe_account_info` instead, so confirm which one answers in setup.
- `stripe_api_search`: finds the operation id for a read, such as "list subscriptions". Look the id up each time; do not hardcode it.
- `stripe_api_details`: shows an operation's parameters, including optional ones like `status`, `expand[]` and date filters.
- `stripe_api_read`: runs any Stripe `GET`. The engine reads customers, subscriptions, subscription items, subscription schedules, invoices, invoice line items, prices, products, coupons and discounts. Money comes back in the smallest currency unit.
- `search_stripe_documentation`: optional, to check a field when a response looks different from this map.
- `stripe_analytics`: optional. It runs Sigma SQL and metric templates such as MRR and churn. It is in preview and SQL needs Sigma, so the engine never depends on it.

The engine never calls `stripe_api_write` (every `POST`, `PATCH`, `PUT` and `DELETE`, including "create a preview invoice"), the Treasury money tools `convert_currency`, `send_money`, `transfer_money` and `setup_recipient`, `atlas_company_formation`, or `stripe_implementation_planner`. **The engine never writes to Stripe.** It reads billing for ARR, seats, term and payment status only. It never computes prices, discounts or pricing advice, and no playbook proposes a billing change.

Stripe has no contract object, no CRM account id, and no committed-units field. Commit units for consumption deals stay with the CRM. Monthly self-serve subscriptions have no renewal date in the contract sense; see the term rows below.

## Matching records to the CRM account

A Stripe customer is tied to the CRM company in this order:

1. **CRM property holding the Stripe customer id** (`cus_...`). Setup names the property. Retrieve each customer directly. This is the strongest link.
2. **Stripe customer `metadata` key holding the CRM company id.** Setup names the key. Find it with customer search, `metadata["<key>"]:"<crm id>"`. Customer search is not in Stripe's list of supported MCP methods, though `stripe_api_read` accepts any `GET`; confirm it answers in setup.
3. **Email domain.** Search `email~"@<domain>"` (substring match, at least 3 characters) for the CRM company's primary domain, or list customers with `email` (exact and case-sensitive) for each known contact. Accept a match only when every returned customer shares the domain and no other CRM company claims that domain. Never match on a free-mail domain such as gmail.com.
4. **Name.** Never auto-match on `name`. Show the candidates and let the user confirm once.

When several Stripe customers belong to one CRM company, sum them and list every customer id in the evidence. When nothing matches, do not guess: fill the contract block from the CRM fallback in `field-sources.md` and flag `billing_account_unmatched`. Use the live account only (`livemode: true`); never mix sandbox data into a Customer 360.

## Setup check

1. Call `list_available_accounts_or_orgs`. Pick the live account and record its `stripe_context` in the stack profile (an account id, not a secret).
2. For one customer the user names, list subscriptions with `customer` and `status=all`, `limit=3`.
3. List that customer's invoices with `status=open`.

A pass is: step 2 returns `items.data[].current_period_end` and `items.data[].price.recurring.interval`, and step 3 answers (an empty list is fine). Record one of these status lines:

- `connected (mapped; confirmed)`
- `connected (mapped; sandbox only)` when no live account is granted. The engine then skips Stripe for scoring.
- `connected (mapped; subscription-level periods)` when `current_period_end` comes back on the subscription and not on the items. The account is on an API version older than 2025-03-31; read the period from the subscription instead.
- `connected (mapped; no CRM link key)` when neither a CRM property nor a metadata key exists. Matching falls to email domain.

## Field map

| Customer 360 field | Source in Stripe | How to derive | If unavailable |
|---|---|---|---|
| `contract.arr` | `Subscription.status`, `Subscription.items.data[].price.unit_amount`, `.quantity`, `.price.recurring.interval`, `.price.recurring.interval_count`, `.price.recurring.usage_type`, `.price.billing_scheme` | Take subscriptions with `status` `active`, `past_due` or `unpaid`. For each recurring item with `usage_type` `licensed` and `billing_scheme` `per_unit`, line = `unit_amount` x `quantity`. Annualize with the interval table below. For `tiered` prices (`unit_amount` is null), use that item's latest non-proration line `amount` on a paid invoice, annualized by the line `period`. Subtract discounts per the coupon table. Leave out metered items, one-time prices and tax. Convert from minor units. Sum across all matched customers. | `billing_account_unmatched` (use the CRM ARR) |
| `contract.arr_90d_ago` | `Subscription Schedule.phases[].start_date`, `.end_date`, `.items[].price`, `.items[].quantity`; `Invoice Line Item.period.start`, `.period.end`, `.amount`, `.discount_amounts`, `.parent.subscription_item_details.proration` | Let D = today minus 90 days. If the subscription has a `schedule` and a phase still covers D, price that phase's items as above. Otherwise list the customer's invoices and take the non-proration subscription lines whose `period` covers D; annualize (`amount` minus `discount_amounts`) by the period length. Include subscriptions that are now `canceled` (list with `status=all`). A subscription started after D adds 0. Events only go back 30 days, so do not use them. | `arr_history_missing` (null) |
| `contract.currency` | `Subscription.currency` | Upper-case the ISO code. If matched subscriptions use more than one currency, report the currency with the largest ARR, sum only that currency, and list the rest in the evidence. Never call `convert_currency`. | `arr_multi_currency` |
| `contract.term_start` | `Subscription Schedule.phases[].start_date`; `Subscription.items.data[].current_period_start`; `Subscription.start_date` | With a schedule: the first phase `start_date`. Yearly or longer items: the base item's `current_period_start`. Monthly or shorter with no schedule: Stripe has no contract term, so use the CRM contract start; if none, use the latest anniversary of `start_date`. | `term_dates_assumed` |
| `contract.term_end` | `Subscription Schedule.phases[].end_date`; `Subscription.items.data[].current_period_end`; `Subscription.cancel_at` | With a schedule: the last phase `end_date`. Yearly or longer items: the base item's `current_period_end`. Monthly or shorter with no schedule: the CRM renewal date, else the next anniversary of `start_date`, so a monthly plan does not sit in the renewal window forever. If `cancel_at` is earlier, use it. | `term_dates_assumed` (today + 365) |
| `contract.term_months` | `Price.recurring.interval`, `Price.recurring.interval_count`; `Subscription Schedule.phases[]` | Months between `term_start` and `term_end`, rounded. A yearly price with `interval_count` 1 gives 12. | none |
| `contract.auto_renew` | `Subscription.cancel_at_period_end`, `Subscription.cancel_at`, `Subscription Schedule.end_behavior` | False when `cancel_at_period_end` is true, `cancel_at` is set, or the schedule `end_behavior` is `cancel`. True otherwise. | none |
| `contract.seats_purchased` | `Subscription.items.data[].quantity`, `Price.billing_scheme` | The quantity of the seat item. Setup names the seat price or product; the default is the base item when its price is `per_unit`. A flat item with quantity 1 is not a seat count. Sum across matched subscriptions. | `seats_purchased_unknown` (set 0) |
| `contract.tier` | `Product.name` via `Price.product` | The product setup marks as a tier. Without a mark, the product of the highest-ARR licensed item. | none |
| `contract.modules_owned` | `Product.name` via `Price.product` | Every other recurring licensed item's product name, without duplicates. | none |
| `contract.payment_days_past_due` | `Invoice.status`, `Invoice.amount_remaining`, `Invoice.due_date`, `Invoice.collection_method`, `Invoice.status_transitions.finalized_at`, `Invoice.attempt_count` | Over invoices with `status` `open` or `uncollectible` and `amount_remaining` above 0: for `send_invoice`, today minus `due_date`; for `charge_automatically` (no `due_date`), today minus `status_transitions.finalized_at` once `attempt_count` is at least 1. Take the maximum, floored at 0. | `payment_status_unknown` (set 0) |
| `contract.contraction_flag_90d` | derived from the two ARR rows and `Subscription.items.data[].quantity` | True when ARR fell from `arr_90d_ago`, or the seat quantity is lower than the quantity on the phase or invoice line that covered D. | `contraction_history_unknown` (set false) |
| `contract.contraction_detail` | `Subscription.items.data[]`, `Invoice Line Item.quantity` | One plain line: which item dropped, from what quantity or amount to what, and the dates. | `contraction_history_unknown` (null) |
| `contract.arr_change_reason` | `Subscription Schedule.phases[]`, `Price.unit_amount` | `contract_ramp` when the change matches a planned phase transition in the schedule. `price_change` when quantity held but the unit amount changed. `expansion` or `contraction` otherwise. Stripe gives no `fx` signal here. | none (null) |
| `contract.consumed_units_run_rate_monthly` | `Invoice Line Item.quantity` on lines whose `Price.recurring.usage_type` is `metered` | Mean monthly quantity over the last three paid invoices. Null for seat-based accounts. | none (null) |

## Vocabulary

**Subscription status to ARR treatment**

| Stripe `status` | Counts in `contract.arr` | Note |
|---|---|---|
| `active` | yes | |
| `past_due` | yes | Stripe counts it in MRR too. Payment rows pick up the risk. |
| `unpaid` | yes | Stripe treats it as churn. The engine keeps it in ARR so a dunning account is not read as churned; `payment_days_past_due` carries the signal. |
| `trialing` | no | If only trialing subscriptions exist, ARR is 0; flag `billing_trial_only` so the stage is not read as churned. |
| `paused` | no | Only reached when a trial ends without a payment method. Pausing collection is different and leaves `status` unchanged. |
| `incomplete`, `incomplete_expired` | no | First payment never succeeded. |
| `canceled` | no | Used only for the 90-day-ago value. |

**Interval to annual multiplier** (from `price.recurring`)

| `interval` | Multiplier |
|---|---|
| `day` | 365 / `interval_count` |
| `week` | 52 / `interval_count` |
| `month` | 12 / `interval_count` |
| `year` | 1 / `interval_count` |

**Coupon duration to ARR treatment** (from the discount's `source.coupon`)

| `duration` | Treatment |
|---|---|
| `forever` | Subtract. Stripe always subtracts permanent discounts from MRR. |
| `repeating` | Subtract while the discount `end` is in the future. |
| `once` | Ignore. |

`percent_off` reduces the item or subscription amount. `amount_off` is taken off each invoice, so annualize it with the subscription's billing interval.

**Invoice status to payment state**

| `status` | Meaning for the engine |
|---|---|
| `draft` | Not issued. Ignore. |
| `open` | Issued and unpaid. Counts toward days past due once due. |
| `paid` | Settled. |
| `uncollectible` | Written off but still unpaid. Counts toward days past due. |
| `void` | Ignore. |

## Limits and gotchas

- **API shape changed in 2025.** Since API version `2025-03-31.basil`, `current_period_start` and `current_period_end` live on each subscription item, not on the subscription. Since `2025-07-30.basil`, one subscription can mix intervals (for example an annual fee and a monthly usage fee), so read each item's own interval. Stripe's docs already cite a `2026-09-30.endive` version; setup confirms the shape the connector returns.
- **Minor units.** Divide by 100 for two-decimal currencies. Zero-decimal currencies such as JPY and KRW are not divided. ISK and UGX are written as two-decimal values even though they are zero-decimal in practice.
- **Engine ARR is not Stripe MRR x 12.** Stripe's MRR counts `active` and `past_due`, drops a subscription the moment `cancel_at_period_end` is set, and excludes `unpaid`, trials, metered usage and tax. The engine keeps `unpaid` and scheduled-to-cancel subscriptions in ARR until the term ends, and sets `auto_renew: false` instead. Expect the engine's number to be higher than the Billing dashboard for accounts in dunning or cancellation.
- **Canceled subscriptions are hidden by default.** List subscriptions returns only non-canceled ones unless you pass `status=all` or `status=canceled`.
- **No history beyond 30 days in events.** Use schedules and invoice lines for the 90-day value.
- **Rate limits.** 100 requests per second per account in live mode, 25 per endpoint, 20 for search. Stripe also caps reads at an average of 500 per transaction over 30 days, with a floor of 10,000 reads a month. A daily review of 40 accounts at about 8 reads each is about 9,600 reads a month, so a low-volume Stripe account can reach the floor. Use `expand[]` on list calls, read each customer once per run, and run calls one at a time (list calls with expansions count against the concurrency limit).
- **Search lags.** Search data can be up to a minute behind, longer during an incident, and search is not available to businesses in India. List calls do not lag.
- **Test clocks.** List-all calls omit test-clock objects. This only matters in sandboxes.
- **`Customer.delinquent` is noisy.** It flips on any invoice event and stays true after dunning write-offs. Use invoices instead.
- **Timestamps** are Unix seconds in UTC. Convert to dates in UTC.
- **Access.** The Claude connector uses OAuth. Stripe lets the user grant access per account and per environment with different permissions; grant read-only access to live mode where the consent screen allows. Stripe MCP stops accepting full-access secret keys and untagged restricted keys after November 30, 2026, which affects only key-based setups.
- **Human confirmation** on some Stripe writes exists, but the engine does not rely on it because it never calls a write tool.

## Sources

- Stripe MCP server (tools, auth, confirmations, supported methods): https://docs.stripe.com/mcp
- Stripe connector in Claude's directory: https://claude.com/connectors/stripe
- Subscription object: https://docs.stripe.com/api/subscriptions/object
- List subscriptions: https://docs.stripe.com/api/subscriptions/list
- Subscription item object: https://docs.stripe.com/api/subscription_items/object
- Price object: https://docs.stripe.com/api/prices/object
- Subscription schedule object: https://docs.stripe.com/api/subscription_schedules/object
- Invoice object: https://docs.stripe.com/api/invoices/object
- List invoices: https://docs.stripe.com/api/invoices/list
- Invoice line item object: https://docs.stripe.com/api/invoice-line-item/object
- Customer object: https://docs.stripe.com/api/customers/object
- List customers: https://docs.stripe.com/api/customers/list
- Search customers: https://docs.stripe.com/api/customers/search
- Search query language: https://docs.stripe.com/search
- Coupon object: https://docs.stripe.com/api/coupons/object
- Discount object: https://docs.stripe.com/api/discounts/object
- List events (30-day window): https://docs.stripe.com/api/events/list
- Item-level billing periods (2025-03-31.basil): https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end
- Mixed intervals (2025-07-30.basil): https://docs.stripe.com/changelog/basil/2025-07-30/support-mixed-intervals
- Billing analytics and MRR definition: https://docs.stripe.com/billing/subscriptions/analytics
- MRR and ARR support article: https://support.stripe.com/questions/understanding-monthly-recurring-revenue-(mrr)-and-annual-recurring-revenue-(arr)
- Rate limits and read allocations: https://docs.stripe.com/rate-limits
- Currencies and minor units: https://docs.stripe.com/currencies
