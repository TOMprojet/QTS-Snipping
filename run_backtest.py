"""
Lance le backtest sur les événements enregistrés, pour plusieurs latences.

Exemples :
  python run_backtest.py                              # données du collecteur
  python run_backtest.py --split-date 2026-10-15      # in-sample / hors échantillon
  python run_backtest.py --latencies 400,1500,5000
  python run_backtest.py --synthetic                  # données simulées (test de la chaîne)
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.replay_engine import ReplayEngine
from backtest.report import export_trades, metrics, print_metrics
from config.config_snipe import params_backtest, params_collector
from database.events import connect, iter_events, summary
from strategies.snipe.strategie_snipe import SnipeStrategy

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest", "results")


def _date_ms(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def run_period(db_path: str, latency: int, start_ms=None, end_ms=None, seed=42):
    conn = connect(db_path)
    engine = ReplayEngine(SnipeStrategy(), latency_ms=latency, seed=seed)
    trades = engine.run(iter_events(conn, start_ms, end_ms))
    conn.close()
    return trades, engine


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest QTS-Snipping")
    ap.add_argument("--db", default=params_collector["db_path"])
    ap.add_argument("--latencies", default=",".join(map(str, params_backtest["latency_grid_ms"])))
    ap.add_argument("--split-date", help="YYYY-MM-DD : avant = optimisation, après = hors échantillon")
    ap.add_argument("--synthetic", action="store_true",
                    help="génère et utilise des données SIMULÉES (test technique uniquement)")
    args = ap.parse_args()

    db = args.db
    if args.synthetic:
        from backtest.synthetic import generate
        db = "data/synthetic_events.db"
        if os.path.exists(db):
            os.remove(db)
        n = generate(db)
        print(f"[!] Données SIMULÉES générées ({n} événements). Résultats non représentatifs du réel.")

    if not os.path.exists(db):
        sys.exit(f"Base introuvable : {db}. Lance d'abord : python -m collector.stream_recorder")

    conn = connect(db)
    info = summary(conn)
    conn.close()
    if not info["events"]:
        sys.exit("La base ne contient aucun événement.")
    span_h = (info["last_ms"] - info["first_ms"]) / 3_600_000
    print(f"Base : {db} | {info['events']} événements | {info['tokens_created']} tokens "
          f"| {info['migrations']} graduations | {span_h:.1f} h de données")

    periods = [("Toute la période", None, None)]
    if args.split_date:
        cut = _date_ms(args.split_date)
        periods = [("In-sample (avant " + args.split_date + ")", None, cut),
                   ("HORS ÉCHANTILLON (après " + args.split_date + ")", cut, None)]

    seed = params_backtest["random_seed"]
    for latency in [int(x) for x in args.latencies.split(",")]:
        for label, start, end in periods:
            trades, engine = run_period(db, latency, start, end, seed)
            print_metrics(f"Latence {latency} ms | {label}", metrics(trades))
            print(f"  {'Achats échoués':<32} {engine.failed_buys}")
            tag = f"lat{latency}" + ("" if start is None and end is None else ("_oos" if start else "_is"))
            export_trades(trades, os.path.join(RESULTS_DIR, f"trades_{tag}.csv"))
    if args.synthetic:
        print("\n[!] Rappel : données SIMULÉES, ces chiffres testent le code, pas la stratégie.")
    print(f"\nDétail des trades : {RESULTS_DIR}")


if __name__ == "__main__":
    main()
