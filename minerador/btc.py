"""Núcleo Bitcoin escrito do zero: hashes, serialização, endereços, coinbase,
árvore de merkle e cabeçalho de bloco.

Convenções de bytes (a parte mais traiçoeira do Bitcoin):
- Hashes (txid, hash do bloco) são exibidos invertidos em relação à ordem
  "interna" usada dentro do cabeçalho e da árvore de merkle.
- Inteiros no cabeçalho (versão, horário, bits, nonce) são little-endian.
"""
from __future__ import annotations

import hashlib
import struct

DIFF1_TARGET = 0xFFFF << 208          # alvo da dificuldade 1
MAX_TARGET = (1 << 256) - 1
COIN = 100_000_000                     # satoshis por BTC


# --------------------------------------------------------------------------
# Hashes e números
# --------------------------------------------------------------------------
def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def hash_to_int(digest: bytes) -> int:
    """Valor numérico de um hash (é esse número que precisa ficar abaixo do alvo)."""
    return int.from_bytes(digest, "little")


def hash_to_hex(digest: bytes) -> str:
    """Hash no formato exibido em exploradores (bytes invertidos)."""
    return digest[::-1].hex()


def hex_to_hash(display_hex: str) -> bytes:
    return bytes.fromhex(display_hex)[::-1]


def bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def target_to_difficulty(target: int) -> float:
    return DIFF1_TARGET / target if target else float("inf")


def difficulty_to_target(difficulty: float) -> int:
    if difficulty <= 0:
        return MAX_TARGET
    return min(MAX_TARGET, int(DIFF1_TARGET / difficulty))


def target_to_bits(target: int) -> int:
    """Formato compacto (igual ao GetCompact do Bitcoin Core)."""
    size = (target.bit_length() + 7) // 8
    if size <= 3:
        compact = target << (8 * (3 - size))
    else:
        compact = target >> (8 * (size - 3))
    if compact & 0x00800000:
        compact >>= 8
        size += 1
    return compact | (size << 24)


POW_LIMIT_MAIN = (1 << 224) - 1
RETARGET_INTERVAL = 2016
TARGET_TIMESPAN = 14 * 24 * 60 * 60


def next_work_required(last_bits: int, first_block_time: int, last_block_time: int,
                       pow_limit: int = POW_LIMIT_MAIN) -> int:
    """Novo alvo no ajuste de dificuldade (a cada 2016 blocos), como no pow.cpp."""
    timespan = last_block_time - first_block_time
    timespan = max(TARGET_TIMESPAN // 4, min(TARGET_TIMESPAN * 4, timespan))
    new_target = bits_to_target(last_bits) * timespan // TARGET_TIMESPAN
    return target_to_bits(min(new_target, pow_limit))


def block_subsidy(height: int, halving_interval: int = 210_000) -> int:
    halvings = height // halving_interval
    return 0 if halvings >= 64 else (50 * COIN) >> halvings


def hash_difficulty(digest: bytes) -> float:
    """Quão "difícil" foi este hash. Um bloco precisa de valor >= dificuldade da rede."""
    value = hash_to_int(digest)
    return DIFF1_TARGET / value if value else float("inf")


def leading_zero_bits(digest: bytes) -> int:
    value = hash_to_int(digest)
    return 256 - value.bit_length()


# --------------------------------------------------------------------------
# Serialização
# --------------------------------------------------------------------------
def varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos]
    if first < 0xFD:
        return first, pos + 1
    if first == 0xFD:
        return struct.unpack_from("<H", data, pos + 1)[0], pos + 3
    if first == 0xFE:
        return struct.unpack_from("<I", data, pos + 1)[0], pos + 5
    return struct.unpack_from("<Q", data, pos + 1)[0], pos + 9


def push_data(data: bytes) -> bytes:
    n = len(data)
    if n < 0x4C:
        return bytes([n]) + data
    if n <= 0xFF:
        return b"\x4c" + bytes([n]) + data
    if n <= 0xFFFF:
        return b"\x4d" + struct.pack("<H", n) + data
    return b"\x4e" + struct.pack("<I", n) + data


