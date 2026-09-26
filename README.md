# QTS-Snipping

Bot de sniping de memecoins pump.fun (Solana), dans la lignée de QTS-Hybrid.
**Phase actuelle : 1 (collecte de données + backtest).** Aucun wallet, aucune clé privée, aucun ordre réel.

## Installation

```bash
pip install -r requirements.txt
```

## 1. Collecter les données (à laisser tourner 2 à 4 semaines)

```bash
python -m collector.stream_recorder
```

Enregistre en continu dans `data/pumpfun_events.db` (SQLite) le flux PumpPortal :
créations de tokens, chaque achat/vente des 30 premières minutes de chaque token,
graduations. Le JSON brut est gardé pour pouvoir re-parser plus tard.
Ctrl+C pour arrêter ; relancer reprend dans la même base.

## 2. Lancer le backtest

```bash
python run_backtest.py                           # sur les données collectées
python run_backtest.py --split-date 2026-10-15   # in-sample / hors échantillon
python run_backtest.py --latencies 400,1500,5000 # sensibilité à la latence
python run_backtest.py --synthetic               # données SIMULÉES : test technique uniquement
```

Le détail de chaque trade est exporté dans `backtest/results/*.csv`.

## Tests

```bash
python -m pytest -q
```

## Comment marche le backtest

- Les événements sont rejoués dans l'ordre exact de réception.
- La stratégie (`strategies/snipe/strategie_snipe.py`) décide ; l'ordre est exécuté
  **après la latence**, au prix de la bonding curve à cet instant (`utilities/bonding_curve.py`),
  avec frais pump.fun, frais réseau, priority fee et un taux d'échec de transaction.
- Une vente échouée est renvoyée jusqu'à 2 fois (frais payés à chaque tentative).
- Limites de risque : taille fixe, positions simultanées max, perte max journalière.

Limites connues de la phase 1 :
- notre propre ordre ne modifie pas les réserves vues par les trades suivants ;
- après graduation, la vente se fait au dernier prix de la courbe (PumpSwap non simulé) ;
- les frais pump.fun (`params_costs`) sont une hypothèse à revérifier.

## Structure

```
config/config_snipe.py          paramètres (filtres, sorties, risque, coûts, backtest)
collector/stream_recorder.py    collecteur PumpPortal -> SQLite
database/events.py              schéma et lecture des événements
strategies/snipe/token_state.py état d'un token (prix, acheteurs, holders, dev)
strategies/snipe/strategie_snipe.py  règles d'entrée / sortie
backtest/mock_pumpfun.py        faux pump.fun (exécution simulée)
backtest/replay_engine.py       moteur de replay
backtest/report.py              métriques + export CSV
backtest/synthetic.py           générateur de données simulées (tests)
utilities/bonding_curve.py      formule de prix pump.fun
utilities/logger.py             repris de QTS-Hybrid
```

## Prochaines phases

3. Recherche de stratégie sur données réelles (walk-forward, hors échantillon)
4. Paper trading en direct (décisions réelles, aucun ordre envoyé)
5. Live minuscule, seulement si les critères go/no-go sont remplis
