"""Caminhos usados pelo aplicativo (tudo fica dentro da pasta do projeto)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
FOUND_FILE = DATA_DIR / "blocos_encontrados.json"
USAGE_FILE = DATA_DIR / "uso_ia.json"
REGTEST_DIR = DATA_DIR / "regtest"
CORE_DIR = ROOT / "bitcoin-core"

DATA_DIR.mkdir(exist_ok=True)
