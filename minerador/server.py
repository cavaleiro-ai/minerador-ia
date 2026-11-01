"""Servidor web local (só aceita conexões do próprio PC).

Proteções: escuta só em 127.0.0.1, confere o cabeçalho Host (contra DNS
rebinding) e exige um token aleatório em todas as chamadas da API, para que
nenhum site aberto no navegador consiga mexer no minerador.
"""
from __future__ import annotations

import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import regtest
from .ai import AIClient, AIError
from .controller import Controller
from .paths import WEB_DIR
from .rpc import RPCError

TOKEN = secrets.token_urlsafe(24)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

ctrl = Controller()


@asynccontextmanager
async def lifespan(_app):
    yield
    ctrl.shutdown()


app = FastAPI(title="Minerador IA", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.middleware("http")
async def guard(request: Request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"erro": "host não permitido"}, status_code=403)
    if request.url.path.startswith("/api/") and request.headers.get("x-token") != TOKEN:
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    return await call_next(request)


def _fail(e: Exception, status: int = 400):
    raise HTTPException(status_code=status, detail=str(e))


async def _run(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except (ValueError, AIError, RPCError, RuntimeError) as e:
        _fail(e)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse({"erro": exc.detail}, status_code=exc.status_code)


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("__TOKEN__", TOKEN)


# ---- estado e configuração ----
@app.get("/api/status")
async def status():
    return await run_in_threadpool(ctrl.status)


@app.get("/api/config")
async def get_config():
    return ctrl.public_config()


@app.post("/api/config")
async def set_config(request: Request):
    return await _run(ctrl.update_config, await request.json())


@app.post("/api/endereco/validar")
async def validate_address(request: Request):
    return ctrl.address_info(str((await request.json()).get("endereco", "")))


# ---- conexão ----
@app.post("/api/conectar")
async def connect():
    await _run(ctrl.connect)
    return {"ok": True}


@app.post("/api/desconectar")
async def disconnect():
    await _run(ctrl.disconnect)
    return {"ok": True}


@app.get("/api/bloco")
async def block_detail():
    return ctrl.current_block_detail() or {}


# ---- validação manual ----
def _manual_args(body: dict):
    raw = str(body.get("nonce", "")).strip().lower()
    try:
        nonce = int(raw, 16) if raw.startswith("0x") else int(raw)
    except ValueError:
        raise ValueError("Digite o nonce como número inteiro (ou hexadecimal começando com 0x).")
    ntime = body.get("horario")
    return nonce, str(body.get("extranonce", "") or "").strip(), int(ntime) if ntime else None


@app.post("/api/manual/testar")
async def manual_test(request: Request):
    body = await request.json()
    try:
        args = _manual_args(body)
    except ValueError as e:
        _fail(e)
    return await _run(ctrl.manual, *args, send=False)


@app.post("/api/manual/emitir")
async def manual_submit(request: Request):
    body = await request.json()
    try:
        args = _manual_args(body)
    except ValueError as e:
        _fail(e)
    return await _run(ctrl.manual, *args, send=True)


@app.get("/api/verificar-bloco")
async def verify_block(altura: int):
    return await _run(ctrl.verify_real_block, altura)


@app.post("/api/hash-cabecalho")
async def hash_header(request: Request):
    body = await request.json()
    try:
        return ctrl.hash_header(body)
    except (KeyError, ValueError) as e:
        _fail(e)


# ---- IA ----
@app.post("/api/ia/iniciar")
async def ai_start():
    await _run(ctrl.copilot.start)
    return {"ok": True}


@app.post("/api/ia/parar")
async def ai_stop():
    ctrl.copilot.stop()
    return {"ok": True}


@app.get("/api/ia/modelos")
async def ai_models(provedor: str):
    cfg = ctrl.config["ia"]
    def run():
        client = AIClient(provedor, cfg["chaves"].get(provedor, ""), "listar",
                          cfg.get("base_url_compat"))
        return {"modelos": client.list_models()}
    return await _run(run)


@app.post("/api/ia/chat")
async def ai_chat(request: Request):
    message = str((await request.json()).get("mensagem", "")).strip()
    if not message:
        _fail(ValueError("mensagem vazia"))
    return {"resposta": await _run(ctrl.copilot.chat, message)}


@app.post("/api/ia/chat/limpar")
async def ai_chat_clear():
    ctrl.copilot.clear_chat()
    return {"ok": True}


# ---- regtest ----
@app.post("/api/regtest/baixar")
async def regtest_download():
    threading.Thread(target=regtest.download_core, daemon=True).start()
    return {"ok": True}


@app.post("/api/regtest/ligar")
async def regtest_start():
    await _run(ctrl.regtest.start)
    return {"ok": True}


@app.post("/api/regtest/desligar")
async def regtest_stop():
    await _run(ctrl.disconnect)
    await _run(ctrl.regtest.stop)
    return {"ok": True}


@app.post("/api/regtest/transacoes")
async def regtest_txs(request: Request):
    count = int((await request.json()).get("quantidade", 5))
    txids = await _run(ctrl.regtest.create_test_transactions, max(1, min(50, count)))
    ctrl.log(f"Regtest: {len(txids)} transações de teste criadas na mempool.", "ok")
    # O getblocktemplate do Bitcoin Core só inclui transações novas após ~5 s.
    if hasattr(ctrl.source, "request_refresh"):
        threading.Timer(6, ctrl.source.request_refresh).start()
    return {"txids": txids}


@app.post("/api/regtest/preparar")
async def regtest_prepare(request: Request):
    count = int((await request.json()).get("quantidade", 101))
    return await _run(ctrl.regtest_mine_local, count)


@app.post("/api/regtest/resetar")
async def regtest_reset():
    await _run(ctrl.disconnect)
    await _run(ctrl.regtest.reset_chain)
    ctrl.log("Blockchain de teste apagada.")
    return {"ok": True}


# ---- P2P ----
@app.post("/api/p2p/testar")
async def p2p_test():
    from . import p2p
    return await _run(p2p.broadcast_block, None, "main", None, 6)

