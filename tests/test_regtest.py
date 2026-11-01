"""Teste de integração com um Bitcoin Core real (regtest).

Prova que os blocos montados pelo minerador (coinbase, compromisso segwit,
árvore de merkle, transações) são aceitos pelo nó, tanto via submitblock
quanto pela mensagem P2P "block" (caminho usado no modo solo sem nó).
Pulado se o Bitcoin Core ainda não foi baixado.
"""
import random
import time

import pytest

from minerador import btc, p2p, regtest
from minerador.node_source import NodeSource

pytestmark = pytest.mark.skipif(regtest.bitcoind_path() is None,
                                reason="Bitcoin Core não baixado")


def solve(job):
    while True:
        nonce = random.getrandbits(32)
        if job.check(nonce)["valido"]:
            return job.build_block(b"\0" * 8, nonce)


@pytest.fixture(scope="module")
def node():
    n = regtest.RegtestNode()
    n.start()
    yield n


def test_blocks_with_transactions_are_accepted(node):
    script, _, _ = btc.address_to_script(node.address)
    src = NodeSource(node.rpc, script, kind="regtest")
    src.check_connection()
    while node.rpc.call("getblockcount") < 101:           # maturidade da coinbase
        job = src.refresh()
        assert src.submit(job, solve(job))["ok"]

    txids = node.create_test_transactions(3)
    time.sleep(6)                                          # cache do getblocktemplate
    job = src.refresh()
    assert len(job.tx_raw) >= 3
    result = src.submit(job, solve(job))
    assert result["ok"], result
    block = node.rpc.call("getblock", node.rpc.call("getbestblockhash"), 1)
    assert set(txids) <= set(block["tx"])


def test_block_relay_over_p2p(node):
    script, _, _ = btc.address_to_script(node.address)
    src = NodeSource(node.rpc, script, kind="regtest")
    src.check_connection()
    job = src.refresh()
    block = solve(job)
    res = p2p.broadcast_block(block, "regtest", peers=[("127.0.0.1", regtest.P2P_PORT)],
                              height=job.height)
    assert res["ok"], res
    time.sleep(1)
    assert node.rpc.call("getbestblockhash") == btc.hash_to_hex(btc.sha256d(block[:80]))
