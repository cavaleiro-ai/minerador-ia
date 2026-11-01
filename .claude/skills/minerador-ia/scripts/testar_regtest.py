#!/usr/bin/env python3
"""Prova, sem gastar nada, que o programa monta blocos aceitos por um Bitcoin Core real.

Copia o código para uma pasta temporária e sobe ali um servidor próprio, então não toca em
data/ nem usa chaves ou APIs de IA. Baixa o Bitcoin Core na cópia se ele não existir no projeto.

Uso: python .claude/skills/minerador-ia/scripts/testar_regtest.py
Precisa do .venv já instalado. Termina com código 0 se o bloco for aceito.
"""
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
RPC_PORT, P2P_PORT = 18443, 18444
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def port_in_use(port):
    s = socket.socket()
    s.settimeout(1)
    in_use = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    return in_use


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api:
    def __init__(self, base):
        self.base = base
        self.token = None

    def wait_up(self, proc):
        for _ in range(120):
            if proc.poll() is not None:
                raise SystemExit(f"O servidor encerrou ao iniciar (código {proc.returncode}).")
            try:
                html = urllib.request.urlopen(self.base + "/", timeout=2).read().decode("utf-8")
                self.token = re.search(r'name="token" content="([^"]+)"', html).group(1)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        raise SystemExit("O servidor não respondeu em 60 s.")

    def call(self, path, body=None, timeout=180):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers={
            "X-Token": self.token, "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{path} falhou (HTTP {e.code}): {e.read().decode('utf-8', 'replace')[:300]}")


def main():
    if not VENV_PY.exists():
        raise SystemExit("Falta o .venv. Abra o iniciar.bat uma vez ou crie o ambiente (veja o README).")
    if port_in_use(RPC_PORT) or port_in_use(P2P_PORT):
        raise SystemExit(f"As portas {RPC_PORT}/{P2P_PORT} estão em uso: já há um nó regtest ligado. "
                         "Desligue-o com o botão 'Desligar nó' e rode de novo.")

    tmp = Path(tempfile.mkdtemp(prefix="minerador-regtest-"))
    copia = tmp / "copia"
    copia.mkdir()
    for name in ("minerador", "web"):
        shutil.copytree(ROOT / name, copia / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "run.py", copia / "run.py")
    if (ROOT / "bitcoin-core").is_dir():
        shutil.copytree(ROOT / "bitcoin-core", copia / "bitcoin-core")

    port = free_port()
    api = Api(f"http://127.0.0.1:{port}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    srv = subprocess.Popen([str(VENV_PY), "run.py", "--porta", str(port), "--sem-navegador"], cwd=copia, env=env)
    aceito = False
    try:
        api.wait_up(srv)
        print("1. Servidor temporário no ar (sem chaves, em pasta temporária).")

        api.call("/api/config", {"modo": "regtest"})
        if not any((copia / "bitcoin-core").glob("bitcoin-*/bin/bitcoind*")):
            print("   Baixando o Bitcoin Core e conferindo o SHA256…")
            api.call("/api/regtest/baixar", {})
            for _ in range(600):
                rt = api.call("/api/status")["regtest"]
                if rt.get("instalado"):
                    break
                if rt.get("download", {}).get("error"):
                    raise SystemExit(f"Download falhou: {rt['download']['error']}")
                time.sleep(1)
            else:
                raise SystemExit("O download não terminou em 10 minutos.")
        api.call("/api/conectar", {})
        print("2. Conectado ao nó regtest.")

        r = api.call("/api/regtest/preparar", {"quantidade": 101})
        rt = api.call("/api/status")["regtest"]
        print(f"3. {r['aceitos']} blocos de preparação aceitos; altura {rt['altura']}, "
              f"saldo disponível {rt['saldo_disponivel']} BTC de teste.")

        txids = api.call("/api/regtest/transacoes", {"quantidade": 5})["txids"]
        for _ in range(30):                       # o getblocktemplate leva alguns segundos
            time.sleep(1)
            bloco = api.call("/api/status")["bloco"]
            if bloco and bloco["num_transacoes"] >= 1 + len(txids):
                break
        else:
            raise SystemExit("As transações de teste não entraram no bloco candidato em 30 s.")
        altura = bloco["altura"]
        print(f"4. Bloco candidato {altura} com {bloco['num_transacoes']} transações.")

        for tentativa in range(1, 200):
            nonce = random.getrandbits(32)
            if api.call("/api/manual/testar", {"nonce": str(nonce)})["valido"]:
                envio = api.call("/api/manual/emitir", {"nonce": str(nonce)})
                if envio.get("valido") and envio.get("envio", {}).get("ok"):
                    aceito = True
                    print(f"5. Nonce válido na tentativa {tentativa}. Resposta: {envio['envio']['detalhe']}.")
                    break
        if not aceito:
            raise SystemExit("Nenhum envio de bloco deu certo em 200 tentativas.")

        time.sleep(3)
        st = api.call("/api/status")
        nova = st["regtest"]["altura"]
        if nova != altura:
            raise SystemExit(f"O nó está na altura {nova}, mas o bloco era o {altura}.")
        print(f"6. O nó confirma a altura {nova}; mempool com {st['regtest']['mempool']} transações.")
        print("RESULTADO: bloco com transações aceito por um Bitcoin Core real.")
    finally:
        try:
            api.call("/api/regtest/desligar", {}, timeout=60)
        except (SystemExit, OSError, TypeError):
            pass
        srv.terminate()
        try:
            srv.wait(15)
        except subprocess.TimeoutExpired:
            srv.kill()
        time.sleep(1)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if aceito else 1


if __name__ == "__main__":
    sys.exit(main())
