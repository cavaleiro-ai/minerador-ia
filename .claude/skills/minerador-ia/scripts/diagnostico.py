#!/usr/bin/env python3
"""Mostra o estado do Minerador IA sem alterar nada e sem exibir segredos.

Uso: python .claude/skills/minerador-ia/scripts/diagnostico.py [--porta 8765]
Só usa a biblioteca padrão, para funcionar mesmo antes da instalação.
Termina com código 1 se alguma linha sair como [erro], e 0 nos demais casos.
"""
import argparse
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


errors = 0


def line(ok, label, detail=""):
    global errors
    errors += ok is False
    mark = {True: "[ok]  ", False: "[erro]", None: "[info]"}[ok]
    print(f"{mark} {label}" + (f": {detail}" if detail else ""))


def check_python():
    v = sys.version_info
    line(v >= (3, 10), "Python usado neste diagnóstico", f"{v.major}.{v.minor}.{v.micro} (mínimo 3.10)")
    if not VENV_PY.exists():
        line(None, "Ambiente .venv", "não existe; o iniciar.bat cria na primeira abertura, ou rode "
                                     "python -m venv .venv e instale o requirements.txt com o Python dele")
        return
    code = "import fastapi, uvicorn, httpx, anthropic, openai"
    r = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True)
    if r.returncode == 0:
        line(True, "Dependências no .venv", "todas importam")
    else:
        erro = (r.stderr.strip().splitlines() or ["erro desconhecido"])[-1]
        line(False, "Dependências no .venv", f"{erro}; rode pip install -r requirements.txt com o Python do .venv")


def check_config():
    path = ROOT / "data" / "config.json"
    if not path.exists():
        line(None, "data/config.json", "ainda não existe; é criado ao salvar algo na interface")
        return
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        line(False, "data/config.json", f"JSON inválido: {e}; o programa usaria os valores padrão")
        return
    ia = c.get("ia", {})
    provedor = ia.get("provedor")
    chaves = ia.get("chaves", {})
    line(None, "Modo salvo", str(c.get("modo")))
    line(None, "Endereço de recompensa", "cadastrado" if c.get("endereco") else "vazio")
    line(None, "Provedor de IA", f"{provedor} | modelo: {ia.get('modelos', {}).get(provedor) or 'vazio'}")
    line(None, "Chave do provedor", "cadastrada" if chaves.get(provedor) else "vazia")
    line(None, "Limites da IA", f"intervalo {ia.get('intervalo')} s, até {ia.get('max_chamadas')} chamadas")


def check_core():
    found = sorted((ROOT / "bitcoin-core").glob("bitcoin-*/bin/bitcoind*"))
    line(None, "Bitcoin Core portátil", found[0].parent.parent.name if found else "não baixado (só o regtest precisa)")


def check_server(port):
    s = socket.socket()
    s.settimeout(1)
    listening = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if not listening:
        line(False, f"Servidor na porta {port}", "parado; no navegador isso aparece como 'Failed to fetch' "
                                                 "ou 'Servidor parado'")
        return
    base = f"http://127.0.0.1:{port}"
    try:
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        token = re.search(r'name="token" content="([^"]+)"', html)
        if not token:
            line(False, f"Porta {port}", "responde, mas a página não é a do Minerador IA")
            return
        req = urllib.request.Request(base + "/api/status", headers={"X-Token": token.group(1)})
        st = json.load(urllib.request.urlopen(req, timeout=20))
    except (urllib.error.URLError, OSError, ValueError) as e:
        line(False, f"Porta {port}", f"resposta inesperada: {e}")
        return
    line(True, f"Servidor na porta {port}", "respondendo")
    fonte = st.get("fonte") or {}
    line(None, "Conexão com a rede", "conectado" if st["conectado"] else
         (f"erro: {fonte.get('erro')}" if fonte.get("erro") else "desconectado"))
    bloco = st.get("bloco")
    if bloco:
        line(None, "Bloco candidato", f"altura {bloco['altura']}, {bloco['num_transacoes']} transações, "
                                      f"{bloco['zeros_necessarios']} bits zero necessários")
    ia = st["ia"]
    line(None, "IA", f"{'RODANDO (gasta dinheiro)' if ia['rodando'] else 'parada'}, "
                     f"{ia['chamadas']} de {ia['limite_chamadas']} chamadas nesta execução")
    if ia.get("ultimo_erro"):
        line(False, "Último erro da IA", ia["ultimo_erro"])
    erros = [e["msg"] for e in st["eventos"] if e["nivel"] == "erro"][:5]
    for msg in erros:
        line(None, "Erro recente no registro", msg[:160])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--porta", type=int, default=8765)
    args = parser.parse_args()
    print(f"Projeto: {ROOT.name}")
    check_python()
    check_config()
    check_core()
    check_server(args.porta)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
