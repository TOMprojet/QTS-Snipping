"""
Phase 1 : enregistre le flux temps réel pump.fun (via PumpPortal) dans SQLite.

- s'abonne aux créations de tokens et aux migrations (graduations),
- pour chaque nouveau token, s'abonne à ses trades pendant `track_minutes`,
- stocke chaque événement (+ le JSON brut, pour pouvoir re-parser plus tard).

Lecture seule : aucun wallet, aucune clé, aucun ordre.

Lancement :  python -m collector.stream_recorder
Arrêt :      Ctrl+C (les événements en attente sont enregistrés avant de quitter)
"""
import asyncio
import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_snipe import params_collector
from database.events import Event, connect, insert_event, summary
from utilities.logger import logger


def now_ms() -> int:
    return int(time.time() * 1000)


def _f(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_message(data: dict, recv_ms: int) -> Optional[Event]:
    """Transforme un message PumpPortal en Event. None si ce n'est pas un événement."""
    tx_type = data.get("txType")
    mint = data.get("mint")
    if not tx_type or not mint:
        return None
    tx_type = {"migration": "migrate"}.get(tx_type, tx_type)
    return Event(
        recv_ms=recv_ms,
        mint=mint,
        tx_type=tx_type,
        trader=data.get("traderPublicKey", "") or "",
        sol_amount=_f(data.get("solAmount")) or 0.0,
        # À la création, l'achat initial du dev est dans initialBuy
        token_amount=_f(data.get("tokenAmount", data.get("initialBuy"))) or 0.0,
        v_sol=_f(data.get("vSolInBondingCurve")),
        v_tokens=_f(data.get("vTokensInBondingCurve")),
        signature=data.get("signature", "") or "",
        name=data.get("name", "") or "",
        symbol=data.get("symbol", "") or "",
        uri=data.get("uri", "") or "",
    )


class StreamRecorder:
    def __init__(self, params: dict = params_collector):
        self.p = params
        self.conn = connect(params["db_path"])
        self.tracked: dict = {}          # mint -> ms de début de suivi
        self.pending_subs: list = []
        self.uncommitted = 0
        self.stats = {"create": 0, "buy": 0, "sell": 0, "migrate": 0}

    def record(self, data: dict) -> None:
        ev = parse_message(data, now_ms())
        if ev is None:
            if "message" in data:
                logger.info("PumpPortal", reply=data.get("message"))
            return
        insert_event(self.conn, ev, raw=data)
        self.stats[ev.tx_type] = self.stats.get(ev.tx_type, 0) + 1
        self.uncommitted += 1
        if ev.tx_type == "create" and ev.mint not in self.tracked:
            self.tracked[ev.mint] = ev.recv_ms
            self.pending_subs.append(ev.mint)
        if self.uncommitted >= self.p["commit_every_events"]:
            self.flush()

    def flush(self) -> None:
        if self.uncommitted:
            self.conn.commit()
            self.uncommitted = 0

    async def _maintenance(self, ws) -> None:
        """Toutes les secondes : abonnements groupés, désabonnements, commit, stats."""
        last_stats = time.time()
        while True:
            await asyncio.sleep(self.p["subscribe_batch_seconds"])
            if self.pending_subs:
                keys, self.pending_subs = self.pending_subs, []
                await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": keys}))
            cutoff = now_ms() - self.p["track_minutes"] * 60_000
            expired = [m for m, t in self.tracked.items() if t < cutoff]
            if expired:
                await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": expired}))
                for m in expired:
                    del self.tracked[m]
            self.flush()
            if time.time() - last_stats > 60:
                logger.info("Collecteur actif", tracked=len(self.tracked), **self.stats)
                last_stats = time.time()

    async def run_once(self) -> None:
        import websockets  # import tardif : le backtest n'en a pas besoin

        async with websockets.connect(self.p["ws_url"], ping_interval=20, max_size=None) as ws:
            logger.info("Connecté à PumpPortal", url=self.p["ws_url"])
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            await ws.send(json.dumps({"method": "subscribeMigration"}))
            # Après une reconnexion, on reprend le suivi des tokens encore actifs
            self.pending_subs = list(self.tracked.keys())
            maintenance = asyncio.create_task(self._maintenance(ws))
            try:
                async for message in ws:
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict):
                        self.record(data)
            finally:
                maintenance.cancel()
                self.flush()

    async def run_forever(self) -> None:
        delay = 1
        while True:
            try:
                await self.run_once()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Connexion perdue, reconnexion", error=e, retry_in_s=delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.p["reconnect_max_delay_s"])


def main() -> None:
    recorder = StreamRecorder()
    logger.info("Démarrage du collecteur", db=params_collector["db_path"], **summary(recorder.conn))
    try:
        asyncio.run(recorder.run_forever())
    except KeyboardInterrupt:
        pass
    finally:
        recorder.flush()
        logger.info("Collecteur arrêté", **summary(recorder.conn))
        recorder.conn.close()


if __name__ == "__main__":
    main()
