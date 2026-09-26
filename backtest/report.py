"""Métriques de backtest et export CSV des trades."""
import csv
import os
from datetime import datetime, timezone
from typing import List

from strategies.snipe.strategie_snipe import Position


def metrics(trades: List[Position]) -> dict:
    pnls = [t.pnl_sol for t in trades]
    n = len(pnls)
    if n == 0:
        return {"trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    # Drawdown max sur le PnL cumulé, dans l'ordre de clôture
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in sorted(trades, key=lambda t: t.closed_ms or 0):
        cum += t.pnl_sol
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    top3 = sorted(pnls, reverse=True)[:3]
    days = {datetime.fromtimestamp(t.entry_ms / 1000, tz=timezone.utc).date() for t in trades}
    return {
        "trades": n,
        "trades_par_jour": n / max(1, len(days)),
        "win_rate": len(wins) / n,
        "gain_moyen_sol": sum(wins) / len(wins) if wins else 0.0,
        "perte_moyenne_sol": sum(losses) / len(losses) if losses else 0.0,
        "esperance_sol": sum(pnls) / n,
        "pnl_total_sol": sum(pnls),
        "pnl_sans_top3_sol": sum(pnls) - sum(top3),
        "drawdown_max_sol": max_dd,
        "frais_tx_sol": sum(t.fees_sol for t in trades),
    }


def print_metrics(title: str, m: dict) -> None:
    print(f"\n=== {title} ===")
    if m.get("trades", 0) == 0:
        print("Aucun trade.")
        return
    labels = {
        "trades": "Trades", "trades_par_jour": "Trades / jour", "win_rate": "Win rate",
        "gain_moyen_sol": "Gain moyen (SOL)", "perte_moyenne_sol": "Perte moyenne (SOL)",
        "esperance_sol": "Espérance / trade (SOL)", "pnl_total_sol": "PnL total (SOL)",
        "pnl_sans_top3_sol": "PnL sans les 3 meilleurs (SOL)",
        "drawdown_max_sol": "Drawdown max (SOL)", "frais_tx_sol": "Frais réseau payés (SOL)",
    }
    for key, label in labels.items():
        v = m[key]
        if key == "win_rate":
            txt = f"{v:.1%}"
        elif key.endswith("_sol"):
            txt = f"{v:+.4f}"
        else:
            txt = f"{v:g}" if isinstance(v, int) else f"{v:.1f}"
        print(f"  {label:<32} {txt}")


def export_trades(trades: List[Position], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["mint", "symbol", "entree_utc", "duree_s", "sol_depense", "sol_recu",
                    "frais_tx", "pnl_sol", "multiple", "sorties"])
        for t in trades:
            dur = ((t.closed_ms or t.entry_ms) - t.entry_ms) / 1000
            w.writerow([t.mint, t.symbol,
                        datetime.fromtimestamp(t.entry_ms / 1000, tz=timezone.utc).isoformat(),
                        f"{dur:.1f}", f"{t.sol_spent:.6f}", f"{t.sol_received:.6f}",
                        f"{t.fees_sol:.6f}", f"{t.pnl_sol:.6f}",
                        f"{(t.sol_received / t.sol_spent) if t.sol_spent else 0:.3f}",
                        " | ".join(t.exit_reasons)])
