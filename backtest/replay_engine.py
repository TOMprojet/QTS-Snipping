"""
Moteur de replay : rejoue les événements pump.fun dans l'ordre exact de
réception, fait décider la stratégie, et exécute ses ordres via MockPumpFun
après `latency_ms`, au prix de la courbe à cet instant-là.
"""
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from backtest.mock_pumpfun import Fill, MockPumpFun, Order
from config.config_snipe import params_risk
from database.events import Event
from strategies.snipe.strategie_snipe import Position, SnipeStrategy
from strategies.snipe.token_state import TokenState

MAX_RETRIES = 2          # une transaction échouée est renvoyée au plus 2 fois
PRUNE_EVERY = 20_000     # nettoyage mémoire des tokens trop vieux


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class ReplayEngine:
    def __init__(self, strategy: SnipeStrategy, latency_ms: int,
                 risk: dict = params_risk, seed: int = 42):
        self.strategy = strategy
        self.latency_ms = latency_ms
        self.risk = risk
        self.mock = MockPumpFun(risk["starting_balance_sol"], seed=seed)
        self.states: Dict[str, TokenState] = {}
        self.seen: set = set()                  # tokens déjà évalués positivement
        self.positions: Dict[str, Position] = {}
        self.pending: List[Order] = []
        self.closed: List[Position] = []
        self.daily_pnl: Dict[str, float] = {}
        self.failed_buys = 0
        self.now_ms = 0

    # --- Ordres ---
    def _submit(self, side: str, mint: str, amount: float, reason: str, attempts: int = 1) -> None:
        self.pending.append(Order(side, mint, amount, self.now_ms,
                                  self.now_ms + self.latency_ms, reason, attempts))

    def _has_pending(self, mint: str) -> bool:
        return any(o.mint == mint for o in self.pending)

    def _fill_due(self, up_to_ms: int) -> None:
        # En boucle : une vente échouée peut être renvoyée dans la même fenêtre
        while True:
            due = [o for o in self.pending if o.fill_ms <= up_to_ms]
            if not due:
                return
            self.pending = [o for o in self.pending if o.fill_ms > up_to_ms]
            for order in sorted(due, key=lambda o: o.fill_ms):
                self.now_ms = max(self.now_ms, order.fill_ms)
                fill = self.mock.execute(order, self.states.get(order.mint))
                self._on_fill(order, fill)

    def _on_fill(self, order: Order, fill: Fill) -> None:
        pos = self.positions.get(order.mint)
        if order.side == "buy":
            if not fill.ok:
                self.failed_buys += 1
                self._book_fees(order.mint, fill.tx_fees)
                return
            st = self.states[order.mint]
            self.positions[order.mint] = Position(
                mint=order.mint, symbol=st.symbol, entry_ms=order.fill_ms,
                sol_spent=fill.sol, tokens_initial=fill.tokens,
                fees_sol=fill.tx_fees, peak_price=fill.price)
            return
        # Vente
        if pos is None:
            return
        pos.fees_sol += fill.tx_fees
        if not fill.ok:
            if order.attempts <= MAX_RETRIES:
                self._submit("sell", order.mint, order.amount, order.reason, order.attempts + 1)
            else:
                # Abandon : les tokens sont considérés perdus (cas extrême)
                pos.tokens_left = 0.0
                self._close(pos, order.reason + " (échec)")
            return
        pos.tokens_left -= fill.tokens
        pos.sol_received += fill.sol
        pos.exit_reasons.append(order.reason)
        if pos.tokens_left <= 1e-9:
            self._close(pos, order.reason)

    def _book_fees(self, mint: str, fees: float) -> None:
        d = _day(self.now_ms)
        self.daily_pnl[d] = self.daily_pnl.get(d, 0.0) - fees

    def _close(self, pos: Position, reason: str) -> None:
        pos.closed_ms = self.now_ms
        if not pos.exit_reasons or pos.exit_reasons[-1] != reason:
            pos.exit_reasons.append(reason)
        del self.positions[pos.mint]
        self.closed.append(pos)
        d = _day(self.now_ms)
        self.daily_pnl[d] = self.daily_pnl.get(d, 0.0) + pos.pnl_sol

    # --- Décisions ---
    def _can_open(self) -> bool:
        n_pending_buys = sum(1 for o in self.pending if o.side == "buy")
        if len(self.positions) + n_pending_buys >= self.risk["max_open_positions"]:
            return False
        if self.daily_pnl.get(_day(self.now_ms), 0.0) <= -self.risk["daily_loss_limit_sol"]:
            return False
        return self.mock.balance >= self.risk["position_size_sol"] + 0.01

    def _check_exit(self, pos: Position) -> None:
        if self._has_pending(pos.mint):
            return
        st = self.states.get(pos.mint)
        if st is None:
            return
        tokens, reason = self.strategy.exit_decision(pos, st, self.now_ms)
        if tokens > 0:
            self._submit("sell", pos.mint, tokens, reason)

    def _prune(self) -> None:
        horizon = self.strategy.e["max_age_s"] * 1000 + 60_000
        for mint in [m for m, s in self.states.items()
                     if self.now_ms - s.created_ms > horizon and m not in self.positions
                     and not self._has_pending(m)]:
            del self.states[mint]

    # --- Boucle principale ---
    def run(self, events: Iterable[Event]) -> List[Position]:
        for i, ev in enumerate(events):
            self._fill_due(ev.recv_ms)
            self.now_ms = ev.recv_ms
            if ev.tx_type == "create":
                if ev.mint not in self.states:
                    self.states[ev.mint] = TokenState.from_create(ev)
                continue
            st = self.states.get(ev.mint)
            if st is None:
                continue          # token créé avant le début des données, ou nettoyé
            st.apply(ev)
            # Sorties : le token concerné, plus les stops temporels des autres
            for pos in list(self.positions.values()):
                self._check_exit(pos)
            # Entrée
            if (ev.mint not in self.seen and ev.mint not in self.positions
                    and not self._has_pending(ev.mint) and self._can_open()):
                ok, _ = self.strategy.should_enter(st, self.now_ms)
                if ok:
                    self.seen.add(ev.mint)
                    self._submit("buy", ev.mint, self.risk["position_size_sol"], "entrée")
            if i % PRUNE_EVERY == 0:
                self._prune()
        # Fin des données : on vide les ordres puis on ferme au dernier prix connu
        self._fill_due(float("inf"))
        for pos in list(self.positions.values()):
            if pos.tokens_left > 0:
                self._submit("sell", pos.mint, pos.tokens_left, "fin des données")
        self._fill_due(float("inf"))
        return self.closed
