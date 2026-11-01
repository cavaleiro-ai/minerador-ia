"""Fonte de blocos: mineração solo SEM nó próprio.

Os dados do topo da blockchain (hash, altura, bits, horários) e as transações
da mempool vêm da API pública do mempool.space. O minerador monta o bloco
inteiro sozinho, e o envio é feito direto para a rede P2P (ver p2p.py).

Só entram transações cujas entradas já estão confirmadas (sem "pais" na
mempool) e que não gastam a mesma moeda que outra, para o bloco não ficar
inválido por dependência que não conseguimos verificar sem um nó.
"""
from __future__ import annotations

import threading
import time

import httpx

from . import btc, p2p
from .job import Job, build_job

API = "https://mempool.space/api"
POLL_SECONDS = 20
REBUILD_SECONDS = 90
BLOCK_VERSION = 0x20000000


class PublicSource:
    kind = "publico"
    network = "main"

    def __init__(self, payout_script: bytes, *, include_txs: bool = True, max_txs: int = 25,
                 log=print, on_job=None):
        self.payout_script = payout_script
        self.include_txs = include_txs
        self.max_txs = max_txs
        self.log = log
        self.on_job = on_job
        self.current: Job | None = None
        self.running = False
        self.connected = False
        self.error: str | None = None
        self.tip: dict = {}
        self._http = httpx.Client(timeout=20, headers={"User-Agent": "MineradorIA/1.0"})
        self._candidates: dict[str, dict] = {}     # txid -> dados da transação
        self._rejected: set[str] = set()
        self._confirmed_parents: set[str] = set()
        self._wake = threading.Event()

    # ---- HTTP ----
    def _get(self, path: str, as_json: bool = True):
        for attempt in range(3):
            r = self._http.get(API + path)
            if r.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return r.json() if as_json else r.text
        r.raise_for_status()

    # ---- ciclo de vida ----
    def start(self) -> None:
        self.running = True
        threading.Thread(target=self._loop, daemon=True, name="fonte-publica").start()

    def stop(self) -> None:
        self.running = False
        self._wake.set()

    def request_refresh(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        last_tip = None
        last_build = 0.0
        while self.running:
            try:
                tip_hash = self._get("/blocks/tip/hash", as_json=False).strip()
                if tip_hash != last_tip or time.time() - last_build > REBUILD_SECONDS \
                        or self._wake.is_set():
                    self._wake.clear()
                    self.refresh(tip_hash, new_block=tip_hash != last_tip)
                    last_tip, last_build = tip_hash, time.time()
                if not self.connected:
                    self.log("Conectado aos dados públicos da rede (mempool.space).", "ok")
                self.connected, self.error = True, None
            except Exception as e:  # noqa: BLE001
                msg = f"{e.__class__.__name__}: {e}"
                if self.error != msg:
                    self.log(f"Dados públicos indisponíveis: {msg}", "erro")
                self.connected, self.error = False, msg
            self._wake.wait(POLL_SECONDS)

    # ---- montagem do bloco ----
    def refresh(self, tip_hash: str | None = None, new_block: bool = True) -> Job:
        tip_hash = tip_hash or self._get("/blocks/tip/hash", as_json=False).strip()
        tip = self._get(f"/block/{tip_hash}")
        self.tip = tip
        height = tip["height"] + 1
        bits = tip["bits"]
        if height % btc.RETARGET_INTERVAL == 0:
            first_hash = self._get(f"/block-height/{height - btc.RETARGET_INTERVAL}", as_json=False)
            first = self._get(f"/block/{first_hash.strip()}")
            bits = btc.next_work_required(tip["bits"], first["timestamp"], tip["timestamp"])
            self.log(f"Bloco {height} é de ajuste de dificuldade: novo bits {bits:08x}")
        ntime = max(int(time.time()), tip["mediantime"] + 1)
        txs = self._select_transactions(new_block) if self.include_txs else []
        job = build_job(source=self.kind, network="main", version=BLOCK_VERSION,
                        prev_hash=btc.hex_to_hash(tip_hash), height=height, bits=bits,
                        ntime=ntime, txs=txs,
                        coinbase_value=btc.block_subsidy(height) + sum(t["fee"] for t in txs),
                        payout_script=self.payout_script)
        job.info["nonce_bloco_anterior"] = tip.get("nonce")
        self.current = job
        if self.on_job:
            self.on_job(job)
        return job

    def _select_transactions(self, new_block: bool) -> list[dict]:
        if new_block and self._candidates:
            # Remove o que foi confirmado ou saiu da mempool (substituído, expirado).
            for txid in list(self._candidates):
                try:
                    if self._get(f"/tx/{txid}/status").get("confirmed"):
                        del self._candidates[txid]
                except httpx.HTTPStatusError:
                    del self._candidates[txid]
        try:
            recent = self._get("/mempool/recent")
        except httpx.HTTPError:
            recent = []
        for item in recent:
            txid = item["txid"]
            if txid in self._candidates or txid in self._rejected:
                continue
            tx = self._load_tx(txid)
            if tx:
                self._candidates[txid] = tx
            else:
                self._rejected.add(txid)
        # Mais rentáveis primeiro (taxa por peso), sem gastar a mesma moeda duas vezes.
        chosen, spent = [], set()
        for tx in sorted(self._candidates.values(), key=lambda t: t["fee"] / max(t["weight"], 1),
                         reverse=True):
            if spent & tx["inputs"]:
                continue
            chosen.append(tx)
            spent |= tx["inputs"]
            if len(chosen) >= self.max_txs:
                break
        while len(self._candidates) > 4 * self.max_txs:   # limita o cache
            worst = min(self._candidates.values(), key=lambda t: t["fee"] / max(t["weight"], 1))
            del self._candidates[btc.hash_to_hex(worst["txid"])]
        return chosen

    def _load_tx(self, txid: str) -> dict | None:
        try:
            info = self._get(f"/tx/{txid}")
            if info["status"]["confirmed"]:
                return None
            for vin in info["vin"]:
                parent = vin["txid"]
                if parent in self._confirmed_parents:
                    continue
                if not self._get(f"/tx/{parent}/status").get("confirmed"):
                    return None            # depende de outra transação ainda não confirmada
                self._confirmed_parents.add(parent)
            raw = bytes.fromhex(self._get(f"/tx/{txid}/hex", as_json=False).strip())
        except (httpx.HTTPError, KeyError, ValueError):
            return None
        tx_hash, wtxid = btc.tx_ids(raw)
        if btc.hash_to_hex(tx_hash) != txid:
            return None                    # dado inconsistente: descarta
        if len(self._confirmed_parents) > 20000:
            self._confirmed_parents.clear()
        return {"raw": raw, "txid": tx_hash, "wtxid": wtxid, "fee": int(info["fee"]),
                "weight": int(info["weight"]),
                "inputs": {(v["txid"], v["vout"]) for v in info["vin"]}}

    # ---- envio ----
    def submit(self, job: Job, block: bytes) -> dict:
        result = p2p.broadcast_block(block, "main", max_peers=12, height=job.height)
        if result["ok"]:
            return {"ok": True, "detalhe": f"bloco enviado para {result['enviados']} nós da rede",
                    "p2p": result}
        return {"ok": False, "motivo": result.get("erro") or "nenhum nó aceitou a conexão",
                "p2p": result}

    def status(self) -> dict:
        return {
            "conectado": self.connected,
            "erro": self.error,
            "rede": "main",
            "altura_topo": self.tip.get("height"),
            "transacoes_candidatas": len(self._candidates),
        }
