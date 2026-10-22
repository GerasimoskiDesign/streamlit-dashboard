# Counting rules (v4, locked)

These are the rules the production engine (`src/salesreport/engine/v4.py`) implements.
Each rule lists **what** it does and **why** it exists. The engine files are hash-locked
(`LOCKED_LOGIC.sha256`): changing any rule means review, re-validation against the
reconciliation sheet, and `python -m salesreport lock`.

## Sources

| Source | Role | What it is |
|---|---|---|
| `store_contracts` | denominator | Contracts signed in a shop. |
| `selfservice_contracts` | denominator + digital flag | Contracts closed through the self-service channel. Inherently digital. |
| `express_flow` | digital flag | A one-minute express digital journey that flags a renewal. |
| `click_collect` | digital flag | Online order, collected in a shop. |
| `web_orders` | digital flag | Webshop orders (same day, or linked by look-ahead, rule 7). |
| `tariff_changes` | exclusion list | Separate daily export, used for the excluded population (rule 6a). |

## Rule 1 - One row = one renewal

**What.** The key is `(date, phone number)`. Several rows for the same key in the same
source collapse into one. The number of collapsed rows is reported per source on the
Control totals sheet.

**Why.** Exports contain duplicates: a contract exported twice, an express journey that
was retried, a partial re-export that overlaps the first file. Counting rows instead of
events inflates both sides of the share and, worse, inflates them differently per
source. The collapsed-row count makes the clean-up visible instead of silent.

## Rule 2 - The denominator

**What.** A renewal exists only if `store_contracts` or `selfservice_contracts` has a
qualifying contract for the key: status in {active, signed} and type in
{renewal with device, renewal only}. Total renewals = store + self-service. A key in both
sources is one renewal (owned by the store contract, with a self-service flag).

**Why.** Only a signed renewal contract is a renewal. Cancelled or pending contracts,
activations, porting and add-ons happen in the same systems and look similar in an
export, but they are not what the team is measured on. Values are compared after
normalisation, so `Renewal_Only` and `renewal only` are the same type.

## Rule 3 - Digital sources only flag, never add

**What.** `selfservice`, `express_flow`, `click_collect` (and `web_orders`, rule 7) mark an
*existing* renewal as digital. They never create a renewal.

**Why.** If a digital source could add to the numerator without a matching renewal in the
denominator, digital share could exceed 100 %. With flags, digital <= total holds by
construction, at every level (agent, shop, region, network, any day).

## Rule 4 - Same owner for numerator and denominator

**What.** A renewal belongs to the agent and the sales point *on the contract*. Digital
flags inherit that owner; the agent field of an express journey is ignored for
attribution. An agent who worked in two shops appears under both, each with their own
events.

**Why.** When the digital count is attributed by each source's own agent/shop field, the
agent rows stop adding up to the shop row and an agent who only *started* journeys for
colleagues can show more digital renewals than renewals. One owner per event makes
"sum of agent rows = shop row" an identity.

## Rule 5 - Digital renewals and the C&C split

**What.** Digital renewals = renewals with at least one digital flag. This is <= the sum of
the individual flag columns, because one renewal can carry several flags. The report also
shows **C&C only** (digital only through click & collect) and **digital share excl. C&C**.

**Why.** Click & collect is a weaker digital signal (the customer still came to the shop),
so the business wants to see the share with and without it. Counting renewals, not flags,
is what keeps the share honest.

## Rule 6 - Unmatched digital transactions are audited, not dropped

**What.** Every digital transaction without a matching renewal goes to the
*Unmatched digital* sheet with one reason, checked in this order:

| Code | Reason |
|---|---|
| `a_excluded_population` | The number is in the excluded population that day: an activation or porting in `tariff_changes`, or an add-on from the excluded product list. |
| `b_contract_not_renewal` | A contract exists that day, but it is not a qualifying renewal (wrong type or status). |
| `c_no_contract_that_day` | No contract record for the number that day. |

Web orders inside the look-ahead window are marked `window still open`.

**Why.** Silent drops are where trust in a report dies. When a shop manager asks "why
doesn't my express journey count?", the audit row answers it, and the reason mix is a
data-quality signal in its own right (a jump in reason c usually means a late or missing
export).

## Rule 7 - Web order look-ahead

**What.** A web order with no renewal on its own day is linked to a renewal for the same
number booked up to **N days later** (default 3, `--lookahead`), if that later day has no
web order of its own. The earliest such renewal wins. The renewal counts as digital in
the month of the contract. Links from orders placed *before* the reporting period are
counted separately on the Control totals and Web look-ahead links sheets.

**Why.** Customers order online and sign the renewal contract in a shop a day or two
later. Without look-ahead those renewals are reported as non-digital and the web orders
as unmatched. The "no own web order" condition stops one order from claiming a renewal
that already has a same-day order, and the before-period count shows how much the month
depends on the previous month's orders.

## Rule 8 - Month to date, always from day 1

**What.** Every run recomputes day 1 up to the chosen day. Nothing is carried over from
an earlier run.

**Why.** Late bookings arrive in a later day's export, and look-ahead links change earlier
days. An incremental "add today to yesterday's totals" approach would freeze yesterday's
mistakes. Rebuilding is cheap; a wrong running total is not.

## Rule 9 - Other channels

**What.** Sales whose sales point is not a retail shop are grouped into **telesales**,
**partner / consignment**, **background / system**, and **other** (anything unknown), each
with their own agent rows, in an "Other channels" section below the shops.

**Why.** These renewals are real and belong in the grand total, but they must not distort
shop rankings. Unknown sales points go to "other" instead of disappearing, so the grand
total always equals all renewals.

## Rule 10 - Variant: strict vs full

**What.** `--variant strict` (default) excludes web renewals that have no contract record
at all (they stay in the audit, reason c). `--variant full` adds them as renewals on
*both* sides (numerator and denominator) under Other channels -> Other ->
`webshop`.

**Why / trade-off.** Strict is conservative: every counted renewal has a contract that can
be checked, which is what an official source needs. Full is closer to customer reality
when a back-office system books web renewals without a contract export, but those
renewals have no shop or agent owner and cannot be verified the same way. Both variants
keep digital <= total because the additions are symmetric. The Control totals sheet shows
how many renewals the choice affects.