def scriptnum(n: int) -> bytes:
    """Serialização CScriptNum (little-endian mínimo com bit de sinal)."""
    if n == 0:
        return b""
    negative = n < 0
    a = abs(n)
    out = bytearray()
    while a:
        out.append(a & 0xFF)
        a >>= 8
    if out[-1] & 0x80:
        out.append(0x80 if negative else 0x00)
    elif negative:
        out[-1] |= 0x80
    return bytes(out)


def script_int(n: int) -> bytes:
    """Equivalente a `CScript() << n` do Bitcoin Core (usado na altura do BIP34)."""
    if n == 0:
        return b"\x00"
    if n == -1 or 1 <= n <= 16:
        return bytes([0x50 + n])
    return push_data(scriptnum(n))


def decode_script_int(script: bytes) -> tuple[int | None, int]:
    """Lê o primeiro número empurrado no script. Retorna (valor, bytes consumidos)."""
    if not script:
        return None, 0
    op = script[0]
    if op == 0x00:
        return 0, 1
    if 0x51 <= op <= 0x60:
        return op - 0x50, 1
    if 1 <= op <= 8 and len(script) > op:
        raw = script[1:1 + op]
        value = int.from_bytes(raw, "little")
        if raw[-1] & 0x80:
            value = -(value & ~(0x80 << (8 * (len(raw) - 1))))
        return value, 1 + op
    return None, 0


# --------------------------------------------------------------------------
# Endereços (Base58Check, Bech32, Bech32m)
# --------------------------------------------------------------------------
NETWORKS = {
    "main": {"hrp": "bc", "p2pkh": 0x00, "p2sh": 0x05, "nome": "Mainnet (rede principal)"},
    "test": {"hrp": "tb", "p2pkh": 0x6F, "p2sh": 0xC4, "nome": "Testnet/Signet"},
    "regtest": {"hrp": "bcrt", "p2pkh": 0x6F, "p2sh": 0xC4, "nome": "Regtest (teste local)"},
}

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST, _BECH32M_CONST = 1, 0x2BC830A3


def b58encode_check(payload: bytes) -> str:
    data = payload + sha256d(payload)[:4]
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def b58decode_check(s: str) -> bytes:
    n = 0
    for c in s:
        if c not in _B58:
            raise ValueError(f"caractere inválido em Base58: {c!r}")
        n = n * 58 + _B58.index(c)
    pad = len(s) - len(s.lstrip("1"))
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    data = b"\0" * pad + raw
    if len(data) < 5 or sha256d(data[:-4])[:4] != data[-4:]:
        raise ValueError("checksum Base58 inválido")
    return data[:-4]


def _bech32_polymod(values) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frombits: int, tobits: int, pad: bool = True):
    acc = bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or value >> frombits:
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def bech32_decode_segwit(addr: str) -> tuple[str, int, bytes]:
    """Decodifica endereço segwit. Retorna (hrp, versão do witness, programa)."""
    if addr.lower() != addr and addr.upper() != addr:
        raise ValueError("endereço mistura maiúsculas e minúsculas")
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        raise ValueError("formato Bech32 inválido")
    hrp, data_part = addr[:pos], addr[pos + 1:]
    if any(c not in _BECH32 for c in data_part):
        raise ValueError("caractere inválido em Bech32")
    data = [_BECH32.index(c) for c in data_part]
    const = _bech32_polymod(_hrp_expand(hrp) + data)
    if const not in (_BECH32_CONST, _BECH32M_CONST):
        raise ValueError("checksum Bech32 inválido (endereço digitado errado?)")
    witver = data[0]
    prog = _convertbits(data[1:-6], 5, 8, False)
    if prog is None or not 2 <= len(prog) <= 40 or witver > 16:
        raise ValueError("programa witness inválido")
    if witver == 0 and len(prog) not in (20, 32):
        raise ValueError("tamanho inválido para segwit v0")
    if (witver == 0) != (const == _BECH32_CONST):
        raise ValueError("variante Bech32/Bech32m errada para esta versão")
    return hrp, witver, bytes(prog)


