"""Controlador central: junta configuração, fonte de blocos, IA, validação e registro."""
from __future__ import annotations

import collections
import copy
import json
import os
import random
import threading
import time

import httpx

from . import btc, regtest
from .ai import PROVIDERS, Copilot
from .job import EXTRANONCE_SIZE, Job
from .node_source import NodeSource
from .paths import CONFIG_FILE, FOUND_FILE
from .public_source import API as MEMPOOL_API, PublicSource
from .rpc import RPCClient, RPCError

DEFAULT_CONFIG = {
    "endereco": "",
    "modo": "publico",                  # publico | no | regtest
    "incluir_transacoes": True,
    "max_transacoes": 25,
    "envio_automatico": True,
    "no": {"host": "127.0.0.1", "porta": 8332, "usuario": "", "senha": "", "cookie": ""},
    "ia": {
        "provedor": "xai",
        "chaves": {p: "" for p in PROVIDERS},
        "modelos": {p: v["modelo"] for p, v in PROVIDERS.items()},
        "base_url_compat": "",
        "intervalo": 5,
        "max_chamadas": 200,
    },
}
MODES = {"publico": "Mainnet solo (sem nó)", "no": "Mainnet com nó próprio",
         "regtest": "Regtest (teste local)"}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def mask(secret: str) -> str:
    return f"{secret[:6]}…{secret[-4:]}" if len(secret) > 12 else ("•" * len(secret))


