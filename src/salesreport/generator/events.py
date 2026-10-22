"""Day-by-day simulation of renewals, digital journeys and noise.

The simulator knows the *truth* - which (date, phone) keys are real renewals, who owns
them and which digital flags they carry - and writes the messy source rows a real
export would contain. Tests compare the engine's output with this truth, so the
generator doubles as the reference implementation of "what really happened".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from salesreport import rules
from salesreport.generator.master import Agent, MasterData, Shop

RENEWAL_WITH_DEVICE = "Renewal with device"
RENEWAL_ONLY = "Renewal only"
TYPE_VARIANTS = {
    RENEWAL_WITH_DEVICE: (
        "Renewal with device", "Renewal_with_Device", "RENEWAL WITH DEVICE",
        "renewal  with device ", "Renewal with device",
    ),
    RENEWAL_ONLY: (
        "Renewal only", "Renewal_Only", "RENEWAL ONLY", "renewal only ", "Renewal only",
        "Ｒenewal only",
    ),
}  # fmt: skip
STATUS_VARIANTS = {
    "Active": ("Active", "active", "ACTIVE ", "Active"),
    "Signed": ("Signed", "signed", "SIGNED"),
}
ADDON_PRODUCTS = ("Data Booster 10GB", "Roaming Week Pass", "Music Pass", "Cloud Storage 50GB")
EXCLUDED_PRODUCTS = {"Data Booster 10GB", "Roaming Week Pass"}

CC_HUB = "SH01"  # flagship shop where many click & collect orders are picked up
WEB_HUB = "SH02"  # shop that fulfils webshop orders


@dataclass(frozen=True)
class GeneratorConfig:
    """All knobs of the synthetic data. Same config + seed = identical files."""

    seed: int = 42
    start: date = date(2026, 7, 1)
    end: date = date(2026, 9, 30)
    n_shops: int = 30
    n_agents: int = 200
    campaign_start: date = date(2026, 9, 7)
    campaign_end: date = date(2026, 9, 13)
    campaign_multiplier: float = 3.0
    reexport_day: date = date(2026, 9, 9)
    lookahead_days: int = rules.LOOKAHEAD_DAYS_DEFAULT
    #: (day, source, file-name prefix) - file-name prefix written with Cyrillic look-alikes
    cyrillic_names: tuple[tuple[date, str, str], ...] = (
        (date(2026, 8, 21), rules.CLICK_COLLECT, "сlick_collect"),
        (date(2026, 9, 15), rules.EXPRESS, "ехpress_flow"),
    )
    #: (day, source, date text) - non-padded day/month in the file name
    unpadded_names: tuple[tuple[date, str, str], ...] = (
        (date(2026, 7, 3), rules.EXPRESS, "3.07.2026"),
        (date(2026, 8, 5), rules.STORE, "5.08.2026"),
        (date(2026, 9, 4), rules.CLICK_COLLECT, "4.9.2026"),
        (date(2026, 9, 4), rules.WEB, "4.09.2026"),
    )
    manual_count_start: date = date(2026, 9, 1)
    manual_count_end: date = date(2026, 9, 7)


@dataclass
class Simulation:
    """Rows per (source, file day) plus the ground truth."""

    rows: dict[tuple[str, date], list[dict]] = field(default_factory=dict)
    truth: list[dict] = field(default_factory=list)
    expected_audit: list[dict] = field(default_factory=list)
    web_no_contract: list[dict] = field(default_factory=list)

    def add(self, source: str, file_day: date, row: dict) -> None:
        self.rows.setdefault((source, file_day), []).append(row)


def phone_digits(index: int) -> str:
    """Unique fake number for customer ``index``: ``999`` + 9 digits (a bijection mod 1e9)."""
    return "999" + f"{(index * 7919 + 12345) % 10**9:09d}"


class Simulator:
    """Generates one day at a time with a single seeded random generator."""

    def __init__(self, cfg: GeneratorConfig, master: MasterData, rng: np.random.Generator):
        self.cfg = cfg
        self.master = master
        self.rng = rng
        self.sim = Simulation()
        self._phone = 0
        self._ids: dict[str, int] = {}
        self.sys_self = next(
            a for a in master.channel_agents("background/system") if a.sales_points == ["SYS-SELF"]
        )
        self.sys_batch = next(
            a for a in master.channel_agents("background/system") if a.sales_points == ["SYS-BATCH"]
        )
        self.pools = {s.shop_id: master.shop_pool(s.shop_id) for s in master.shops}
        self.hosts = {a.home_shop: a for a in master.agents if a.is_host}

    # --- small helpers ---------------------------------------------------------------
    def new_phone(self) -> str:
        self._phone += 1
        return phone_digits(self._phone)

    def next_id(self, prefix: str) -> str:
        self._ids[prefix] = self._ids.get(prefix, 0) + 1
        return f"{prefix}{self._ids[prefix]:07d}"

    def pick(self, options: tuple | list):
        return options[int(self.rng.integers(len(options)))]

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def factor(self, day: date) -> float:
        weekday = day.weekday()
        base = 1.0 if weekday < 5 else (0.7 if weekday == 5 else 0.35)
        if self.cfg.campaign_start <= day <= self.cfg.campaign_end:
            base *= self.cfg.campaign_multiplier
        return base

    def messy_sp(self, code: str) -> str:
        return f" {code.lower()} " if self.chance(0.05) else code

    def messy_login(self, login: str) -> str:
        return login.upper() if self.chance(0.05) else login

    def pick_agent(self, shop: Shop) -> Agent:
        pool, weights = self.pools[shop.shop_id]
        return pool[int(self.rng.choice(len(pool), p=weights))]

    # --- row builders (each source has its own formats, as real exports do) ---------
    def contract_row(
        self, source: str, day: date, phone: str, ctype: str, status: str, sp: str, agent: str
    ) -> dict:
        if source == rules.STORE:
            when: object = datetime(day.year, day.month, day.day)
            msisdn = f"+999 {phone[3:5]} {phone[5:8]} {phone[8:]}"
        else:
            when = day.strftime("%d.%m.%Y")
            msisdn = f"+{phone}"
        ctype_text = self.pick(TYPE_VARIANTS[ctype]) if ctype in TYPE_VARIANTS else ctype
        status_text = self.pick(STATUS_VARIANTS.get(status, (status,)))
        return {
            "Contract Date": when,
            "MSISDN": msisdn,
            "Contract Type": ctype_text,
            "Status": status_text,
            "Sales Point": self.messy_sp(sp),
            "Agent Login": self.messy_login(agent),
            "Contract ID": self.next_id("C"),
        }

    def express_row(self, day: date, phone: str, agent: Agent, sp: str) -> dict:
        minute = int(self.rng.integers(8 * 60, 20 * 60))
        return {
            "Flow ID": self.next_id("X"),
            "Flow Date": f"{day:%d.%m.%Y} {minute // 60:02d}:{minute % 60:02d}",
            "Phone": float(phone),  # stored as a number, read back as 999....0
            "Agent": self.messy_login(agent.login),
            "Sales Point": sp,
            "Step": "completed",
        }

    def cc_row(self, day: date, phone: str, pickup: str) -> dict:
        return {
            "Order ID": self.next_id("CC"),
            "Order Date": day.strftime("%d.%m.%Y"),
            "Phone Number": f"{phone[:3]}-{phone[3:5]}-{phone[5:8]}-{phone[8:]}",
            "Pickup Shop": pickup,
            "Order Status": "collected",
        }

    def web_row(self, day: date, phone: str, order_type: str, sp: str) -> dict:
        minute = int(self.rng.integers(0, 24 * 60))
        return {
            "Order No": self.next_id("W"),
            "Order Date": datetime(day.year, day.month, day.day, minute // 60, minute % 60),
            "Phone": f"+999 ({phone[3:5]}) {phone[5:]}",
            "Order Type": order_type,
            "Sales Point": sp,
            "Channel": "webshop",
        }

    def tariff_row(self, day: date, phone: str, change_type: str, product: str) -> dict:
        return {
            "Change Date": day.isoformat(),
            "MSISDN": phone,
            "Change Type": change_type,
            "Product": product,
        }

    def expect(self, day: date, phone: str, source: str, reason: str) -> None:
        self.sim.expected_audit.append(
            {"date": day, "phone": phone, "source": source, "reason_code": reason}
        )

    # --- a real renewal -----------------------------------------------------------
    def renewal(self, day: date, kind: str, shop: Shop | None, agent: Agent, sp: str) -> None:
        cfg, sim = self.cfg, self.sim
        phone = self.new_phone()
        is_shop = kind == "shop"
        source = rules.SELFSERVICE if is_shop and self.chance(0.15) else rules.STORE
        owner, owner_sp = agent, sp
        if source == rules.SELFSERVICE and self.chance(0.4):
            owner, owner_sp = self.sys_self, "SYS-SELF"
        ctype = RENEWAL_WITH_DEVICE if self.chance(0.55) else RENEWAL_ONLY
        if kind == "batch":
            ctype = RENEWAL_ONLY
        status = "Active" if self.chance(0.7) else "Signed"

        file_day = day
        if source == rules.STORE and self.chance(0.02):
            later = day + timedelta(days=int(self.rng.integers(1, 3)))
            if later.month == day.month and later <= cfg.end:
                file_day = later  # late booking: arrives in a later day's export

        if source == rules.STORE and self.chance(0.005):
            cancelled = self.contract_row(
                source, day, phone, ctype, "Cancelled", owner_sp, owner.login
            )
            sim.add(source, file_day, cancelled)
        row = self.contract_row(source, day, phone, ctype, status, owner_sp, owner.login)
        sim.add(source, file_day, row)
        if source == rules.STORE and self.chance(0.03):
            sim.add(source, file_day, dict(row))  # duplicate export row

        flags = {"ss": source == rules.SELFSERVICE, "express": False, "cc": False, "web": False}
        web_link, web_order_day = "", None

        if source == rules.STORE and is_shop and self.chance(0.04):
            ss = self.contract_row(
                rules.SELFSERVICE, day, phone, ctype, "Signed", "SYS-SELF", self.sys_self.login
            )
            sim.add(rules.SELFSERVICE, day, ss)  # started in self-service, finished in shop
            flags["ss"] = True

        express_p = 0.20 if is_shop else (0.10 if kind == "telesales" else 0.0)
        if self.chance(express_p):
            roll = self.rng.random()
            if shop is None or roll < 0.7:
                helper = agent
            elif roll < 0.95:
                helper = self.hosts[shop.shop_id]
            else:
                helper = self.pick_agent(self.pick(self.master.shops))
            helper_sp = helper.sales_points[0] if helper.home_shop else sp
            express = self.express_row(day, phone, helper, helper_sp)
            sim.add(rules.EXPRESS, day, express)
            if self.chance(0.08):
                sim.add(rules.EXPRESS, day, {**express, "Flow ID": self.next_id("X")})  # retry
            flags["express"] = True

        if is_shop and shop is not None and source == rules.STORE and self.chance(0.10):
            hub = self.master.shop(CC_HUB).sales_points[0]
            pickup = shop.sales_points[0] if self.chance(0.8) else hub
            order = self.cc_row(day, phone, pickup)
            sim.add(rules.CLICK_COLLECT, day, order)
            if self.chance(0.03):
                sim.add(rules.CLICK_COLLECT, day, dict(order))
            flags["cc"] = True

        if kind in ("shop", "telesales"):
            roll = self.rng.random()
            hub_sp = self.master.shop(WEB_HUB).sales_points[0]
            web_sp = hub_sp if self.chance(0.7) else ""
            if roll < 0.04:
                sim.add(rules.WEB, day, self.web_row(day, phone, "Renewal", web_sp))
                flags["web"], web_link = True, "same_day"
            elif roll < 0.07:
                gap = int(self.rng.integers(1, cfg.lookahead_days + 1))
                order_day = day - timedelta(days=gap)
                if order_day >= cfg.start:
                    sim.add(rules.WEB, order_day, self.web_row(order_day, phone, "Renewal", web_sp))
                    flags["web"], web_link, web_order_day = True, "lookahead", order_day

        sim.truth.append(
            {
                "date": day,
                "phone": phone,
                "agent": owner.login,
                "sales_point": owner_sp,
                "contract_source": "store" if source == rules.STORE else "selfservice",
                "contract_file_date": file_day,
                "flag_selfservice": flags["ss"],
                "flag_express": flags["express"],
                "flag_cc": flags["cc"],
                "flag_web": flags["web"],
                "web_link": web_link,
                "web_order_date": web_order_day,
            }
        )

    # --- noise around each shop -------------------------------------------------------
    def shop_noise(self, day: date, shop: Shop, lam: float) -> None:
        sim = self.sim
        for _ in range(self.rng.poisson(lam * 0.25)):  # contracts that are not renewals
            phone, agent = self.new_phone(), self.pick_agent(shop)
            sp = self.pick(shop.sales_points)
            ctype = str(
                self.rng.choice(["New activation", "Number porting", "Add-on"], p=[0.4, 0.25, 0.35])
            )
            sim.add(
                rules.STORE,
                day,
                self.contract_row(rules.STORE, day, phone, ctype, "Active", sp, agent.login),
            )
            if ctype == "New activation":
                excluded, change, product = True, "Activation", "Starter plan"
            elif ctype == "Number porting":
                excluded, change, product = True, "Porting", "Starter plan"
            else:
                product = self.pick(ADDON_PRODUCTS)
                excluded, change = (
                    product in EXCLUDED_PRODUCTS,
                    self.pick(("Add-on", "ADD_ON", "add on")),
                )
            sim.add(rules.TARIFF, day, self.tariff_row(day, phone, change, product))
            reason = rules.REASON_EXCLUDED if excluded else rules.REASON_NOT_RENEWAL
            if self.chance(0.25):
                sim.add(rules.EXPRESS, day, self.express_row(day, phone, agent, sp))
                self.expect(day, phone, rules.EXPRESS, reason)
            if self.chance(0.08):
                sim.add(rules.CLICK_COLLECT, day, self.cc_row(day, phone, shop.sales_points[0]))
                self.expect(day, phone, rules.CLICK_COLLECT, reason)

        for _ in range(self.rng.poisson(lam * 0.04)):  # cancelled / pending renewal contracts
            phone, agent = self.new_phone(), self.pick_agent(shop)
            status = self.pick(("Cancelled", "Pending"))
            ctype = RENEWAL_WITH_DEVICE if self.chance(0.5) else RENEWAL_ONLY
            row = self.contract_row(
                rules.STORE, day, phone, ctype, status, shop.sales_points[0], agent.login
            )
            sim.add(rules.STORE, day, row)
            if self.chance(0.4):
                sim.add(
                    rules.EXPRESS, day, self.express_row(day, phone, agent, shop.sales_points[0])
                )
                self.expect(day, phone, rules.EXPRESS, rules.REASON_NOT_RENEWAL)

        for _ in range(self.rng.poisson(lam * 0.06)):  # abandoned express journeys
            phone = self.new_phone()
            agent = self.hosts[shop.shop_id] if self.chance(0.6) else self.pick_agent(shop)
            sim.add(rules.EXPRESS, day, self.express_row(day, phone, agent, shop.sales_points[0]))
            self.expect(day, phone, rules.EXPRESS, rules.REASON_NO_CONTRACT)

        for _ in range(self.rng.poisson(lam * 0.03)):  # excluded add-on bought digitally
            phone, agent = self.new_phone(), self.pick_agent(shop)
            product = self.pick(sorted(EXCLUDED_PRODUCTS))
            sim.add(rules.TARIFF, day, self.tariff_row(day, phone, "Add-on", product))
            sim.add(rules.EXPRESS, day, self.express_row(day, phone, agent, shop.sales_points[0]))
            self.expect(day, phone, rules.EXPRESS, rules.REASON_EXCLUDED)

    def network_noise(self, day: date, factor: float) -> None:
        sim = self.sim
        hub_sp = self.master.shop(WEB_HUB).sales_points[0]
        for _ in range(self.rng.poisson(6 * factor)):  # web orders that are not renewals
            phone = self.new_phone()
            order_type = self.pick(("Accessory", "New line"))
            sim.add(
                rules.WEB,
                day,
                self.web_row(day, phone, order_type, hub_sp if self.chance(0.5) else ""),
            )
            self.expect(day, phone, rules.WEB, rules.REASON_NO_CONTRACT)
        for _ in range(self.rng.poisson(2 * factor)):  # web renewals without contract record
            phone = self.new_phone()
            sim.add(rules.WEB, day, self.web_row(day, phone, "Renewal", hub_sp))
            self.expect(day, phone, rules.WEB, rules.REASON_NO_CONTRACT)
            sim.web_no_contract.append({"date": day, "phone": phone})
        for _ in range(
            self.rng.poisson(2 * factor)
        ):  # click & collect never turned into a contract
            phone = self.new_phone()
            sim.add(
                rules.CLICK_COLLECT,
                day,
                self.cc_row(day, phone, self.pick(self.master.shops).sales_points[0]),
            )
            self.expect(day, phone, rules.CLICK_COLLECT, rules.REASON_NO_CONTRACT)
        for _ in range(self.rng.poisson(2 * factor)):  # self-service activations (not renewals)
            phone = self.new_phone()
            row = self.contract_row(
                rules.SELFSERVICE,
                day,
                phone,
                "New activation",
                "Active",
                "SYS-SELF",
                self.sys_self.login,
            )
            sim.add(rules.SELFSERVICE, day, row)
            sim.add(rules.TARIFF, day, self.tariff_row(day, phone, "Activation", "Starter plan"))
            self.expect(day, phone, rules.SELFSERVICE, rules.REASON_EXCLUDED)
        for _ in range(self.rng.poisson(8 * factor)):  # unrelated tariff changes
            sim.add(
                rules.TARIFF, day, self.tariff_row(day, self.new_phone(), "Tariff change", "Plan M")
            )

    # --- one day ------------------------------------------------------------------------
    def simulate_day(self, day: date) -> None:
        factor = self.factor(day)
        for shop in self.master.shops:
            for _ in range(self.rng.poisson(shop.lam * factor)):
                agent = self.pick_agent(shop)
                self.renewal(day, "shop", shop, agent, self.pick(shop.sales_points))
            self.shop_noise(day, shop, shop.lam * factor)
        for channel, kind, lam in (
            ("telesales", "telesales", 10.0),
            ("partner/consignment", "partner", 5.0),
            ("other", "other", 1.0),
        ):
            agents = self.master.channel_agents(channel)
            for _ in range(self.rng.poisson(lam * factor)):
                agent = self.pick(agents)
                self.renewal(day, kind, None, agent, agent.sales_points[0])
        for _ in range(self.rng.poisson(2.0 * factor)):
            self.renewal(day, "batch", None, self.sys_batch, "SYS-BATCH")
        self.network_noise(day, factor)

    def run(self) -> Simulation:
        day = self.cfg.start
        while day <= self.cfg.end:
            self.simulate_day(day)
            day += timedelta(days=1)
        return self.sim
