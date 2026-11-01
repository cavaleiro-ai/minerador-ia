"""Transmissão de blocos direto pela rede P2P do Bitcoin, sem nó próprio e sem pool.

O minerador se conecta a nós públicos (descobertos pelos DNS seeds oficiais),
faz o aperto de mão do protocolo (version/verack) e envia a mensagem "block".
Cada nó que recebe o bloco valida e repassa para os outros.
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .btc import sha256d, varint

MAGIC = {
    "main": bytes.fromhex("f9beb4d9"),
    "test": bytes.fromhex("0b110907"),
    "regtest": bytes.fromhex("fabfb5da"),
}
DEFAULT_PORT = {"main": 8333, "test": 18333, "regtest": 18444}
DNS_SEEDS = [
    "seed.bitcoin.sipa.be", "dnsseed.bluematt.me", "seed.bitcoin.jonasschnelli.ch",
    "seed.btc.petertodd.net", "seed.bitcoin.sprovoost.nl", "dnsseed.emzy.de",
    "seed.bitcoin.wiz.biz", "seed.mainnet.achownodes.xyz",
]
PROTOCOL_VERSION = 70016
USER_AGENT = b"/MineradorIA:1.0/"


def _message(magic: bytes, command: str, payload: bytes) -> bytes:
    cmd = command.encode().ljust(12, b"\0")
    return magic + cmd + struct.pack("<I", len(payload)) + sha256d(payload)[:4] + payload


def _net_addr(ip: str = "0.0.0.0", port: int = 0) -> bytes:
    try:
        raw = socket.inet_pton(socket.AF_INET6, ip) if ":" in ip else \
            b"\0" * 10 + b"\xff\xff" + socket.inet_aton(ip)
    except OSError:
        raw = b"\0" * 16
    return struct.pack("<Q", 0) + raw + struct.pack(">H", port)


def _version_payload(peer_ip: str, peer_port: int, start_height: int) -> bytes:
    return (struct.pack("<iQq", PROTOCOL_VERSION, 0, int(time.time()))
            + _net_addr(peer_ip, peer_port) + _net_addr()
            + os.urandom(8) + varint(len(USER_AGENT)) + USER_AGENT
            + struct.pack("<i", start_height) + b"\0")


class Peer:
    def __init__(self, host: str, port: int, network: str = "main", timeout: float = 8.0):
        self.host, self.port = host, port
        self.magic = MAGIC[network]
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.user_agent = ""
        self.height = 0

    def send(self, command: str, payload: bytes = b"") -> None:
        self.sock.sendall(_message(self.magic, command, payload))

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("o nó fechou a conexão")
            buf += chunk
        return buf

    def recv(self) -> tuple[str, bytes]:
        head = self._read_exact(24)
        if head[:4] != self.magic:
            raise ConnectionError("rede errada (magic diferente)")
        command = head[4:16].rstrip(b"\0").decode(errors="replace")
        length = struct.unpack("<I", head[16:20])[0]
        if length > 32 * 1024 * 1024:
            raise ConnectionError("mensagem grande demais")
        payload = self._read_exact(length)
        if sha256d(payload)[:4] != head[20:24]:
            raise ConnectionError("checksum inválido")
        return command, payload

    def handshake(self, start_height: int = 0) -> None:
        self.send("version", _version_payload(self.host, self.port, start_height))
        got_version = got_verack = False
        deadline = time.time() + 10
        while not (got_version and got_verack):
            if time.time() > deadline:
                raise TimeoutError("sem resposta ao handshake")
            cmd, payload = self.recv()
            if cmd == "version":
                got_version = True
                ua_len = payload[80]
                self.user_agent = payload[81:81 + ua_len].decode(errors="replace")
                self.height = struct.unpack_from("<i", payload, 81 + ua_len)[0]
                self.send("verack")
            elif cmd == "verack":
                got_verack = True
            elif cmd == "ping":
                self.send("pong", payload)

    def drain(self, seconds: float) -> None:
        """Escuta um pouco (respondendo pings) para o nó ter tempo de processar."""
        end = time.time() + seconds
        self.sock.settimeout(0.5)
        while time.time() < end:
            try:
                cmd, payload = self.recv()
                if cmd == "ping":
                    self.send("pong", payload)
            except socket.timeout:
                continue
            except (OSError, ConnectionError):
                break

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def discover_peers(network: str = "main", limit: int = 24) -> list[tuple[str, int]]:
    if network != "main":
        return []
    port = DEFAULT_PORT[network]
    found: list[tuple[str, int]] = []
    lock = threading.Lock()

    def resolve(seed: str):
        try:
            infos = socket.getaddrinfo(seed, port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            return
        with lock:
            for info in infos:
                addr = (info[4][0], port)
                if addr not in found:
                    found.append(addr)

    with ThreadPoolExecutor(len(DNS_SEEDS)) as ex:
        list(ex.map(resolve, DNS_SEEDS))
    return found[:limit]


def _deliver(host: str, port: int, network: str, block: bytes | None, height: int) -> dict:
    result = {"no": f"{host}:{port}", "ok": False}
    peer = None
    try:
        peer = Peer(host, port, network)
        peer.handshake(height)
        result.update(versao=peer.user_agent, altura=peer.height)
        if block is not None:
            peer.send("block", block)
            peer.drain(3)
        result["ok"] = True
    except Exception as e:  # noqa: BLE001
        result["erro"] = str(e) or e.__class__.__name__
    finally:
        if peer:
            peer.close()
    return result


def broadcast_block(block: bytes | None, network: str = "main", peers=None, max_peers: int = 10,
                    height: int = 0) -> dict:
    """Envia o bloco para vários nós em paralelo. Com block=None só testa a conexão."""
    peers = peers or discover_peers(network, max_peers * 2)
    if not peers:
        return {"ok": False, "enviados": 0, "tentados": 0, "resultados": [],
                "erro": "nenhum nó encontrado pelos DNS seeds"}
    peers = peers[:max_peers]
    with ThreadPoolExecutor(len(peers)) as ex:
        results = list(ex.map(lambda p: _deliver(p[0], p[1], network, block, height), peers))
    sent = sum(r["ok"] for r in results)
    return {"ok": sent > 0, "enviados": sent, "tentados": len(peers), "resultados": results}
