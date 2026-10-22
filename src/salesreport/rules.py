"""Business constants behind the v4 counting rules (LOCKED - see LOCKED_LOGIC.sha256).

Every value here changes the published numbers, which are the team's official source
for renewal and digital-share figures.
That is why this file is part of the hash-locked logic: a change must be reviewed,
re-validated against the reconciliation sheet and re-locked with
``python -m salesreport lock``.
"""

from __future__ import annotations

# --- Sources ---------------------------------------------------------------------------
STORE = "store_contracts"
SELFSERVICE = "selfservice_contracts"
EXPRESS = "express_flow"
CLICK_COLLECT = "click_collect"
WEB = "web_orders"
TARIFF = "tariff_changes"

#: Renewal sources: only these can create a renewal (rule 2, the denominator).
CONTRACT_SOURCES = (STORE, SELFSERVICE)
#: Digital sources: these only flag an existing renewal (rule 3).
DIGITAL_SOURCES = (SELFSERVICE, EXPRESS, CLICK_COLLECT, WEB)
ALL_SOURCES = (STORE, SELFSERVICE, EXPRESS, CLICK_COLLECT, WEB, TARIFF)

# --- Rule 2: what counts as a renewal contract (values are normalised text) -------------
RENEWAL_TYPES = frozenset({"renewal with device", "renewal only"})
QUALIFYING_STATUSES = frozenset({"active", "signed"})

# --- Rule 6a: excluded population from tariff_changes ----------------------------------
#: Activations and number porting are new customers, not renewals.
EXCLUDED_CHANGE_TYPES = frozenset({"activation", "porting"})
ADDON_CHANGE_TYPE = "add on"
#: Add-ons bought through a digital journey that must never look like a renewal.
EXCLUDED_ADDON_PRODUCTS = frozenset({"data booster 10gb", "roaming week pass"})

# --- Rule 6: audit reasons ------------------------------------------------------------
REASON_EXCLUDED = "a_excluded_population"
REASON_NOT_RENEWAL = "b_contract_not_renewal"
REASON_NO_CONTRACT = "c_no_contract_that_day"
REASON_TEXT = {
    REASON_EXCLUDED: "Number is in the excluded population (activation/porting or excluded add-on)",
    REASON_NOT_RENEWAL: "A contract exists that day but it is not a qualifying renewal",
    REASON_NO_CONTRACT: "No contract record for this number that day",
}

# --- Rule 7: web look-ahead -----------------------------------------------------------
LOOKAHEAD_DAYS_DEFAULT = 3
WEB_RENEWAL_ORDER_TYPE = "renewal"

# --- Rule 9: other channels (sales points that are not a retail shop) ------------------
CHANNEL_TELESALES = "telesales"
CHANNEL_PARTNER = "partner/consignment"
CHANNEL_SYSTEM = "background/system"
CHANNEL_OTHER = "other"
CHANNEL_ORDER = (CHANNEL_TELESALES, CHANNEL_PARTNER, CHANNEL_SYSTEM, CHANNEL_OTHER)
CHANNEL_LABELS = {
    CHANNEL_TELESALES: "Telesales",
    CHANNEL_PARTNER: "Partner / consignment",
    CHANNEL_SYSTEM: "Background / system",
    CHANNEL_OTHER: "Other",
}
#: Sales-point code prefix -> channel. Anything unknown falls into "other" so that no
#: sale silently disappears from the grand total.
CHANNEL_PREFIXES = {"TS": CHANNEL_TELESALES, "PC": CHANNEL_PARTNER, "SYS": CHANNEL_SYSTEM}

# --- Rule 10: variant -----------------------------------------------------------------
VARIANT_STRICT = "strict"
VARIANT_FULL = "full"
VARIANTS = (VARIANT_STRICT, VARIANT_FULL)
#: Owner used for web renewals without a contract record in the full variant.
WEB_NO_CONTRACT_AGENT = "webshop"
WEB_NO_CONTRACT_NAME = "Webshop orders without contract record"

NO_DISPLAY_NAME = "(no display name)"
