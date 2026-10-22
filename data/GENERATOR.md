# Synthetic data generator

`python -m salesreport generate` writes seeded, fully synthetic inputs (default seed 42).
Re-running with the same seed produces identical data. Nothing in here comes from a real
system; names are drawn from neutral word lists and every phone number uses the fake
prefix `+999`.

## What is generated

| Item | Default |
|---|---|
| Period | 01.07.2026 - 30.09.2026 (92 days) |
| Regions | North, South, East, West |
| Shops | 30 (`SH01`..`SH30`), each with 1-2 sales-point codes (`SP101`, `SP101K`) |
| Agents | 200 (`agent_001`..`agent_200`): 171 in shops, 14 telesales, 9 partner, 3 system, 3 other |
| Other channel sales points | `TS-01/02` telesales, `PC-01..03` partner, `SYS-SELF` / `SYS-BATCH` system, `EVT-01` (unknown prefix -> "other") |
| Renewals | ~19,500 over the period (~5,800 per month) |

Output layout:

```
data/
  master/shops.xlsx, master/agents.xlsx
  daily/<Month>/<DD.MM.YYYY>/<source>_<DD.MM.YYYY>.xlsx   (6 sources per day)
  manual_count/manual_count_01.09.2026-07.09.2026.xlsx
```

All of `data/` except this file is gitignored (about 6 MB); regenerate it any time.

## Injected mess (and which rule handles it)

| Mess | Where | Handled by |
|---|---|---|
| Title rows (1-3) above the header | ~25 % of files | header auto-detection |
| Data on a second sheet after an "Info" sheet | ~10 % of files | sheet auto-detection |
| Upper-case headers | ~10 % of files | header normalisation |
| Footer "Rows exported: N" after 6 blank rows | ~15 % of files | stop after a blank run |
| Contract-type spellings: `Renewal_Only`, `RENEWAL ONLY`, double spaces, non-breaking space, a full-width letter | store / self-service | text normalisation (NFKC, case-fold) |
| Status spellings: `ACTIVE `, `signed` | store / self-service | text normalisation |
| Sales point in lower case with spaces, login in upper case | ~5 % of rows | code normalisation |
| Phone formats: `+999 70 123 4567`, `+99970...`, Excel float `99970....0`, `999-70-...`, `+999 (70) ...` | per source | phone normalisation |
| Duplicate contract rows | ~3 % of store renewals | rule 1 |
| Retried express journeys (duplicate rows) | ~8 % of express rows | rule 1 |
| Same sale in two sources (express + click & collect, store + self-service) | throughout | rules 3 and 5 |
| Click & collect orders that also appear as store contracts | ~10 % of shop renewals | rule 3 (flag, not add) |
| Express journey started by a different agent (often the shop's "floor host") | ~30 % of journeys | rule 4 |
| Web orders followed by the contract 1-3 days later | ~3 % of renewals | rule 7 |
| Web orders placed before the month, renewal in the month | at each month start | rule 7 (before-period count) |
| Late bookings: contract appears in the export 1-2 days later | ~2 % of store contracts | rule 8 |
| Cancelled / pending renewal contracts (some with an express journey) | per shop | rules 2 and 6b |
| Non-renewal contracts: activation, porting, add-on (some with digital journeys) | per shop | rules 2, 6a, 6b |
| Excluded add-ons bought digitally (`Data Booster 10GB`, `Roaming Week Pass`) | per shop | rule 6a |
| Abandoned express journeys, web orders that never convert, uncollected C&C orders | per day | rule 6c |
| Web renewals without any contract record | ~2 per weekday | rule 10 (strict vs full) |
| Self-service activations (not renewals) | ~2 per weekday | rule 6a |
| Agents working in two shops (3 in the same region, 1 across regions) | 4 agents | rule 4 |
| Agents without a display name | 2 agents | control totals |
| Campaign week with 3x volume | 07.09.2026 - 13.09.2026 | v3-vs-v4 regression test |
| A "web fulfilment" shop (SH02) and a "click & collect hub" (SH01) | throughout | makes v3 shop shares exceed 100 % |
| Non-padded file names: `express_flow_3.07.2026`, `store_contracts_5.08.2026`, `click_collect_4.9.2026`, `web_orders_4.09.2026` | 4 files | file-name resolution |
| File names with Cyrillic look-alike letters: `сlick_collect_21.08.2026` (Cyrillic с), `ехpress_flow_15.09.2026` (Cyrillic е, х) | 2 files | file-name resolution |
| Partial re-export: `store_contracts_09.09.2026.xlsx` stops at 60 % of the day, `..._reexport.xlsx` covers 50 %-100 % | 09.09.2026 | override table `config/overrides.csv` + rule 1 |

## Ground truth and the manual count

The generator keeps the truth for every renewal (key, owner, flags). The test suite checks
that the engine reproduces it exactly for a full month, and that every audited digital
transaction gets the reason the generator intended.

For 01.09-07.09.2026 it also writes an *independent manual count* per agent, with two
deliberate human slips (one agent +1 for a duplicate row counted twice, one agent -1 for a
missed late booking). The report's Reconciliation sheet shows all other agents matching
and exactly those two differing.
