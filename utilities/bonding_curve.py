"""
Formule de prix de la bonding curve pump.fun (produit constant x * y = k
sur des réserves virtuelles). Partagée par le live, le paper et le backtest,
pour que les trois calculent exactement le même prix.

Unités : SOL et tokens « humains » (pas les lamports / unités brutes).
"""
from dataclasses import dataclass

TOTAL_SUPPLY = 1_000_000_000.0
INITIAL_VIRTUAL_SOL = 30.0
INITIAL_VIRTUAL_TOKENS = 1_073_000_000.0
INITIAL_REAL_TOKENS = 793_100_000.0
# Tokens virtuels qui ne seront jamais vendus par la courbe
_VIRTUAL_ONLY_TOKENS = INITIAL_VIRTUAL_TOKENS - INITIAL_REAL_TOKENS


@dataclass
class BondingCurve:
    v_sol: float = INITIAL_VIRTUAL_SOL
    v_tokens: float = INITIAL_VIRTUAL_TOKENS

    @property
    def k(self) -> float:
        return self.v_sol * self.v_tokens

    @property
    def price(self) -> float:
        """Prix spot en SOL par token."""
        return self.v_sol / self.v_tokens

    @property
    def real_tokens_left(self) -> float:
        return max(0.0, self.v_tokens - _VIRTUAL_ONLY_TOKENS)

    @property
    def progress(self) -> float:
        """Remplissage de la courbe : 0 à la création, 1 à la graduation."""
        return 1.0 - self.real_tokens_left / INITIAL_REAL_TOKENS

    @property
    def market_cap_sol(self) -> float:
        return self.price * TOTAL_SUPPLY

    def quote_buy(self, sol_in: float, fee_pct: float) -> float:
        """Tokens reçus pour sol_in SOL dépensés (frais inclus dans sol_in)."""
        if sol_in <= 0:
            return 0.0
        sol_to_curve = sol_in / (1.0 + fee_pct)
        tokens_out = self.v_tokens - self.k / (self.v_sol + sol_to_curve)
        return min(tokens_out, self.real_tokens_left)

    def quote_sell(self, tokens_in: float, fee_pct: float) -> float:
        """SOL nets reçus pour tokens_in tokens vendus."""
        if tokens_in <= 0:
            return 0.0
        sol_gross = self.v_sol - self.k / (self.v_tokens + tokens_in)
        return sol_gross * (1.0 - fee_pct)

    def apply_buy(self, sol_in: float, fee_pct: float) -> float:
        tokens = self.quote_buy(sol_in, fee_pct)
        # Si l'achat est plafonné par l'offre restante, seul le SOL nécessaire entre
        sol_to_curve = min(sol_in / (1.0 + fee_pct), self.k / (self.v_tokens - tokens) - self.v_sol)
        self.v_sol += sol_to_curve
        self.v_tokens -= tokens
        return tokens

    def apply_sell(self, tokens_in: float, fee_pct: float) -> float:
        sol_net = self.quote_sell(tokens_in, fee_pct)
        self.v_sol -= sol_net / (1.0 - fee_pct)
        self.v_tokens += tokens_in
        return sol_net
