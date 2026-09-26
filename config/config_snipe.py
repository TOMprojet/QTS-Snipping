# Configuration QTS-Snipping
# Même esprit que config_hybrid.py : tous les paramètres au même endroit.
# Les valeurs ci-dessous sont des HYPOTHÈSES DE DÉPART, à valider en backtest.

# --- COLLECTEUR (phase 1) ---
params_collector = {
    "ws_url": "wss://pumpportal.fun/api/data",
    # PumpPortal exige une clé API (liée à un wallet PumpPortal avec >= 0,02 SOL)
    # pour suivre les trades. La clé se met dans .env, jamais dans le code.
    "api_key_env": "PUMPPORTAL_API_KEY",
    "db_path": "data/pumpfun_events.db",
    # Durée pendant laquelle on suit les trades d'un token après sa création.
    # Au-delà, on se désabonne pour limiter la charge (la plupart meurent avant).
    "track_minutes": 30,
    "subscribe_batch_seconds": 1.0,   # regroupe les abonnements pour limiter les messages
    "commit_every_events": 200,
    "reconnect_max_delay_s": 60,
}

# --- STRATÉGIE : filtres d'entrée (approche B « momentum ») ---
params_entry = {
    "min_age_s": 20,              # on n'entre pas avant 20 s de vie
    "max_age_s": 180,             # ni après 3 min
    "min_unique_buyers": 15,      # wallets acheteurs distincts
    "min_buy_sell_ratio": 1.5,    # nb achats / nb ventes
    "min_net_sol_in": 3.0,        # SOL entrés - SOL sortis depuis la création
    "min_progress": 0.05,         # remplissage de la bonding curve (0 à 1)
    "max_progress": 0.50,
    "max_top10_share": 0.35,      # part de l'offre détenue par les 10 plus gros holders
    "max_dev_buy_sol": 3.0,       # achat initial du dev trop gros = suspect
    "reject_if_dev_sold": True,
}

# --- STRATÉGIE : sorties ---
params_exit = {
    # (multiple du prix d'entrée, fraction de la position INITIALE à vendre)
    "tp_levels": [(2.0, 0.50), (3.0, 0.25)],
    "stop_loss_pct": 0.30,        # -30 % depuis le prix d'entrée
    "trailing_pct": 0.25,         # après le 1er TP : -25 % depuis le plus haut
    "max_hold_s": 300,            # stop temporel : 5 min
    "exit_on_dev_sell": True,
    "exit_on_migration": True,    # sortie à la graduation (PumpSwap non simulé en phase 1)
}

# --- RISQUE ---
params_risk = {
    "position_size_sol": 0.10,
    "max_open_positions": 3,
    "daily_loss_limit_sol": 1.0,  # le bot s'arrête pour la journée au-delà
    "starting_balance_sol": 5.0,  # backtest / paper uniquement
}

# --- COÛTS (à revérifier : pump.fun change régulièrement sa grille) ---
params_costs = {
    "pump_fee_pct": 0.0125,       # frais protocole + créateur sur la bonding curve (hypothèse)
    "network_fee_sol": 0.000005,  # frais de base Solana par transaction
    "priority_fee_sol": 0.0005,   # priority fee / tip par transaction
    "tx_failure_rate": 0.05,      # part des transactions qui échouent (frais payés quand même)
}

# --- BACKTEST ---
params_backtest = {
    # Délai entre la décision et l'exécution on-chain, en millisecondes.
    # C'est LE paramètre décisif : on le fait varier dans run_backtest.py.
    "latency_ms": 1500,
    "latency_grid_ms": [400, 1500, 5000],
    "random_seed": 42,
}
