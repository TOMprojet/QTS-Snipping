"""
Stratégie de sniping « momentum » (approche B) : entrée 20 s à 3 min après
le lancement sur des tokens filtrés, sortie par paliers / stops.

Ce module ne fait que DÉCIDER. L'exécution est faite par le backtest
(mock_pumpfun) ou, plus tard, par l'API live : la même logique sert partout.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

from config.config_snipe import params_entry, params_exit
from strategies.snipe.token_state import TokenState


@dataclass
class Position:
    mint: str
    symbol: str
    entry_ms: int
    sol_spent: float
    tokens_initial: float
    tokens_left: float = 0.0
    sol_received: float = 0.0
    fees_sol: float = 0.0
    tp_done: int = 0
    peak_price: float = 0.0
    exit_reasons: list = field(default_factory=list)
    closed_ms: Optional[int] = None

    def __post_init__(self):
        if not self.tokens_left:
            self.tokens_left = self.tokens_initial

    @property
    def entry_price(self) -> float:
        """Prix effectif payé (frais inclus), en SOL par token."""
        return self.sol_spent / self.tokens_initial if self.tokens_initial else 0.0

    @property
    def pnl_sol(self) -> float:
        return self.sol_received - self.sol_spent - self.fees_sol


class SnipeStrategy:
    def __init__(self, entry: dict = params_entry, exit_: dict = params_exit):
        self.e = entry
        self.x = exit_

    def should_enter(self, st: TokenState, now_ms: int) -> Tuple[bool, str]:
        e = self.e
        age = st.age_s(now_ms)
        if st.migrated:
            return False, "migré"
        if age < e["min_age_s"] or age > e["max_age_s"]:
            return False, "âge"
        if e["reject_if_dev_sold"] and st.dev_sold:
            return False, "dev a vendu"
        if st.dev_buy_sol > e["max_dev_buy_sol"]:
            return False, "achat dev trop gros"
        if len(st.buyers) < e["min_unique_buyers"]:
            return False, "pas assez d'acheteurs"
        if st.buy_sell_ratio < e["min_buy_sell_ratio"]:
            return False, "ratio achats/ventes"
        if st.net_sol_in < e["min_net_sol_in"]:
            return False, "flux SOL net"
        if not (e["min_progress"] <= st.progress <= e["max_progress"]):
            return False, "remplissage courbe"
        if st.top10_share > e["max_top10_share"]:
            return False, "concentration holders"
        return True, "signal"

    def exit_decision(self, pos: Position, st: TokenState, now_ms: int) -> Tuple[float, str]:
        """Renvoie (tokens à vendre, raison). 0 = on garde."""
        x = self.x
        price = st.price
        pos.peak_price = max(pos.peak_price, price)
        if pos.tokens_left <= 0:
            return 0.0, ""
        entry = pos.entry_price
        # Sorties totales, par ordre de priorité
        if x["exit_on_migration"] and st.migrated:
            return pos.tokens_left, "graduation"
        if x["exit_on_dev_sell"] and st.dev_sold:
            return pos.tokens_left, "dev vend"
        if price <= entry * (1 - x["stop_loss_pct"]):
            return pos.tokens_left, "stop-loss"
        if pos.tp_done > 0 and price <= pos.peak_price * (1 - x["trailing_pct"]):
            return pos.tokens_left, "trailing stop"
        if (now_ms - pos.entry_ms) / 1000.0 >= x["max_hold_s"]:
            return pos.tokens_left, "stop temporel"
        # Take-profit par paliers
        levels = x["tp_levels"]
        if pos.tp_done < len(levels):
            multiple, fraction = levels[pos.tp_done]
            if price >= entry * multiple:
                pos.tp_done += 1
                return min(pos.tokens_left, pos.tokens_initial * fraction), f"TP x{multiple:g}"
        return 0.0, ""
