"""
État d'un token reconstruit à partir de ses événements : prix, remplissage de
la courbe, acheteurs, concentration des holders, comportement du dev.
Utilisé à l'identique en live, en paper et en backtest.
"""
from dataclasses import dataclass, field

from database.events import Event
from utilities.bonding_curve import TOTAL_SUPPLY, BondingCurve


@dataclass
class TokenState:
    mint: str
    created_ms: int
    creator: str = ""
    symbol: str = ""
    dev_buy_sol: float = 0.0
    curve: BondingCurve = field(default_factory=BondingCurve)
    last_ms: int = 0
    buyers: set = field(default_factory=set)
    n_buys: int = 0
    n_sells: int = 0
    sol_in: float = 0.0
    sol_out: float = 0.0
    holdings: dict = field(default_factory=dict)   # wallet -> tokens (net)
    dev_sold: bool = False
    migrated: bool = False

    @classmethod
    def from_create(cls, ev: Event) -> "TokenState":
        st = cls(mint=ev.mint, created_ms=ev.recv_ms, creator=ev.trader,
                 symbol=ev.symbol, dev_buy_sol=ev.sol_amount)
        st._sync_curve(ev)
        st.last_ms = ev.recv_ms
        if ev.trader and ev.token_amount:
            st.holdings[ev.trader] = ev.token_amount
        return st

    def _sync_curve(self, ev: Event) -> None:
        # Les réserves publiées font foi : on ne recalcule pas, on recopie.
        if ev.v_sol and ev.v_tokens:
            self.curve = BondingCurve(ev.v_sol, ev.v_tokens)

    def apply(self, ev: Event) -> None:
        self.last_ms = ev.recv_ms
        if ev.tx_type == "migrate":
            self.migrated = True
            return
        self._sync_curve(ev)
        if ev.tx_type == "buy":
            self.n_buys += 1
            self.sol_in += ev.sol_amount
            self.buyers.add(ev.trader)
            self.holdings[ev.trader] = self.holdings.get(ev.trader, 0.0) + ev.token_amount
        elif ev.tx_type == "sell":
            self.n_sells += 1
            self.sol_out += ev.sol_amount
            self.holdings[ev.trader] = max(0.0, self.holdings.get(ev.trader, 0.0) - ev.token_amount)
            if ev.trader == self.creator:
                self.dev_sold = True

    # --- Indicateurs ---
    def age_s(self, now_ms: int) -> float:
        return (now_ms - self.created_ms) / 1000.0

    @property
    def price(self) -> float:
        return self.curve.price

    @property
    def progress(self) -> float:
        return self.curve.progress

    @property
    def net_sol_in(self) -> float:
        return self.sol_in - self.sol_out

    @property
    def buy_sell_ratio(self) -> float:
        return self.n_buys / max(1, self.n_sells)

    @property
    def top10_share(self) -> float:
        top = sorted(self.holdings.values(), reverse=True)[:10]
        return sum(top) / TOTAL_SUPPLY
