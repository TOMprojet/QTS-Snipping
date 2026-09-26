"""
Faux pump.fun pour le backtest (même rôle que MockExchange dans QTS-Backtest).
Exécute nos ordres sur l'état de la bonding curve AU MOMENT DU REMPLISSAGE,
c'est-à-dire après la latence, avec frais, priority fee et échecs de transaction.

Simplification assumée : notre propre ordre ne modifie pas les réserves vues
par les trades suivants (tailles petites devant la liquidité).
"""
import random
from dataclasses import dataclass
from typing import Optional

from config.config_snipe import params_costs
from strategies.snipe.token_state import TokenState


@dataclass
class Order:
    side: str            # buy | sell
    mint: str
    amount: float        # SOL pour un achat, tokens pour une vente
    submit_ms: int
    fill_ms: int
    reason: str = ""
    attempts: int = 1


@dataclass
class Fill:
    ok: bool
    sol: float = 0.0       # SOL dépensés (achat) ou reçus nets (vente)
    tokens: float = 0.0
    tx_fees: float = 0.0   # frais réseau + priority fee payés
    price: float = 0.0


class MockPumpFun:
    def __init__(self, starting_balance: float, costs: dict = params_costs, seed: int = 42):
        self.balance = starting_balance
        self.c = costs
        self.rng = random.Random(seed)

    @property
    def tx_cost(self) -> float:
        return self.c["network_fee_sol"] + self.c["priority_fee_sol"]

    def execute(self, order: Order, st: Optional[TokenState]) -> Fill:
        fees = self.tx_cost
        self.balance -= fees
        if st is None or self.rng.random() < self.c["tx_failure_rate"]:
            return Fill(ok=False, tx_fees=fees)
        fee_pct = self.c["pump_fee_pct"]
        if order.side == "buy":
            if st.migrated or order.amount > self.balance:
                return Fill(ok=False, tx_fees=fees)
            tokens = st.curve.quote_buy(order.amount, fee_pct)
            if tokens <= 0:
                return Fill(ok=False, tx_fees=fees)
            self.balance -= order.amount
            return Fill(ok=True, sol=order.amount, tokens=tokens, tx_fees=fees, price=st.price)
        # Vente : après graduation, on vend au dernier état de la courbe
        # (PumpSwap n'est pas simulé en phase 1).
        sol = st.curve.quote_sell(order.amount, fee_pct)
        self.balance += sol
        return Fill(ok=True, sol=sol, tokens=order.amount, tx_fees=fees, price=st.price)