def _apply_env_overrides(cfg: dict) -> dict:
    """Endereço e IA via ambiente (.env / Compose). Não grava seed nem chave privada."""
    addr = os.environ.get("MINERADOR_ENDERECO", "").strip()
    if addr:
        cfg["endereco"] = addr
    provedor = os.environ.get("MINERADOR_IA_PROVEDOR", "").strip()
    if provedor in PROVIDERS:
        cfg["ia"]["provedor"] = provedor
    modelo = os.environ.get("MINERADOR_IA_MODELO", "").strip()
    if modelo:
        cfg["ia"]["modelos"][cfg["ia"]["provedor"]] = modelo
    base = os.environ.get("MINERADOR_IA_BASE_URL", "").strip()
    if base:
        cfg["ia"]["base_url_compat"] = base
    chave = os.environ.get("MINERADOR_IA_CHAVE", "").strip()
    if chave:
        cfg["ia"]["chaves"][cfg["ia"]["provedor"]] = chave
    return cfg


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.events: collections.deque = collections.deque(maxlen=400)
        self.config = self._load_config()
        self.source = None
        self.current_job: Job | None = None
        self.solved_jobs: set[str] = set()
        self.found: list = self._load_found()
        self.checked_total = 0
        self.regtest = regtest.RegtestNode()
        self.copilot = Copilot(self)
        self.network: dict = {}
        self._network_at = 0.0
        self._http = httpx.Client(timeout=20, headers={"User-Agent": "MineradorIA/1.0"})
        threading.Thread(target=self._network_loop, daemon=True).start()
        self.log("Minerador iniciado.")

    # ---- registro e persistência ----
    def log(self, msg: str, level: str = "info") -> None:
        self.events.appendleft({"quando": time.time(), "nivel": level, "msg": msg})

    def _load_config(self) -> dict:
        try:
            cfg = _merge(DEFAULT_CONFIG, json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            cfg["ia"].pop("palpites_por_chamada", None)     # opção antiga (vários nonces por chamada)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = copy.deepcopy(DEFAULT_CONFIG)
        return _apply_env_overrides(cfg)

    def _save_config(self) -> None:
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_found(self) -> list:
        try:
            return json.loads(FOUND_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_found(self) -> None:
        FOUND_FILE.write_text(json.dumps(self.found, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- configuração ----
    def public_config(self) -> dict:
        cfg = copy.deepcopy(self.config)
        cfg["ia"]["chaves"] = {p: mask(k) for p, k in cfg["ia"]["chaves"].items()}
        cfg["ia"]["tem_chave"] = {p: bool(k) for p, k in self.config["ia"]["chaves"].items()}
        cfg["no"]["senha"] = mask(cfg["no"]["senha"])
        cfg["provedores"] = {p: v["nome"] for p, v in PROVIDERS.items()}
        cfg["modos"] = MODES
        info = self.address_info(cfg["endereco"]) if cfg["endereco"] else None
        cfg["endereco_info"] = info
        return cfg

    @staticmethod
    def address_info(address: str) -> dict:
        try:
            script, net, kind = btc.address_to_script(address)
            return {"valido": True, "rede": btc.NETWORKS[net]["nome"], "tipo": kind,
                    "rede_id": net, "script": script.hex()}
        except ValueError as e:
            return {"valido": False, "erro": str(e)}

    def update_config(self, data: dict) -> dict:
        with self.lock:
            new = copy.deepcopy(self.config)
            if "endereco" in data:
                addr = str(data["endereco"]).strip()
                if addr:
                    info = self.address_info(addr)
                    if not info["valido"]:
                        raise ValueError(f"Endereço inválido: {info['erro']}")
                    src = self.source
                    if src is not None and src.kind != "regtest" \
                            and (src.network == "main") != (info["rede_id"] == "main"):
                        raise ValueError("Este endereço é de outra rede Bitcoin. "
                                         "Use um endereço da mainnet (bc1…, 1… ou 3…).")
                new["endereco"] = addr
            if data.get("modo") in MODES:
                new["modo"] = data["modo"]
            for key in ("incluir_transacoes", "envio_automatico"):
                if key in data:
                    new[key] = bool(data[key])
            if "max_transacoes" in data:
                new["max_transacoes"] = max(0, min(500, int(data["max_transacoes"])))
            for key in ("host", "porta", "usuario", "senha", "cookie"):
                value = data.get("no", {}).get(key)
                if value is not None and not (key == "senha" and "…" in str(value)):
                    new["no"][key] = int(value) if key == "porta" else str(value).strip()
            ia = data.get("ia", {})
            if ia.get("provedor") in PROVIDERS:
                new["ia"]["provedor"] = ia["provedor"]
            for p, key in (ia.get("chaves") or {}).items():
                if p in PROVIDERS and key is not None and "…" not in key and "•" not in key:
                    new["ia"]["chaves"][p] = key.strip()
            for p, model in (ia.get("modelos") or {}).items():
                if p in PROVIDERS and model is not None:
                    new["ia"]["modelos"][p] = str(model).strip()
            if "base_url_compat" in ia:
                new["ia"]["base_url_compat"] = str(ia["base_url_compat"]).strip()
            for key, lo, hi in (("intervalo", 0, 3600), ("max_chamadas", 1, 1_000_000)):
                if key in ia:
                    new["ia"][key] = max(lo, min(hi, float(ia[key]) if key == "intervalo"
                                                 else int(ia[key])))
            address_changed = new["endereco"] != self.config["endereco"]
            self.config = new
            self._save_config()
            if address_changed:
                self._apply_new_address()
        return self.public_config()

    def _payout_script(self) -> bytes | None:
        addr = self.config["endereco"]
        return btc.address_to_script(addr)[0] if addr else None

    def _apply_new_address(self) -> None:
        """Troca o endereço da recompensa no bloco candidato sem precisar reconectar."""
        src = self.source
        if src is None or src.kind == "regtest":   # regtest paga a carteira de teste
            return
        script = self._payout_script()
        if script is None:
            self.disconnect()
            self.log("Endereço removido: minerador desconectado.", "erro")
            return
        src.payout_script = script
        self.current_job = None          # nada de minerar um bloco que paga o endereço antigo
        src.request_refresh()
        self.log(f"Endereço da recompensa trocado para {self.config['endereco']}. "
                 "Remontando o bloco candidato…", "ok")

    # ---- conexão com a rede ----
    def connect(self) -> None:
        with self.lock:
            self.disconnect(quiet=True)
            mode = self.config["modo"]
            if mode == "regtest":
                if not self.regtest.is_running():
                    self.log("Ligando o nó regtest…")
                    self.regtest.start()
                self.regtest.status()
                script, _, _ = btc.address_to_script(self.regtest.address)
                src = NodeSource(self.regtest.rpc, script, kind="regtest", log=self.log,
                                 on_job=self._on_job)
                src.check_connection()
                self.log(f"Regtest: recompensa vai para a carteira de teste {self.regtest.address}")
            else:
                addr = self.config["endereco"]
                if not addr:
                    raise ValueError("Cadastre o endereço da sua carteira antes de conectar.")
                script, net, _ = btc.address_to_script(addr)
                if mode == "publico":
                    if net != "main":
                        raise ValueError("O modo solo sem nó é só para a mainnet: use um endereço bc1…, 1… ou 3….")
                    src = PublicSource(script, include_txs=self.config["incluir_transacoes"],
                                       max_txs=self.config["max_transacoes"], log=self.log,
                                       on_job=self._on_job)
                else:
                    n = self.config["no"]
                    rpc = RPCClient(n["host"], int(n["porta"]), n["usuario"], n["senha"],
                                    cookie_file=n["cookie"] or None)
                    src = NodeSource(rpc, script, kind="no", log=self.log, on_job=self._on_job)
                    try:
                        src.check_connection()
                    except RPCError as e:
                        raise ValueError(f"Não foi possível falar com o nó: {e}")
                    if (src.network == "main") != (net == "main"):
                        raise ValueError(f"O nó está na rede '{src.chain}', mas o endereço é de outra rede.")
            self.source = src
            src.start()
            self.log(f"Modo: {MODES[mode]}. Aguardando o bloco candidato…", "ok")

    def disconnect(self, quiet: bool = False) -> None:
        with self.lock:
            self.copilot.stop()
            if self.source:
                self.source.stop()
                self.source = None
                if not quiet:
                    self.log("Desconectado.")
            self.current_job = None

    def _on_job(self, job: Job) -> None:
        if job.source != "regtest" and job.info.get("script_recompensa") != \
                (self._payout_script() or b"").hex():
            return                       # montado com o endereço antigo: descarta
        previous = self.current_job
        self.current_job = job
        if previous is None or previous.height != job.height:
            self.log(f"Novo bloco candidato: altura {job.height}, {1 + len(job.tx_raw)} transações, "
                     f"recompensa {job.info['recompensa_total'] / btc.COIN:.8f} BTC")

    # ---- testar e emitir ----
    def try_nonce(self, job: Job, nonce: int, origin: str, extranonce: bytes | None = None,
                  ntime: int | None = None, submit: bool | None = None) -> dict:
        extranonce = extranonce if extranonce is not None else b"\0" * EXTRANONCE_SIZE
        result = job.check(nonce, extranonce, ntime)
        self.checked_total += 1
        if result["valido"] and job.job_id in self.solved_jobs:
            result["envio"] = {"ok": False, "motivo": "este bloco candidato já foi resolvido"}
        elif result["valido"]:
            self.log(f"NONCE VÁLIDO encontrado por {origin}: {nonce} (altura {job.height})", "ok")
            if submit is None:
                submit = self.config["envio_automatico"]
            if submit:
                result["envio"] = self.submit(job, extranonce, nonce, ntime, origin)
        return result

    def submit(self, job: Job, extranonce: bytes, nonce: int, ntime: int | None, origin: str) -> dict:
        with self.lock:
            if job.job_id in self.solved_jobs:
                return {"ok": False, "motivo": "este bloco candidato já foi resolvido e enviado"}
            check = job.check(nonce, extranonce, ntime)
            if not check["valido"]:
                return {"ok": False, "motivo": "hash acima do alvo: o bloco seria rejeitado"}
            source = self.source
            if source is None:
                return {"ok": False, "motivo": "não conectado"}
            block = job.build_block(extranonce, nonce, ntime)
            self.solved_jobs.add(job.job_id)
        self.log(f"Transmitindo bloco {job.height} ({len(block)} bytes)…")
        result = source.submit(job, block)
        entry = {"quando": time.time(), "altura": job.height, "hash": check["hash"],
                 "origem": origin, "modo": job.source, "rede": job.network, "nonce": nonce,
                 "recompensa": job.info["recompensa_total"], "transacoes": 1 + len(job.tx_raw),
                 "resultado": {k: v for k, v in result.items() if k != "p2p"}, "bloco_hex": block.hex()}
        self.found.insert(0, entry)
        self._save_found()
        if result["ok"]:
            self.log(f"BLOCO {job.height} ENVIADO! {result.get('detalhe', '')} Hash {check['hash']}", "ok")
        else:
            self.solved_jobs.discard(job.job_id)
            self.log(f"Bloco {job.height} recusado: {result.get('motivo')}", "erro")
        return result

    def manual(self, nonce: int, extranonce_hex: str = "", ntime: int | None = None,
               send: bool = False) -> dict:
        job = self.current_job
        if job is None:
            raise ValueError("Ainda não há bloco candidato. Conecte-se primeiro (aba Carteira & Rede).")
        if not 0 <= nonce <= 0xFFFFFFFF:
            raise ValueError("O nonce deve estar entre 0 e 4294967295.")
        extranonce = b"\0" * EXTRANONCE_SIZE
        if extranonce_hex:
            extranonce = bytes.fromhex(extranonce_hex)
            if len(extranonce) != EXTRANONCE_SIZE:
                raise ValueError(f"O extranonce deve ter {EXTRANONCE_SIZE} bytes ({2 * EXTRANONCE_SIZE} dígitos hex).")
        result = self.try_nonce(job, nonce, "você (manual)", extranonce, ntime, submit=send)
        result.update(alvo=f"{job.target:064x}", altura=job.height, job_id=job.job_id,
                      campos=btc.parse_header(bytes.fromhex(result["cabecalho_hex"])),
                      zeros_necessarios=256 - job.target.bit_length())
        return result

    # ---- regtest ----
    def regtest_mine_local(self, count: int) -> dict:
        """Mina blocos de teste sorteando nonces (no regtest ~2 tentativas por bloco)."""
        src = self.source
        if not isinstance(src, NodeSource) or src.kind != "regtest":
            raise ValueError("Conecte-se no modo Regtest primeiro.")
        accepted = 0
        for _ in range(max(1, min(500, count))):
            job = src.refresh()
            for _attempt in range(10_000):
                nonce = random.getrandbits(32)
                if job.check(nonce)["valido"]:
                    block = job.build_block(b"\0" * EXTRANONCE_SIZE, nonce)
                    if src.submit(job, block)["ok"]:
                        accepted += 1
                    break
        src.refresh()
        self.log(f"Regtest: {accepted} blocos de preparação minerados localmente.", "ok")
        return {"aceitos": accepted}

    # ---- rede Bitcoin (dados públicos) ----
    def _network_loop(self) -> None:
        while True:
            try:
                hr = self._http.get(f"{MEMPOOL_API}/v1/mining/hashrate/3d").json()
                adj = self._http.get(f"{MEMPOOL_API}/v1/difficulty-adjustment").json()
                height = int(self._http.get(f"{MEMPOOL_API}/blocks/tip/height").text)
                self.network = {"altura": height, "hashrate": hr.get("currentHashrate"),
                                "dificuldade": hr.get("currentDifficulty"),
                                "ajuste_previsto_pct": adj.get("difficultyChange"),
                                "blocos_ate_ajuste": adj.get("remainingBlocks"),
                                "atualizado": time.time()}
            except Exception:  # noqa: BLE001 - sem internet, o painel só não mostra esses dados
                pass
            time.sleep(60)

    def verify_real_block(self, height: int) -> dict:
        block_hash = self._http.get(f"{MEMPOOL_API}/block-height/{height}")
        if block_hash.status_code != 200:
            raise ValueError("Altura não encontrada.")
        block_hash = block_hash.text.strip()
        header = bytes.fromhex(self._http.get(f"{MEMPOOL_API}/block/{block_hash}/header").text.strip())
        fields = btc.parse_header(header)
        digest = btc.sha256d(header)
        target = btc.bits_to_target(fields["bits"])
        return {"altura": height, "hash_oficial": block_hash, "hash_calculado": btc.hash_to_hex(digest),
                "confere": btc.hash_to_hex(digest) == block_hash, "campos": fields,
                "cabecalho_hex": header.hex(), "alvo": f"{target:064x}",
                "valido": btc.hash_to_int(digest) <= target,
                "zeros_bits": btc.leading_zero_bits(digest)}

    @staticmethod
    def hash_header(fields: dict) -> dict:
        header = btc.build_header(int(fields["version"]), btc.hex_to_hash(fields["prev_hash"]),
                                  btc.hex_to_hash(fields["merkle_root"]), int(fields["time"]),
                                  int(fields["bits"]), int(fields["nonce"]))
        digest = btc.sha256d(header)
        target = btc.bits_to_target(int(fields["bits"]))
        return {"hash": btc.hash_to_hex(digest), "valido": btc.hash_to_int(digest) <= target,
                "zeros_bits": btc.leading_zero_bits(digest), "cabecalho_hex": header.hex()}

    # ---- estado para a interface e para a IA ----
    def chance(self) -> dict | None:
        job = self.current_job
        if not job:
            return None
        p = job.target / 2 ** 256
        return {"por_palpite": p, "palpites_esperados": 1 / p if p else None}

    def ai_context(self) -> dict:
        job = self.current_job
        s = job.summary() if job else None
        if s:
            s = {k: v for k, v in s.items() if k not in ("transacoes", "coinbase_hex", "cabecalho_sem_nonce")}
        ia = self.copilot.status()
        return {
            "modo": MODES[self.config["modo"]],
            "endereco_recompensa": self.config["endereco"] or None,
            "conectado": bool(self.source and self.source.connected),
            "bloco_candidato": s,
            "chance": self.chance(),
            "palpites_da_ia": {"total": ia["ia"]["total"], "melhor": ia["ia"]["melhor"],
                               "media_zeros": ia["ia"]["media_zeros"]},
            "palpites_aleatorios": {"total": ia["aleatorio"]["total"], "melhor": ia["aleatorio"]["melhor"],
                                    "media_zeros": ia["aleatorio"]["media_zeros"]},
            "tokens_gastos": ia["tokens_total"],
            "blocos_encontrados": len(self.found),
            "rede_bitcoin": self.network,
        }

    def status(self) -> dict:
        job = self.current_job
        regtest_status = None
        if self.config["modo"] == "regtest":
            try:
                regtest_status = self.regtest.status()
            except (RPCError, RuntimeError) as e:
                regtest_status = {"rodando": False, "erro": str(e)}
            regtest_status["download"] = regtest.download_state
            regtest_status["instalado"] = regtest.bitcoind_path() is not None
        return {
            "modo": self.config["modo"],
            "conectado": bool(self.source and self.source.connected),
            "ativo": self.source is not None,
            "fonte": self.source.status() if self.source else None,
            "bloco": {k: v for k, v in job.summary().items() if k != "transacoes"} if job else None,
            "chance": self.chance(),
            "testados": self.checked_total,
            "ia": self.copilot.status(),
            "encontrados": [{k: v for k, v in f.items() if k != "bloco_hex"} for f in self.found[:20]],
            "eventos": list(self.events)[:80],
            "rede": self.network,
            "regtest": regtest_status,
            "endereco": self.config["endereco"],
        }

    def current_block_detail(self) -> dict | None:
        return self.current_job.summary() if self.current_job else None

    def shutdown(self) -> None:
        self.disconnect(quiet=True)
        if self.regtest.proc:
            self.regtest.stop()

