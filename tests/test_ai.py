"""Formato da instrução enviada à IA e leitura da resposta (sem chamar API)."""
from minerador import btc
from minerador.ai import Copilot, parse_nonce
from minerador.job import build_job


def test_parse_nonce_only_number():
    assert parse_nonce("2083236893") == 2083236893
    assert parse_nonce("  1235\n") == 1235
    assert parse_nonce("`4294967295`") == 4294967295
    assert parse_nonce("0x7c2bac1d") == 0x7C2BAC1D
    assert parse_nonce("2.083.236.893") == 2083236893
    assert parse_nonce("Nonce: 42") == 42
    assert parse_nonce("0\n\n(explicação que a IA não devia ter escrito)") == 0
    assert parse_nonce("sem número") is None
    assert parse_nonce("99999999999") is None          # fora do intervalo de 32 bits
    # número solto no meio de um texto não é nonce
    assert parse_nonce("Calcular isso exige SHA-256 duplo sobre o header") is None
    assert parse_nonce("The guidelines require...\n80-byte header") is None


def _job():
    script, _, _ = btc.address_to_script("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    job = build_job(source="publico", network="main", version=0x20000000, prev_hash=b"\x11" * 32,
                    height=969105, bits=0x17021EC5, ntime=1_790_000_000, txs=[],
                    coinbase_value=btc.block_subsidy(969105), payout_script=script)
    job.info["nonce_bloco_anterior"] = 3932395645
    return job


def test_prompt_sends_previous_nonce_and_asks_only_the_nonce():
    job = _job()
    first = Copilot._guess_prompt(job, None)
    assert "Nonce do bloco anterior (altura 969104): 3932395645" in first
    assert "nenhum (esta é a primeira tentativa)" in first
    assert job.summary()["cabecalho_sem_nonce"] in first
    assert "Responda somente com o nonce" in first

    check = job.check(1234)
    second = Copilot._guess_prompt(job, {"nonce": 1234, "hash": check["hash"]})
    assert f"Nonce anterior testado neste bloco: 1234 (hash {check['hash']}" in second
    assert "Calcule o próximo nonce" in second


# ---- a IA segue de bloco em bloco -------------------------------------------------------
from minerador import ai as ai_module  # noqa: E402


def _job_at(height: int, prev_block_nonce: int):
    script, _, _ = btc.address_to_script("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    job = build_job(source="publico", network="main", version=0x20000000,
                    prev_hash=height.to_bytes(32, "little"), height=height, bits=0x17021EC5,
                    ntime=1_790_000_000, txs=[], coinbase_value=btc.block_subsidy(height),
                    payout_script=script)
    job.info["nonce_bloco_anterior"] = prev_block_nonce
    return job


class FakeCtrl:
    def __init__(self, job):
        self.current_job = job
        self.solved_jobs = set()
        self.logs = []
        self.tested = []
        self.config = {"ia": {"max_chamadas": 100, "intervalo": 0, "provedor": "xai",
                              "modelos": {"xai": "grok"}, "chaves": {"xai": "k"}}}

    def log(self, msg, level="info"):
        self.logs.append(msg)

    def try_nonce(self, job, nonce, origin):
        self.tested.append((job.height, nonce))
        return job.check(nonce)


class FakeClient:
    model = "grok"

    def __init__(self, steps):
        self.steps, self.prompts = steps, []

    def complete(self, system, messages):
        step = self.steps[len(self.prompts)]
        self.prompts.append(messages[0]["content"])
        return step(), {"entrada": 1, "saida": 1, "raciocinio": 0, "total": 2, "custo_usd": None}, {}


def test_ai_keeps_going_block_after_block(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "USAGE_FILE", tmp_path / "uso.json")
    a1 = _job_at(100, prev_block_nonce=111)
    a2 = _job_at(100, prev_block_nonce=111)      # mesmo bloco remontado (90 s depois)
    b1 = _job_at(101, prev_block_nonce=222)      # a rede fechou o bloco 100
    ctrl = FakeCtrl(a1)
    cop = Copilot(ctrl)

    def rebuild_same_height():
        ctrl.current_job = a2
        return "6"

    def network_found_block():
        ctrl.current_job = b1
        return "7"

    def last():
        cop.running = False
        return "8"

    fake = FakeClient([lambda: "5", rebuild_same_height, network_found_block, last])
    monkeypatch.setattr(cop, "_client", lambda: fake)
    cop.running = True
    cop._loop()

    p = fake.prompts
    assert "Nonce anterior testado neste bloco: nenhum" in p[0]
    assert "Nonce do bloco anterior (altura 99): 111" in p[0]
    assert "Nonce anterior testado neste bloco: 5 " in p[1]
    assert "Nonce anterior testado neste bloco: 6 " in p[2]      # continuou após remontar
    assert "Altura do bloco candidato: 101" in p[3]              # passou para o bloco seguinte
    assert "Nonce anterior testado neste bloco: nenhum" in p[3]
    assert "Nonce do bloco anterior (altura 100): 222" in p[3]
    # a resposta 7 era para o bloco 100, que a rede já tinha fechado: descartada
    assert ctrl.tested == [(100, 5), (100, 6), (101, 8)]
    assert any("descartada" in m for m in ctrl.logs)
