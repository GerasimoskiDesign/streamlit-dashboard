"""Synthetic master data: regions, shops, sales points and agents.

Names are generated from neutral word lists; logins are ``agent_001`` style. A few
agents deliberately work in two shops and two have no display name, because both
cases broke earlier versions of the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

REGIONS = ("North", "South", "East", "West")

SHOP_NAMES = (
    "Northgate", "Riverside", "Old Town", "Harbour View", "Station Square", "Hillcrest",
    "Lakeside", "Market Street", "Southpark", "Eastfield", "Westbrook", "Kingsway",
    "Millbrook", "Cedar Plaza", "Bridgeport", "Elm Court", "Granite Hall", "Maple Centre",
    "Oak Avenue", "Pine Ridge", "Quarry Lane", "Rose Gardens", "Silver Mall", "Tower Point",
    "Union Square", "Valley Road", "Willow Park", "Cross Mall", "Sunset Boulevard", "Garden City",
    "Beacon Hill", "Canal Walk", "Dockside", "Forest Gate", "Glen Park", "Ivy Lane",
)  # fmt: skip

FIRST_NAMES = (
    "Ana", "Boris", "Clara", "Daniel", "Elena", "Filip", "Greta", "Hugo", "Iris", "Jonas",
    "Katja", "Luka", "Mila", "Nikola", "Olga", "Petar", "Rosa", "Stefan", "Tara", "Viktor",
    "Wanda", "Yannick", "Zora", "Adrian", "Bianca", "Cyril", "Dora", "Emil", "Fiona", "Goran",
    "Helena", "Ivan", "Jana", "Kristian", "Lena", "Marko", "Nora", "Oskar", "Paula", "Sara",
)  # fmt: skip

LAST_NAMES = (
    "Novak", "Berg", "Costa", "Dahl", "Ek", "Ferreira", "Gruber", "Horvat", "Ilic", "Jansen",
    "Kovac", "Lind", "Moreau", "Nielsen", "Olsen", "Petrov", "Quinn", "Rossi", "Silva", "Toth",
    "Urban", "Varga", "Weber", "Young", "Zeller", "Arnaud", "Blom", "Carver", "Dimitrov",
    "Engel", "Fischer", "Hart", "Ivanova", "Keller", "Lang", "Marin", "Nagy", "Ortiz", "Popov",
)  # fmt: skip

#: (channel, sales points, number of agents)
CHANNEL_SETUP = (
    ("telesales", ("TS-01", "TS-02"), 14),
    ("partner/consignment", ("PC-01", "PC-02", "PC-03"), 9),
    ("background/system", ("SYS-SELF", "SYS-BATCH"), 3),
    ("other", ("EVT-01",), 3),
)


@dataclass
class Shop:
    shop_id: str
    name: str
    region: str
    sales_points: list[str]
    lam: float  # mean renewals per weekday


@dataclass
class Agent:
    login: str
    name: str
    channel: str
    home_shop: str = ""  # empty for non-shop channels
    sales_points: list[str] = field(default_factory=list)
    weight: float = 1.0
    is_host: bool = False  # starts many express journeys for colleagues
    second_shop: str = ""


@dataclass
class MasterData:
    shops: list[Shop]
    agents: list[Agent]

    def shop(self, shop_id: str) -> Shop:
        return next(s for s in self.shops if s.shop_id == shop_id)

    def channel_agents(self, channel: str) -> list[Agent]:
        return [a for a in self.agents if a.channel == channel]

    def shop_pool(self, shop_id: str) -> tuple[list[Agent], np.ndarray]:
        """Agents selling in a shop with their weights (second-shop agents at half weight)."""
        pool = [a for a in self.agents if a.home_shop == shop_id or a.second_shop == shop_id]
        weights = np.array(
            [a.weight * (0.5 if a.second_shop == shop_id else 1.0) for a in pool], dtype=float
        )
        return pool, weights / weights.sum()


def build_master(rng: np.random.Generator, n_shops: int = 30, n_agents: int = 200) -> MasterData:
    """Create shops in four regions and ``n_agents`` agents across shops and channels."""
    if n_shops > len(SHOP_NAMES):
        raise ValueError(f"at most {len(SHOP_NAMES)} shops supported")
    shops: list[Shop] = []
    for i in range(n_shops):
        code = f"SP{101 + i}"
        points = [code, f"{code}K"] if rng.random() < 0.3 else [code]
        shops.append(
            Shop(
                shop_id=f"SH{i + 1:02d}",
                name=SHOP_NAMES[i],
                region=REGIONS[i * len(REGIONS) // n_shops],
                sales_points=points,
                lam=float(rng.uniform(3.0, 10.0)),
            )
        )

    channel_agents = sum(n for _, _, n in CHANNEL_SETUP)
    shop_agent_total = n_agents - channel_agents
    if shop_agent_total < 2 * n_shops:
        raise ValueError("not enough agents for the shops")
    per_shop = np.full(n_shops, shop_agent_total // n_shops)
    for i in rng.choice(n_shops, shop_agent_total - per_shop.sum(), replace=False):
        per_shop[i] += 1

    used: set[str] = set()

    def fake_name() -> str:
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                return name

    agents: list[Agent] = []
    counter = 1
    for shop, count in zip(shops, per_shop, strict=True):
        for j in range(count):
            agents.append(
                Agent(
                    login=f"agent_{counter:03d}",
                    name=fake_name(),
                    channel="shop",
                    home_shop=shop.shop_id,
                    sales_points=shop.sales_points,
                    weight=0.25 if j == 0 else float(rng.uniform(0.6, 1.6)),
                    is_host=j == 0,
                )
            )
            counter += 1
    for channel, points, count in CHANNEL_SETUP:
        for j in range(count):
            agents.append(
                Agent(
                    login=f"agent_{counter:03d}",
                    name=fake_name(),
                    channel=channel,
                    sales_points=[points[j % len(points)]],
                )
            )
            counter += 1

    shop_agents = [a for a in agents if a.channel == "shop" and not a.is_host]
    # Two shop agents without a display name (a real master-data gap).
    for agent in rng.choice(shop_agents, 2, replace=False):
        agent.name = ""
    # Four agents who also work in a second shop: three in the same region, one not.
    movers = rng.choice(shop_agents, 4, replace=False)
    for k, agent in enumerate(movers):
        home = next(s for s in shops if s.shop_id == agent.home_shop)
        same_region = [s for s in shops if s.region == home.region and s.shop_id != home.shop_id]
        other_region = [s for s in shops if s.region != home.region]
        options = other_region if k == 3 else same_region
        agent.second_shop = options[int(rng.integers(len(options)))].shop_id
    return MasterData(shops=shops, agents=agents)
