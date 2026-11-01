"""Trocar o endereço com o minerador conectado vale na hora."""
import pytest

from minerador import btc
from minerador import controller as controller_module
from minerador.job import build_job
from minerador.public_source import PublicSource

OLD = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
NEW = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def _job(address: str):
    script, _, _ = btc.address_to_script(address)
    return build_job(source="publico", network="main", version=0x20000000, prev_hash=b"\x01" * 32,
                     height=969200, bits=0x17021EC5, ntime=1_790_000_000, txs=[],
                     coinbase_value=btc.block_subsidy(969200), payout_script=script)


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(controller_module, "FOUND_FILE", tmp_path / "encontrados.json")
    c = controller_module.Controller()
    c.config["endereco"], c.config["modo"] = OLD, "publico"
    c.source = PublicSource(btc.address_to_script(OLD)[0], include_txs=False, log=c.log)
    c._on_job(_job(OLD))
    assert c.current_job is not None
    return c


def test_address_change_applies_immediately(ctrl):
    ctrl.update_config({"endereco": NEW})
    assert ctrl.source.payout_script == btc.address_to_script(NEW)[0]
    assert ctrl.current_job is None                 # parou de usar o bloco antigo
    ctrl._on_job(_job(OLD))                         # bloco atrasado com o endereço antigo
    assert ctrl.current_job is None
    ctrl._on_job(_job(NEW))
    assert ctrl.current_job.info["saidas"][0]["endereco"] == NEW


def test_address_from_other_network_is_refused_while_connected(ctrl):
    with pytest.raises(ValueError):
        ctrl.update_config({"endereco": "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"})
    assert ctrl.config["endereco"] == OLD
