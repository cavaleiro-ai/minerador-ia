"""Nó Bitcoin Core local em modo regtest.

O regtest é uma blockchain privada que roda só no seu PC. Ela usa exatamente as
mesmas regras de consenso da rede principal, mas com dificuldade mínima. Serve
para provar que o minerador monta blocos válidos (com transações), que o nó
aceita esses blocos e que a recompensa cai na carteira.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
import zipfile

import httpx

from .paths import CORE_DIR, REGTEST_DIR
from .rpc import RPCClient, RPCError

CORE_VERSION = "31.1"
ZIP_NAME = f"bitcoin-{CORE_VERSION}-win64.zip"
BASE_URL = f"https://bitcoincore.org/bin/bitcoin-core-{CORE_VERSION}/"
RPC_PORT = 18443
P2P_PORT = 18444
WALLET = "minerador"

download_state = {"status": "parado", "percent": 0, "error": None}
_download_lock = threading.Lock()


def bitcoind_path():
    for p in sorted(CORE_DIR.glob("bitcoin-*/bin/bitcoind.exe")):
        return p
    return None


def download_core() -> None:
    """Baixa o zip oficial do Bitcoin Core, confere o SHA256 e extrai em ./bitcoin-core."""
    if not _download_lock.acquire(blocking=False):
        return  # já está baixando
    try:
        if sys.platform != "win32":
            raise RuntimeError("Download automático disponível só para Windows. "
                               "Instale o Bitcoin Core manualmente.")
        if bitcoind_path():
            download_state.update(status="pronto", percent=100, error=None)
            return
        CORE_DIR.mkdir(exist_ok=True)
        download_state.update(status="baixando lista de hashes", percent=0, error=None)
        sums = httpx.get(BASE_URL + "SHA256SUMS", timeout=30, follow_redirects=True).text
        expected = next((line.split()[0] for line in sums.splitlines()
                         if line.strip().endswith(ZIP_NAME)), None)
        if not expected:
            raise RuntimeError(f"{ZIP_NAME} não está no SHA256SUMS oficial")

        zip_path = CORE_DIR / ZIP_NAME
        sha = hashlib.sha256()
        download_state["status"] = "baixando Bitcoin Core"
        with httpx.stream("GET", BASE_URL + ZIP_NAME, timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or 1
            done = 0
            with open(zip_path, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    download_state["percent"] = min(99, done * 100 // total)

        if sha.hexdigest() != expected:
            zip_path.unlink(missing_ok=True)
            raise RuntimeError("SHA256 do arquivo baixado não confere! Download descartado.")

        download_state["status"] = "extraindo"
        with zipfile.ZipFile(zip_path) as z:
            members = [m for m in z.namelist() if m.endswith(("bitcoind.exe", "bitcoin-cli.exe"))]
            z.extractall(CORE_DIR, members)
        zip_path.unlink(missing_ok=True)
        download_state.update(status="pronto", percent=100)
    except Exception as e:  # noqa: BLE001 - erro vai para a interface
        download_state.update(status="erro", error=str(e))
    finally:
        _download_lock.release()


class RegtestNode:
    """Liga, desliga e opera o bitcoind em regtest."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.rpc = RPCClient(port=RPC_PORT, cookie_file=REGTEST_DIR / "regtest" / ".cookie",
                             timeout=60)
        self.address: str | None = None

    # ---- ciclo de vida -------------------------------------------------
    def is_running(self) -> bool:
        try:
            self.rpc.call("getblockcount")
            return True
        except RPCError:
            return False

    def start(self) -> None:
        if self.is_running():
            self._ensure_wallet()
            return
        exe = bitcoind_path()
        if not exe:
            raise RuntimeError("Bitcoin Core ainda não foi baixado.")
        REGTEST_DIR.mkdir(parents=True, exist_ok=True)
        args = [
            str(exe), "-regtest", f"-datadir={REGTEST_DIR}", "-server=1",
            "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1", f"-rpcport={RPC_PORT}",
            f"-port={P2P_PORT}", "-listen=1", "-bind=127.0.0.1", "-dnsseed=0", "-fallbackfee=0.0002",
            "-printtoconsole=0",
        ]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(args, creationflags=flags,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"bitcoind encerrou ao iniciar (código {self.proc.returncode}). "
                                   f"Veja {REGTEST_DIR / 'regtest' / 'debug.log'}")
            try:
                self.rpc.call("getblockchaininfo")
                break
            except RPCError as e:
                if e.code == -28:  # ainda carregando
                    pass
                time.sleep(0.5)
        else:
            raise RuntimeError("bitcoind não respondeu em 90 s")
        self._ensure_wallet()

    def stop(self) -> None:
        try:
            self.rpc.call("stop")
        except RPCError:
            pass
        if self.proc:
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        self.address = None

    def _ensure_wallet(self) -> None:
        loaded = self.rpc.call("listwallets")
        if WALLET not in loaded:
            try:
                self.rpc.call("loadwallet", WALLET)
            except RPCError:
                self.rpc.call("createwallet", WALLET)
        if not self.address:
            self.address = self.rpc.call("getnewaddress", "recompensa", "bech32", wallet=WALLET)

    # ---- consultas e ações --------------------------------------------
    def status(self) -> dict:
        if not self.is_running():
            return {"rodando": False}
        self._ensure_wallet()
        bal = self.rpc.call("getbalances", wallet=WALLET)["mine"]
        return {
            "rodando": True,
            "altura": self.rpc.call("getblockcount"),
            "mempool": self.rpc.call("getmempoolinfo")["size"],
            "endereco": self.address,
            "saldo_disponivel": bal["trusted"],
            "saldo_imaturo": bal["immature"],
            "saldo_pendente": bal["untrusted_pending"],
        }

    def create_test_transactions(self, count: int = 5) -> list[str]:
        """Envia algumas transações da carteira para endereços novos, enchendo a mempool."""
        import random
        txids = []
        for _ in range(count):
            dest = self.rpc.call("getnewaddress", "teste", "bech32", wallet=WALLET)
            amount = round(random.uniform(0.1, 2.0), 8)
            txids.append(self.rpc.call("sendtoaddress", dest, amount, wallet=WALLET))
        return txids

    def reset_chain(self) -> None:
        """Apaga a blockchain de teste (a carteira também) e começa do zero."""
        import shutil
        self.stop()
        shutil.rmtree(REGTEST_DIR, ignore_errors=True)
