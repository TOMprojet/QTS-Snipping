"""
Génère des données pump.fun SIMULÉES pour tester la chaîne de backtest
(sans connexion réseau). Ces données ne disent RIEN sur la rentabilité réelle :
les vrais résultats viendront des données enregistrées par le collecteur.

Profils de tokens : mort-né, rug (le dev vend tout), pump & dump, gradué.
"""
import random
from typing import List

from database.events import Event, connect, insert_event
from utilities.bonding_curve import BondingCurve

FEE = 0.0125
PROFILES = [("mort", 0.60), ("rug", 0.20), ("pump_dump", 0.15), ("gradue", 0.05)]


class _TokenSim:
    def __init__(self, rng: random.Random, mint: str, t0: int):
        self.rng, self.mint, self.t = rng, mint, t0
        self.curve = BondingCurve()
        self.holdings: dict = {}
        self.events: List[Event] = []
        self.n_wallets = 0

    def wallet(self) -> str:
        self.n_wallets += 1
        return f"{self.mint}_w{self.n_wallets}"

    def step(self, lo_s: float, hi_s: float) -> None:
        self.t += int(self.rng.uniform(lo_s, hi_s) * 1000)

    def _ev(self, tx_type: str, trader: str, sol: float, tokens: float, **kw) -> None:
        self.events.append(Event(self.t, self.mint, tx_type, trader, sol, tokens,
                                 self.curve.v_sol, self.curve.v_tokens,
                                 signature=f"{self.mint}_{len(self.events)}", **kw))

    def create(self, dev: str, sol: float) -> None:
        tokens = self.curve.apply_buy(sol, FEE)
        self.holdings[dev] = tokens
        self._ev("create", dev, sol, tokens, name=f"Token {self.mint}", symbol=self.mint[:6].upper())

    def buy(self, trader: str, sol: float) -> None:
        if self.curve.progress >= 1:
            return
        tokens = self.curve.apply_buy(sol, FEE)
        self.holdings[trader] = self.holdings.get(trader, 0.0) + tokens
        self._ev("buy", trader, sol, tokens)

    def sell(self, trader: str, fraction: float = 1.0) -> None:
        tokens = self.holdings.get(trader, 0.0) * fraction
        if tokens <= 0:
            return
        sol = self.curve.apply_sell(tokens, FEE)
        self.holdings[trader] -= tokens
        self._ev("sell", trader, sol, tokens)

    def random_holder(self, exclude: str = "") -> str:
        holders = [w for w, q in self.holdings.items() if q > 0 and w != exclude]
        return self.rng.choice(holders) if holders else ""


def _simulate(rng: random.Random, mint: str, t0: int, profile: str) -> List[Event]:
    s = _TokenSim(rng, mint, t0)
    dev = f"{mint}_dev"
    s.create(dev, rng.uniform(0.2, 2.5))
    if profile == "mort":
        for _ in range(rng.randint(2, 10)):
            s.step(1, 15)
            s.buy(s.wallet(), rng.uniform(0.05, 0.5))
        for _ in range(rng.randint(1, 5)):
            s.step(5, 30)
            s.sell(s.random_holder(), 1.0)
    elif profile == "rug":
        # Le dev vend à un moment aléatoire, souvent en pleine montée
        n = rng.randint(15, 60)
        rug_at = rng.randint(5, n)
        for i in range(n):
            s.step(0.5, 3)
            s.buy(s.wallet(), rng.uniform(0.1, 1.2))
            if i == rug_at:
                break
        s.step(0.3, 2)
        s.sell(dev, 1.0)
        for _ in range(rng.randint(5, 20)):
            s.step(0.5, 5)
            s.sell(s.random_holder(dev), 1.0)
    elif profile == "pump_dump":
        n = rng.randint(10, 90)   # le sommet arrive plus ou moins tôt
        for i in range(n):
            s.step(0.5, 3)
            s.buy(s.wallet(), rng.uniform(0.1, 0.8) * (1 + i / n))
            if rng.random() < 0.15:
                s.sell(s.random_holder(dev), rng.uniform(0.3, 1.0))
        for _ in range(rng.randint(20, 60)):
            s.step(0.5, 4)
            s.sell(s.random_holder(), rng.uniform(0.5, 1.0))
    else:  # gradué
        while s.curve.progress < 1:
            s.step(0.3, 2)
            s.buy(s.wallet(), rng.uniform(0.2, 2.5))
            if rng.random() < 0.2:
                s.sell(s.random_holder(dev), rng.uniform(0.2, 1.0))
        s.step(1, 5)
        s._ev("migrate", "", 0.0, 0.0)
    return s.events


def generate(db_path: str, n_tokens: int = 2000, span_days: float = 4.0,
             start_ms: int = 1_767_225_600_000, seed: int = 7) -> int:
    """Écrit n_tokens tokens simulés dans db_path. Renvoie le nombre d'événements."""
    rng = random.Random(seed)
    names = [p for p, _ in PROFILES]
    weights = [w for _, w in PROFILES]
    events: List[Event] = []
    for i in range(n_tokens):
        t0 = start_ms + int(rng.uniform(0, span_days * 86_400_000))
        profile = rng.choices(names, weights)[0]
        events.extend(_simulate(rng, f"sim{i:06d}", t0, profile))
    conn = connect(db_path)
    for ev in events:
        insert_event(conn, ev)
    conn.commit()
    conn.close()
    return len(events)
