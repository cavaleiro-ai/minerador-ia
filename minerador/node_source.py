"""Fonte de blocos: nó Bitcoin Core (o seu nó na mainnet ou o nó regtest local).

O nó entrega as transações da mempool (getblocktemplate). O minerador monta a
coinbase, o compromisso segwit e a árvore de merkle sozinho, e envia o bloco
pronto com submitblock quando um nonce válido é encontrado.
"""
from __future__ import annotations

import threading
import time

from . import btc
from .job import Job, build_job
from .rpc import RPCClient, RPCError

TEMPLATE_REFRESH = 30   # segundos entre atualizações da lista de transações
CHAIN_TO_NETWORK = {"main": "main", "regtest": "regtest"}


class NodeSource:
    def __init__(self, rpc: RPCClient, payout_script: bytes, *, kind: str = "no",
                 log=print, on_job=None):
        self.rpc = rpc
        self.payout_script = payout_script
        self.kind = kind
        self.log = log
        self.on_job = on_job
        self.current: Job | None = None
        self.running = False
        self.connected = False
        self.error: str | None = None
        self.chain: str | None = None
        self.mining_info: dict = {}
        self._wake = threading.Event()

    @property
    def network(self) -> str:
        return CHAIN_TO_NETWORK.get(self.chain or "main", "test")

    def check_connection(self) -> dict:
        info = self.rpc.call("getblockchaininfo")
        self.chain = info["chain"]
        return info

    def start(self) -> None:
        self.running = True
        threading.Thread(target=self._loop, daemon=True, name=f"fonte-{self.kind}").start()

    def stop(self) -> None:
        self.running = False
        self._wake.set()

    def request_refresh(self) -> None:
        self._wake.set()

    def refresh(self) -> Job:
        """Busca um template novo agora e o transforma em bloco candidato."""
        tpl = self.rpc.call("getblocktemplate", {"rules": ["segwit"]})
        txs = []
        for t in tpl["transactions"]:
            raw = bytes.fromhex(t["data"])
            txs.append({"raw": raw, "txid": btc.hex_to_hash(t["txid"]),
                        "wtxid": btc.hex_to_hash(t["hash"]), "fee": t.get("fee", 0),
                        "weight": t.get("weight", 0)})
        job = build_job(source=self.kind, network=self.network, version=tpl["version"],
                        prev_hash=btc.hex_to_hash(tpl["previousblockhash"]), height=tpl["height"],
                        bits=int(tpl["bits"], 16), ntime=tpl["curtime"], txs=txs,
                        coinbase_value=tpl["coinbasevalue"], payout_script=self.payout_script)
        # O compromisso segwit é calculado por nós; o do nó serve de conferência.
        expected = tpl.get("default_witness_commitment")
        if expected and expected != job.info["compromisso_segwit"]:
            self.log("Aviso: compromisso segwit diferente do calculado pelo nó!", "erro")
        job.info["nonce_bloco_anterior"] = self.rpc.call(
            "getblockheader", tpl["previousblockhash"]).get("nonce")
        self.mining_info = self.rpc.call("getmininginfo")
        self.current = job
        if self.on_job:
            self.on_job(job)
        return job

    def _loop(self) -> None:
        last_best = None
        last_refresh = 0.0
        while self.running:
            try:
                best = self.rpc.call("getbestblockhash")
                if best != last_best or self._wake.is_set() \
                        or time.time() - last_refresh > TEMPLATE_REFRESH:
                    self._wake.clear()
                    self.refresh()
                    last_best, last_refresh = best, time.time()
                if not self.connected:
                    self.log("Conectado ao nó Bitcoin Core.", "ok")
                self.connected, self.error = True, None
            except RPCError as e:
                if self.error != str(e):
                    self.log(f"Nó Bitcoin Core: {e}", "erro")
                self.connected, self.error = False, str(e)
                self._wake.wait(5)
                continue
            self._wake.wait(2)

    def submit(self, job: Job, block: bytes) -> dict:
        try:
            result = self.rpc.call("submitblock", block.hex())
        except RPCError as e:
            return {"ok": False, "motivo": str(e)}
        self._wake.set()     # pede um template novo imediatamente
        if result is None:
            return {"ok": True, "detalhe": "o nó aceitou o bloco"}
        return {"ok": False, "motivo": result}

    def status(self) -> dict:
        return {
            "conectado": self.connected,
            "erro": self.error,
            "rede": self.chain,
            "altura_no": self.mining_info.get("blocks"),
            "mempool": self.mining_info.get("pooledtx"),
        }
