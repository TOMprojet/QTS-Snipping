"""
Stockage SQLite des événements pump.fun bruts (créations, achats, ventes,
migrations). C'est la matière première du backtest.
"""
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Event:
    recv_ms: int          # heure de réception chez nous (ms epoch)
    mint: str
    tx_type: str          # create | buy | sell | migrate
    trader: str = ""
    sol_amount: float = 0.0
    token_amount: float = 0.0
    v_sol: Optional[float] = None       # réserves virtuelles APRÈS la transaction
    v_tokens: Optional[float] = None
    signature: str = ""
    # Champs de création uniquement
    name: str = ""
    symbol: str = ""
    uri: str = ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recv_ms INTEGER NOT NULL,
    mint TEXT NOT NULL,
    tx_type TEXT NOT NULL,
    trader TEXT,
    sol_amount REAL,
    token_amount REAL,
    v_sol REAL,
    v_tokens REAL,
    signature TEXT,
    name TEXT,
    symbol TEXT,
    uri TEXT,
    raw TEXT,
    UNIQUE(signature, mint, tx_type)
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(recv_ms);
CREATE INDEX IF NOT EXISTS idx_events_mint ON events(mint, recv_ms);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def insert_event(conn: sqlite3.Connection, ev: Event, raw: Optional[dict] = None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO events
           (recv_ms, mint, tx_type, trader, sol_amount, token_amount, v_sol, v_tokens,
            signature, name, symbol, uri, raw)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ev.recv_ms, ev.mint, ev.tx_type, ev.trader, ev.sol_amount, ev.token_amount,
         ev.v_sol, ev.v_tokens, ev.signature or None, ev.name, ev.symbol, ev.uri,
         json.dumps(raw) if raw is not None else None),
    )


def iter_events(conn: sqlite3.Connection, start_ms: Optional[int] = None,
                end_ms: Optional[int] = None) -> Iterator[Event]:
    """Événements dans l'ordre chronologique de réception."""
    query = ("SELECT recv_ms, mint, tx_type, trader, sol_amount, token_amount, v_sol, v_tokens, "
             "signature, name, symbol, uri FROM events WHERE 1=1")
    args = []
    if start_ms is not None:
        query += " AND recv_ms >= ?"
        args.append(start_ms)
    if end_ms is not None:
        query += " AND recv_ms < ?"
        args.append(end_ms)
    query += " ORDER BY recv_ms, id"
    for row in conn.execute(query, args):
        yield Event(recv_ms=row[0], mint=row[1], tx_type=row[2], trader=row[3] or "",
                    sol_amount=row[4] or 0.0, token_amount=row[5] or 0.0,
                    v_sol=row[6], v_tokens=row[7], signature=row[8] or "",
                    name=row[9] or "", symbol=row[10] or "", uri=row[11] or "")


def summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), MIN(recv_ms), MAX(recv_ms), "
        "SUM(tx_type='create'), SUM(tx_type='migrate') FROM events"
    ).fetchone()
    return {"events": row[0], "first_ms": row[1], "last_ms": row[2],
            "tokens_created": row[3] or 0, "migrations": row[4] or 0}