def bech32_encode_segwit(hrp: str, witver: int, prog: bytes) -> str:
    data = [witver] + _convertbits(prog, 8, 5)
    const = _BECH32_CONST if witver == 0 else _BECH32M_CONST
    polymod = _bech32_polymod(_hrp_expand(hrp) + data + [0] * 6) ^ const
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH32[d] for d in data + checksum)


def address_to_script(addr: str) -> tuple[bytes, str, str]:
    """Converte endereço em scriptPubKey. Retorna (script, rede, tipo)."""
    addr = addr.strip()
    if not addr:
        raise ValueError("endereço vazio")
    lower = addr.lower()
    for net, p in sorted(NETWORKS.items(), key=lambda kv: -len(kv[1]["hrp"])):
        if lower.startswith(p["hrp"] + "1"):
            hrp, witver, prog = bech32_decode_segwit(addr)
            if hrp != p["hrp"]:
                continue
            op = 0x00 if witver == 0 else 0x50 + witver
            kind = {(0, 20): "P2WPKH (SegWit)", (0, 32): "P2WSH (SegWit)",
                    (1, 32): "P2TR (Taproot)"}.get((witver, len(prog)), f"witness v{witver}")
            return bytes([op]) + push_data(prog), net, kind
    payload = b58decode_check(addr)
    if len(payload) != 21:
        raise ValueError("tamanho inválido de endereço Base58")
    ver, h160 = payload[0], payload[1:]
    if ver in (0x00, 0x6F):
        return b"\x76\xa9\x14" + h160 + b"\x88\xac", "main" if ver == 0 else "test", "P2PKH (legado)"
    if ver in (0x05, 0xC4):
        return b"\xa9\x14" + h160 + b"\x87", "main" if ver == 5 else "test", "P2SH"
    raise ValueError("versão de endereço desconhecida")


def script_to_address(script: bytes, network: str = "main") -> str | None:
    p = NETWORKS.get(network, NETWORKS["main"])
    if len(script) == 25 and script[:3] == b"\x76\xa9\x14" and script[23:] == b"\x88\xac":
        return b58encode_check(bytes([p["p2pkh"]]) + script[3:23])
    if len(script) == 23 and script[:2] == b"\xa9\x14" and script[22] == 0x87:
        return b58encode_check(bytes([p["p2sh"]]) + script[2:22])
    if 4 <= len(script) <= 42 and (script[0] == 0 or 0x51 <= script[0] <= 0x60) \
            and script[1] == len(script) - 2:
        witver = 0 if script[0] == 0 else script[0] - 0x50
        return bech32_encode_segwit(p["hrp"], witver, script[2:])
    return None


def is_witness_commitment(script: bytes) -> bool:
    return len(script) >= 38 and script[:6] == bytes.fromhex("6a24aa21a9ed")


def witness_commitment_script(wtxids: list[bytes]) -> bytes:
    """Saída OP_RETURN do BIP141. `wtxids` NÃO inclui a coinbase (que conta como zeros)."""
    root = merkle_root([b"\0" * 32] + list(wtxids))
    return bytes.fromhex("6a24aa21a9ed") + sha256d(root + b"\0" * 32)


def tx_ids(raw: bytes) -> tuple[bytes, bytes]:
    """Calcula (txid, wtxid) de uma transação serializada. O txid ignora o witness."""
    wtxid = sha256d(raw)
    if len(raw) > 6 and raw[4] == 0 and raw[5] == 1:
        pos = 6
        n_in, pos = read_varint(raw, pos)
        for _ in range(n_in):
            pos += 36
            slen, pos = read_varint(raw, pos)
            pos += slen + 4
        n_out, pos = read_varint(raw, pos)
        for _ in range(n_out):
            pos += 8
            slen, pos = read_varint(raw, pos)
            pos += slen
        return sha256d(raw[:4] + raw[6:pos] + raw[-4:]), wtxid
    return wtxid, wtxid


# --------------------------------------------------------------------------
# Transação coinbase
# --------------------------------------------------------------------------
def serialize_output(value: int, script: bytes) -> bytes:
    return struct.pack("<q", value) + varint(len(script)) + script


