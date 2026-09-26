import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.replay_engine import ReplayEngine
from collector.stream_recorder import build_url, parse_message
from database.events import Event, connect, insert_event, iter_events
from strategies.snipe.strategie_snipe import Position, SnipeStrategy
from strategies.snipe.token_state import TokenState
from utilities.bonding_curve import BondingCurve

FEE = 0.0125


# --- Bonding curve ---
def test_curve_starts_empty_and_graduates_after_about_85_real_sol():
    c = BondingCurve()
    assert c.progress == pytest.approx(0.0)
    assert c.market_cap_sol == pytest.approx(27.96, abs=0.01)
    c.apply_buy(200, 0.0)     # achat énorme : plafonné à l'offre réelle
    assert c.progress == pytest.approx(1.0)
    assert 84 < c.v_sol - 30 < 86   # ~85 SOL réels déposés à la graduation


def test_round_trip_costs_about_two_fees():
    c = BondingCurve()
    tokens = c.apply_buy(1.0, FEE)
    sol_back = c.apply_sell(tokens, FEE)
    assert sol_back == pytest.approx(1.0 / (1 + FEE) * (1 - FEE), rel=1e-9)


def test_quote_does_not_change_state():
    c = BondingCurve()
    c.quote_buy(5, FEE)
    assert c.v_sol == 30.0


# --- Collecteur ---
def test_parse_pumpportal_messages():
    create = {"signature": "s1", "mint": "M", "traderPublicKey": "DEV", "txType": "create",
              "initialBuy": 1000.0, "solAmount": 0.5, "vSolInBondingCurve": 30.5,
              "vTokensInBondingCurve": 1.05e9, "name": "N", "symbol": "SYM", "uri": "u"}
    ev = parse_message(create, 123)
    assert (ev.tx_type, ev.trader, ev.token_amount, ev.symbol) == ("create", "DEV", 1000.0, "SYM")
    assert parse_message({"message": "Successfully subscribed"}, 1) is None
    assert parse_message({"mint": "M", "txType": "migration"}, 1).tx_type == "migrate"


def test_events_roundtrip_sqlite(tmp_path):
    conn = connect(str(tmp_path / "e.db"))
    insert_event(conn, Event(2, "M", "buy", "A", 1.0, 10.0, 31.0, 1.0e9, "sig2"))
    insert_event(conn, Event(1, "M", "create", "DEV", 0.1, 5.0, 30.1, 1.07e9, "sig1"))
    insert_event(conn, Event(1, "M", "create", "DEV", 0.1, 5.0, 30.1, 1.07e9, "sig1"))  # doublon
    conn.commit()
    evs = list(iter_events(conn))
    assert [e.tx_type for e in evs] == ["create", "buy"]


# --- Stratégie ---
def _state_after(buys: int, t0=0, dt=2000, sol=0.5) -> TokenState:
    c = BondingCurve()
    c.apply_buy(0.5, FEE)
    st = TokenState.from_create(Event(t0, "M", "create", "DEV", 0.5, 1e6, c.v_sol, c.v_tokens))
    for i in range(buys):
        tok = c.apply_buy(sol, FEE)
        st.apply(Event(t0 + (i + 1) * dt, "M", "buy", f"w{i}", sol, tok, c.v_sol, c.v_tokens))
    return st


def test_entry_filters():
    strat = SnipeStrategy()
    st = _state_after(20)
    assert strat.should_enter(st, st.last_ms) == (True, "signal")
    assert strat.should_enter(st, 5_000)[1] == "âge"
    st.dev_sold = True
    assert strat.should_enter(st, st.last_ms)[1] == "dev a vendu"


def test_exit_rules():
    strat = SnipeStrategy()
    st = _state_after(20)
    p = st.price
    pos = Position("M", "S", entry_ms=0, sol_spent=p * 1000, tokens_initial=1000)
    st.curve.v_sol *= 2.2          # prix x2,2 -> 1er palier TP x2
    tokens, reason = strat.exit_decision(pos, st, 1000)
    assert reason == "TP x2" and tokens == pytest.approx(500)
    pos.tokens_left = 500
    st.curve.v_sol /= 3            # effondrement -> trailing stop (TP déjà pris)
    assert strat.exit_decision(pos, st, 2000)[1] in ("trailing stop", "stop-loss")
    pos2 = Position("M", "S", entry_ms=0, sol_spent=st.price * 10, tokens_initial=10)
    assert strat.exit_decision(pos2, st, 301_000)[1] == "stop temporel"


# --- Moteur de replay ---
def test_latency_fills_at_later_price():
    """Plus la latence est grande, plus on achète cher sur un token qui monte."""
    events = []
    c = BondingCurve()
    c.apply_buy(0.5, FEE)
    events.append(Event(0, "M", "create", "DEV", 0.5, 1e6, c.v_sol, c.v_tokens, "s0", symbol="S"))
    for i in range(120):
        tok = c.apply_buy(0.3, FEE)
        events.append(Event((i + 1) * 1000, "M", "buy", f"w{i}", 0.3, tok, c.v_sol, c.v_tokens, f"s{i+1}"))

    def entry_price(latency):
        eng = ReplayEngine(SnipeStrategy(), latency_ms=latency, seed=1)
        eng.mock.c = dict(eng.mock.c, tx_failure_rate=0.0)
        trades = eng.run(iter(events))
        assert len(trades) == 1
        return trades[0].entry_price

    assert entry_price(5000) > entry_price(400)


def test_daily_loss_limit_blocks_new_entries():
    eng = ReplayEngine(SnipeStrategy(), latency_ms=500)
    eng.now_ms = 0
    eng.daily_pnl["1970-01-01"] = -eng.risk["daily_loss_limit_sol"]
    assert not eng._can_open()


def test_api_key_is_added_to_url():
    assert build_url("wss://pumpportal.fun/api/data", "") == "wss://pumpportal.fun/api/data"
    assert build_url("wss://pumpportal.fun/api/data", "abc") == "wss://pumpportal.fun/api/data?api-key=abc"
