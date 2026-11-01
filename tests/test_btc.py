"""Testes do núcleo Bitcoin contra dados reais da blockchain e vetores oficiais."""
import random

import pytest

from minerador import btc

GENESIS_COINBASE = bytes.fromhex(
    "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff"
    "001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e2062726"
    "96e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a010000004"
    "34104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35"
    "504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000"
)


def test_genesis_block():
    txid = btc.sha256d(GENESIS_COINBASE)
    assert btc.hash_to_hex(txid) == "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
    header = btc.build_header(1, b"\0" * 32, btc.merkle_root([txid]), 1231006505, 0x1D00FFFF,
                              2083236893)
    h = btc.sha256d(header)
    assert btc.hash_to_hex(h) == "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
    assert btc.hash_to_int(h) <= btc.bits_to_target(0x1D00FFFF)
    parsed = btc.parse_coinbase(GENESIS_COINBASE)
    assert parsed["outputs"][0][0] == 50 * btc.COIN


def test_block_125552():
    header = btc.build_header(
        1, btc.hex_to_hash("00000000000008a3a41b85b8b29ad444def299fee21793cd8b9e567eab02cd81"),
        btc.hex_to_hash("2b12fcf1b09288fcaff797d71e950e71ae42b91e8bdb2304758dfcffc2b620e3"),
        1305998791, 0x1A44B9F2, 2504433986)
    h = btc.sha256d(header)
    assert btc.hash_to_hex(h) == "00000000000000001e8d6829a8a21adc5d38d0a473b144b6765798e61f98bd1d"
    assert btc.parse_header(header)["nonce"] == 2504433986
    # Com um nonce diferente o hash deixa de ser válido
    bad = btc.build_header(1, header[4:36], header[36:68], 1305998791, 0x1A44B9F2, 2504433987)
    assert btc.hash_to_int(btc.sha256d(bad)) > btc.bits_to_target(0x1A44B9F2)


def test_target_and_difficulty():
    assert btc.bits_to_target(0x1D00FFFF) == btc.DIFF1_TARGET
    assert btc.target_to_difficulty(btc.DIFF1_TARGET) == 1.0
    assert btc.bits_to_target(0x207FFFFF) == 0x7FFFFF << 232  # regtest


@pytest.mark.parametrize("addr,script_hex,net", [
    ("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", "0014751e76e8199196d454941c45d1b3a323f1433bd6", "main"),
    ("tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7",
     "00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262", "test"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",
     "512079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798", "main"),
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "76a91462e907b15cbf27d5425399ebf6f0fb50ebb88f1888ac", "main"),
])
def test_addresses(addr, script_hex, net):
    script, network, _ = btc.address_to_script(addr)
    assert script.hex() == script_hex
    assert network == net
    assert btc.script_to_address(script, net) == addr.lower() if addr[0] in "bBtT" else addr


@pytest.mark.parametrize("bad", [
    "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",       # checksum errado
    "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj1",
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",
    "",
])
def test_invalid_addresses(bad):
    with pytest.raises(ValueError):
        btc.address_to_script(bad)


def test_taproot_with_bech32_checksum_is_rejected():
    # Taproot (v1) precisa de Bech32m. O mesmo programa com checksum Bech32 é inválido.
    prog = bytes(range(32))
    data = [1] + btc._convertbits(prog, 8, 5)
    polymod = btc._bech32_polymod(btc._hrp_expand("bc") + data + [0] * 6) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    wrong = "bc1" + "".join(btc._BECH32[d] for d in data + checksum)
    with pytest.raises(ValueError):
        btc.address_to_script(wrong)
    assert btc.address_to_script(btc.bech32_encode_segwit("bc", 1, prog))[2] == "P2TR (Taproot)"


def test_bip34_height():
    assert btc.script_int(1) == b"\x51"
    assert btc.script_int(16) == b"\x60"
    assert btc.script_int(17) == b"\x01\x11"
    assert btc.script_int(128) == b"\x02\x80\x00"
    assert btc.script_int(900000) == b"\x03\xa0\xbb\x0d"
    for h in (0, 1, 16, 17, 127, 128, 255, 256, 32767, 32768, 900000, 8388608):
        assert btc.decode_script_int(btc.script_int(h))[0] == h


def test_merkle_branch_matches_full_tree():
    rng = random.Random(1)
    for n in range(1, 40):
        hashes = [rng.randbytes(32) for _ in range(n)]
        branch = btc.merkle_branch(hashes[1:])
        assert btc.merkle_root_from_branch(hashes[0], branch) == btc.merkle_root(hashes)


def test_coinbase_roundtrip():
    script, _, _ = btc.address_to_script("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    c1, c2 = btc.build_coinbase(900000, [(312_500_000, script)], extranonce_size=8)
    tx = c1 + b"\x11" * 8 + c2
    parsed = btc.parse_coinbase(tx)
    assert parsed["height"] == 900000
    assert parsed["outputs"] == [(312_500_000, script)]
    wit = btc.add_coinbase_witness(tx)
    assert wit[4:6] == b"\x00\x01" and wit[-4:] == tx[-4:]
    assert len(wit) == len(tx) + 2 + 34


# Vetores do pow_tests.cpp do Bitcoin Core
@pytest.mark.parametrize("first,last,bits,expected", [
    (1261130161, 1262152739, 0x1D00FFFF, 0x1D00D86A),
    (1231006505, 1233061996, 0x1D00FFFF, 0x1D00FFFF),   # limitado pelo powLimit
    (1279008237, 1279297671, 0x1C05A3F4, 0x1C0168FD),   # limite inferior (4x mais difícil)
    (1263163443, 1269211443, 0x1C387F6F, 0x1D00E1FD),   # limite superior (4x mais fácil)
])
def test_retarget(first, last, bits, expected):
    assert btc.next_work_required(bits, first, last) == expected


def test_compact_roundtrip():
    for bits in (0x1D00FFFF, 0x17021EC5, 0x1A44B9F2, 0x207FFFFF, 0x1C05A3F4):
        assert btc.target_to_bits(btc.bits_to_target(bits)) == bits


def test_subsidy():
    assert btc.block_subsidy(0) == 50 * btc.COIN
    assert btc.block_subsidy(840_000) == 312_500_000
    assert btc.block_subsidy(969_099) == 312_500_000
    assert btc.block_subsidy(1_050_000) == 156_250_000


def test_tx_ids_legacy_and_segwit():
    txid, wtxid = btc.tx_ids(GENESIS_COINBASE)
    assert txid == wtxid
    assert btc.hash_to_hex(txid) == "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
    # coinbase com witness tem o mesmo txid da versão sem witness
    script, _, _ = btc.address_to_script("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    c1, c2 = btc.build_coinbase(900000, [(1, script)])
    plain = c1 + b"\0" * 8 + c2
    txid2, wtxid2 = btc.tx_ids(btc.add_coinbase_witness(plain))
    assert txid2 == btc.sha256d(plain) and wtxid2 != txid2
