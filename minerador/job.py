"""Bloco candidato: tudo o que é preciso para testar nonces e montar o bloco final.

A coinbase é guardada dividida (coinb1 + extranonce + coinb2) e a árvore de
merkle como um caminho a partir da coinbase, como no protocolo Stratum.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

from . import btc

EXTRANONCE_SIZE = 8
_ids = itertools.count(1)


@dataclass
class Job:
    job_id: str
    source: str                 # "publico", "no" ou "regtest"
    version: int
    prev_hash: bytes            # ordem interna
    coinb1: bytes
    coinb2: bytes
    merkle_branch: list[bytes]
    ntime: int
    bits: int
    height: int
    network: str = "main"
    tx_raw: list[bytes] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    @property
    def target(self) -> int:
        return btc.bits_to_target(self.bits)

    @property
    def difficulty(self) -> float:
        return btc.target_to_difficulty(self.target)

    def coinbase(self, extranonce: bytes) -> bytes:
        return self.coinb1 + extranonce + self.coinb2

    def merkle_root(self, extranonce: bytes) -> bytes:
        return btc.merkle_root_from_branch(btc.sha256d(self.coinbase(extranonce)), self.merkle_branch)

    def header(self, extranonce: bytes, nonce: int, ntime: int | None = None) -> bytes:
        return btc.build_header(self.version, self.prev_hash, self.merkle_root(extranonce),
                                self.ntime if ntime is None else ntime, self.bits, nonce)

    def check(self, nonce: int, extranonce: bytes = b"\0" * EXTRANONCE_SIZE,
              ntime: int | None = None) -> dict:
        """Testa um nonce: SHA-256 duplo do cabeçalho comparado com o alvo da rede."""
        header = self.header(extranonce, nonce, ntime)
        digest = btc.sha256d(header)
        return {
            "nonce": nonce,
            "cabecalho_hex": header.hex(),
            "hash": btc.hash_to_hex(digest),
            "valido": btc.hash_to_int(digest) <= self.target,
            "dificuldade_hash": btc.hash_difficulty(digest),
            "zeros_bits": btc.leading_zero_bits(digest),
        }

    def build_block(self, extranonce: bytes, nonce: int, ntime: int | None = None) -> bytes:
        """Bloco completo serializado, pronto para ser transmitido."""
        coinbase = btc.add_coinbase_witness(self.coinbase(extranonce))
        return (self.header(extranonce, nonce, ntime) + btc.varint(1 + len(self.tx_raw))
                + coinbase + b"".join(self.tx_raw))

    def summary(self) -> dict:
        zero = b"\0" * EXTRANONCE_SIZE
        return {
            "job_id": self.job_id,
            "fonte": self.source,
            "rede": self.network,
            "altura": self.height,
            "versao": f"{self.version:08x}",
            "bloco_anterior": btc.hash_to_hex(self.prev_hash),
            "merkle_root": btc.hash_to_hex(self.merkle_root(zero)),
            "horario": self.ntime,
            "bits": f"{self.bits:08x}",
            "alvo": f"{self.target:064x}",
            "zeros_necessarios": 256 - self.target.bit_length(),
            "dificuldade": self.difficulty,
            "cabecalho_sem_nonce": self.header(zero, 0)[:76].hex(),
            "coinbase_hex": self.coinbase(zero).hex(),
            "num_transacoes": 1 + len(self.tx_raw),
            "criado_em": self.created,
            **self.info,
        }


def build_job(*, source: str, network: str, version: int, prev_hash: bytes, height: int,
              bits: int, ntime: int, txs: list[dict], coinbase_value: int, payout_script: bytes,
              tag: bytes = b"/MineradorIA/") -> Job:
    """Monta o bloco candidato.

    txs: lista de {"raw": bytes, "txid": bytes, "wtxid": bytes, "fee": int, "weight": int}
    (txid/wtxid na ordem interna), já na ordem em que devem entrar no bloco.
    """
    commitment = btc.witness_commitment_script([t["wtxid"] for t in txs])
    outputs = [(coinbase_value, payout_script), (0, commitment)]
    coinb1, coinb2 = btc.build_coinbase(height, outputs, extranonce_size=EXTRANONCE_SIZE, tag=tag)
    fees = sum(t["fee"] for t in txs)
    return Job(
        job_id=f"{source}-{next(_ids)}",
        source=source, network=network, version=version, prev_hash=prev_hash,
        coinb1=coinb1, coinb2=coinb2,
        merkle_branch=btc.merkle_branch([t["txid"] for t in txs]),
        ntime=ntime, bits=bits, height=height,
        tx_raw=[t["raw"] for t in txs],
        info={
            "recompensa_total": coinbase_value,
            "script_recompensa": payout_script.hex(),
            "taxas_total": fees,
            "subsidio": coinbase_value - fees,
            "peso_total": sum(t.get("weight", 0) for t in txs),
            "compromisso_segwit": commitment.hex(),
            "transacoes": [{"txid": btc.hash_to_hex(t["txid"]), "taxa": t["fee"],
                            "peso": t.get("weight", 0)} for t in txs],
            "saidas": [{"valor": coinbase_value,
                        "endereco": btc.script_to_address(payout_script, network)},
                       {"valor": 0, "endereco": "compromisso segwit (OP_RETURN)"}],
        },
    )