def build_coinbase(height: int, outputs: list[tuple[int, bytes]], extranonce_size: int = 8,
                   tag: bytes = b"/MineradorIA/") -> tuple[bytes, bytes]:
    """Monta a coinbase dividida em (coinb1, coinb2). O extranonce vai entre as duas.

    scriptSig = altura (BIP34) + extranonce + etiqueta.
    nLockTime = altura-1 e nSequence != 0xffffffff, como pede o BIP54 (inofensivo hoje).
    """
    height_push = script_int(height)
    tag_push = push_data(tag)
    script_len = len(height_push) + 1 + extranonce_size + len(tag_push)
    if not 2 <= script_len <= 100:
        raise ValueError("scriptSig da coinbase fora do limite de 2..100 bytes")
    coinb1 = (struct.pack("<i", 2) + varint(1) + b"\0" * 32 + b"\xff\xff\xff\xff"
              + varint(script_len) + height_push + bytes([extranonce_size]))
    coinb2 = (tag_push + struct.pack("<I", 0xFFFFFFFE) + varint(len(outputs))
              + b"".join(serialize_output(v, s) for v, s in outputs)
              + struct.pack("<I", max(height - 1, 0)))
    return coinb1, coinb2


def add_coinbase_witness(tx: bytes) -> bytes:
    """Converte a coinbase para o formato com witness (valor reservado = 32 zeros)."""
    return tx[:4] + b"\x00\x01" + tx[4:-4] + b"\x01\x20" + b"\0" * 32 + tx[-4:]


def parse_coinbase(tx: bytes) -> dict:
    """Lê uma coinbase (sem witness): altura, scriptSig e saídas."""
    pos = 4
    n_in, pos = read_varint(tx, pos)
    pos += 36
    slen, pos = read_varint(tx, pos)
    script_sig = tx[pos:pos + slen]
    pos += slen + 4
    n_out, pos = read_varint(tx, pos)
    outputs = []
    for _ in range(n_out):
        value = struct.unpack_from("<q", tx, pos)[0]
        pos += 8
        plen, pos = read_varint(tx, pos)
        outputs.append((value, tx[pos:pos + plen]))
        pos += plen
    height, _ = decode_script_int(script_sig)
    return {"height": height, "script_sig": script_sig, "outputs": outputs}


# --------------------------------------------------------------------------
# Árvore de merkle
# --------------------------------------------------------------------------
def merkle_root(hashes: list[bytes]) -> bytes:
    level = list(hashes)
    if not level:
        raise ValueError("lista vazia")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_branch(txids: list[bytes]) -> list[bytes]:
    """Caminho de merkle da coinbase (índice 0). `txids` NÃO inclui a coinbase."""
    branch = []
    level: list[bytes | None] = [None] + list(txids)
    while len(level) > 1:
        branch.append(level[1])
        if len(level) % 2:
            level.append(level[-1])
        level = [None] + [sha256d(level[i] + level[i + 1]) for i in range(2, len(level), 2)]
    return branch


def merkle_root_from_branch(coinbase_hash: bytes, branch: list[bytes]) -> bytes:
    root = coinbase_hash
    for h in branch:
        root = sha256d(root + h)
    return root


# --------------------------------------------------------------------------
# Cabeçalho
# --------------------------------------------------------------------------
def build_header(version: int, prev_hash: bytes, merkle: bytes, ntime: int, bits: int,
                 nonce: int) -> bytes:
    """prev_hash e merkle na ordem interna (a mesma de sha256d)."""
    return (struct.pack("<I", version & 0xFFFFFFFF) + prev_hash + merkle
            + struct.pack("<III", ntime, bits, nonce))


def parse_header(header: bytes) -> dict:
    if len(header) != 80:
        raise ValueError("cabeçalho deve ter 80 bytes")
    version, = struct.unpack_from("<I", header, 0)
    ntime, bits, nonce = struct.unpack_from("<III", header, 68)
    return {
        "version": version,
        "prev_hash": hash_to_hex(header[4:36]),
        "merkle_root": hash_to_hex(header[36:68]),
        "time": ntime,
        "bits": bits,
        "nonce": nonce,
    }


def swap_words(data: bytes) -> bytes:
    """Inverte cada palavra de 4 bytes (formato do prevhash no protocolo Stratum)."""
    return b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
