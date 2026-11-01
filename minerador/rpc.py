"""Cliente JSON-RPC mínimo para o Bitcoin Core (bitcoind)."""
from __future__ import annotations

import itertools
from pathlib import Path

import httpx


class RPCError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class RPCClient:
    """Fala com o bitcoind via HTTP. Aceita usuário/senha ou arquivo .cookie."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8332, user: str = "",
                 password: str = "", cookie_file: str | Path | None = None,
                 timeout: float = 30.0):
        self.url = f"http://{host}:{port}"
        self.user = user
        self.password = password
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self._ids = itertools.count(1)
        self._http = httpx.Client(timeout=timeout)

    def _auth(self) -> tuple[str, str]:
        if self.cookie_file:
            # O cookie é recriado a cada vez que o bitcoind inicia, então lemos sempre.
            user, _, password = self.cookie_file.read_text().strip().partition(":")
            return user, password
        return self.user, self.password

    def call(self, method: str, *params, wallet: str | None = None):
        url = self.url + (f"/wallet/{wallet}" if wallet else "")
        payload = {"jsonrpc": "1.0", "id": next(self._ids), "method": method, "params": list(params)}
        try:
            resp = self._http.post(url, json=payload, auth=self._auth())
        except FileNotFoundError:
            raise RPCError("Arquivo .cookie não encontrado (o nó está rodando?)")
        except httpx.HTTPError as e:
            raise RPCError(f"Sem conexão com o nó em {self.url}: {e}")
        if resp.status_code == 401:
            raise RPCError("Usuário/senha RPC incorretos (HTTP 401)")
        try:
            data = resp.json()
        except ValueError:
            raise RPCError(f"Resposta inválida do nó (HTTP {resp.status_code})")
        if data.get("error"):
            err = data["error"]
            raise RPCError(err.get("message", str(err)), err.get("code"))
        return data["result"]

    def close(self):
        self._http.close()
