#!/usr/bin/env python3
"""Confere o que iria para o GitHub e procura segredos, sem nunca exibir os valores.

Usa a mesma lista do Git (respeita o .gitignore). Funciona mesmo antes do `git init`, com um
repositório temporário fora do projeto. Procura padrões de chaves e também os valores reais
de data/config.json. Não altera nada no projeto.

Uso: python .claude/skills/minerador-ia/scripts/verificar_publicacao.py
Termina com código 0 se estiver tudo limpo e 1 se houver problema.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PATTERNS = {
    "chave xAI": rb"xai-[A-Za-z0-9]{20,}",
    "chave Anthropic": rb"sk-ant-[A-Za-z0-9_\-]{20,}",
    "chave OpenAI ou similar": rb"\bsk-[A-Za-z0-9_\-]{20,}",
    "token GitHub": rb"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "token Hugging Face": rb"\bhf_[A-Za-z0-9]{30,}",
    "chave Groq": rb"\bgsk_[A-Za-z0-9]{30,}",
    "chave AWS": rb"\bAKIA[0-9A-Z]{16}\b",
    "chave privada": rb"-----BEGIN [A-Z ]*PRIVATE KEY",
}
FORBIDDEN = (re.compile(r"^data/"), re.compile(r"^\.venv/"), re.compile(r"^bitcoin-core/"),
             re.compile(r"(^|/)__pycache__/"), re.compile(r"\.(pyc|dat|ldb|cookie)$"),
             re.compile(r"(^|/)\.env(\.|$)"), re.compile(r"(^|/)settings\.local\.json$"))
MAX_BYTES = 50 * 1024 * 1024


def tracked_files():
    if (ROOT / ".git").exists():
        cmd = ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        return [f for f in subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8").split("\0") if f]
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_DIR": str(Path(tmp) / "repo"), "GIT_WORK_TREE": str(ROOT)}
        subprocess.run(["git", "init", "-q"], env=env, check=True, capture_output=True)
        cmd = ["git", "ls-files", "--others", "--exclude-standard", "-z"]
        out = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, check=True).stdout
    return [f for f in out.decode("utf-8").split("\0") if f]


def local_values():
    """Segredos e dados pessoais do config local. Ficam só na memória deste script."""
    values = {}
    try:
        c = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return values
    for p, v in c.get("ia", {}).get("chaves", {}).items():
        if v:
            values[f"sua chave de API ({p})"] = v.encode()
    no = c.get("no", {})
    if no.get("senha"):
        values["sua senha RPC"] = no["senha"].encode()
    if c.get("endereco"):
        values["seu endereço de carteira"] = c["endereco"].encode()
    return values


def main():
    files = tracked_files()
    problems = []
    values = local_values()
    total = 0
    this_script = Path(__file__).resolve()
    for rel in files:
        path = ROOT / rel
        rel = rel.replace("\\", "/")
        if any(rx.search(rel) for rx in FORBIDDEN):
            problems.append(f"{rel}: este arquivo não deveria ser publicado")
        try:
            data = path.read_bytes()
        except OSError:
            continue
        total += len(data)
        if len(data) > MAX_BYTES:
            problems.append(f"{rel}: maior que 50 MB")
        for label, value in values.items():
            if value in data:
                problems.append(f"{rel}: contém {label}")
        if path.resolve() == this_script:
            continue                        # os padrões acima aparecem no próprio script
        for label, rx in PATTERNS.items():
            if re.search(rx, data):
                problems.append(f"{rel}: parece conter {label}")

    print(f"{len(files)} arquivos seriam publicados ({total / 1024:.0f} KB):")
    for rel in sorted(files):
        print(f"  {rel}")
    if not (ROOT / ".gitignore").exists():
        problems.append(".gitignore não existe")
    if problems:
        print(f"\nPROBLEMAS ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nTudo limpo: nenhum segredo ou arquivo proibido na lista.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
