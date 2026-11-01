"""Copiloto de IA: calcula nonces para o bloco candidato e conversa com você.

Provedores: xAI (Grok), Anthropic (Claude), OpenAI e qualquer API compatível
com OpenAI. A cada chamada a IA recebe o cabeçalho, o alvo e o nonce anterior,
e responde somente com o próximo nonce, que é testado de verdade (SHA-256
duplo). Para comparação honesta, um nonce aleatório é testado ao lado de cada
nonce da IA.
"""
from __future__ import annotations

import collections
import json
import random
import re
import threading
import time

import anthropic
import openai

from .paths import USAGE_FILE

PROVIDERS = {
    "xai": {"nome": "xAI Grok", "base_url": "https://api.x.ai/v1",
            "modelo": "grok-4.20-0309-reasoning"},
    "anthropic": {"nome": "Anthropic Claude", "base_url": None, "modelo": "claude-opus-5-5"},
    "openai": {"nome": "OpenAI", "base_url": None, "modelo": ""},
    "compat": {"nome": "Outra API compatível com OpenAI", "base_url": "", "modelo": ""},
}
# Modelos Claude que aceitam o fallback automático do servidor em caso de recusa.
CLAUDE_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
# Preço por milhão de tokens (entrada, saída) em US$, para estimar o gasto do Claude.
PRICES = {"claude-opus-5-5": (4, 20), "claude-opus-5": (5, 25), "claude-sonnet-5-5": (2, 10),
          "claude-haiku-4-5": (1, 5), "claude-fable-5-1": (10, 50)}
XAI_TICKS_PER_USD = 10_000_000_000     # a xAI informa o custo em "ticks" (1e-10 US$)
MAX_NONCE = 0xFFFFFFFF
REQUEST_TIMEOUT = 600                  # a IA pode levar o tempo que precisar

SYSTEM_GUESS = """Você é o copiloto de IA de um minerador solo de Bitcoin.
Sua tarefa é calcular o nonce que fecha o bloco candidato: um número inteiro entre 0 e \
4294967295 tal que SHA-256(SHA-256(cabeçalho de 76 bytes + nonce em 4 bytes little-endian)), \
lido como número little-endian, seja menor ou igual ao alvo.
Você recebe o cabeçalho, o alvo, o nonce do bloco anterior da blockchain e o nonce anterior \
testado neste bloco (que não fechou o bloco). A partir do nonce anterior, calcule o próximo \
nonce. Leve o tempo que precisar para calcular.
Responda somente com o nonce: um único número inteiro em decimal, sem texto, sem explicação \
e sem formatação. Nunca escreva comentários, avisos ou parênteses: a resposta inteira deve \
conter apenas os dígitos do nonce."""

SYSTEM_CHAT = """Você é o copiloto de IA de um minerador solo de Bitcoin que roda no PC do \
usuário. Nesse minerador, a IA calcula nonces a partir do nonce anterior, e cada um é testado \
com SHA-256 duplo contra o alvo da rede. Não há mineração pesada na CPU.
Responda em português do Brasil, de forma clara, amigável e honesta. Você recebe junto de \
cada mensagem o estado atual do minerador em JSON. Use esses dados quando forem relevantes. \
Seja franco sobre probabilidades: o SHA-256 não tem padrão explorável, então nenhum palpite \
é melhor que o acaso, e a chance de achar um bloco na mainnet é astronomicamente pequena."""


class AIError(Exception):
    pass


def _usage(entrada: int, saida: int, raciocinio: int = 0, custo: float | None = None) -> dict:
    return {"entrada": entrada, "saida": saida, "raciocinio": raciocinio,
            "total": entrada + saida, "custo_usd": custo}


class AIClient:
    def __init__(self, provider: str, api_key: str, model: str, base_url: str | None = None):
        if provider not in PROVIDERS:
            raise AIError(f"provedor desconhecido: {provider}")
        if not api_key:
            raise AIError(f"Cadastre a chave da API ({PROVIDERS[provider]['nome']}) na aba IA.")
        if not model:
            raise AIError("Escolha um modelo na aba IA (use o botão 'Listar modelos').")
        self.provider, self.model = provider, model
        if provider == "anthropic":
            self._anthropic = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT,
                                                  max_retries=2)
        else:
            url = base_url if provider == "compat" else PROVIDERS[provider]["base_url"]
            if provider == "compat" and not url:
                raise AIError("Informe a URL base da API compatível.")
            self._openai = openai.OpenAI(api_key=api_key, base_url=url, timeout=REQUEST_TIMEOUT,
                                         max_retries=2)

    def complete(self, system: str, messages: list) -> tuple[str, dict, dict]:
        """Retorna (texto, uso de tokens, mensagem para o histórico)."""
        try:
            if self.provider == "anthropic":
                return self._complete_anthropic(system, messages)
            return self._complete_openai(system, messages)
        except (anthropic.AuthenticationError, openai.AuthenticationError):
            raise AIError("Chave da API inválida ou sem permissão.")
        except (anthropic.RateLimitError, openai.RateLimitError):
            raise AIError("Limite de uso da API atingido (rate limit). Tentando de novo em breve.")
        except (anthropic.NotFoundError, openai.NotFoundError):
            raise AIError(f"Modelo '{self.model}' não encontrado para esta chave.")
        except (anthropic.APITimeoutError, openai.APITimeoutError):
            raise AIError(f"A IA passou de {REQUEST_TIMEOUT // 60} minutos sem responder.")
        except (anthropic.APIConnectionError, openai.APIConnectionError):
            raise AIError("Sem conexão com a API da IA.")
        except (anthropic.APIStatusError, openai.APIStatusError) as e:
            raise AIError(f"Erro da API ({e.status_code}): {getattr(e, 'message', e)}")

    def _complete_anthropic(self, system, messages):
        kwargs = {"model": self.model, "max_tokens": 16000, "system": system, "messages": messages}
        if self.model in CLAUDE_FALLBACK_MODELS:
            resp = self._anthropic.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = self._anthropic.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise AIError("A IA recusou a solicitação.")
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        entrada = (u.input_tokens + (u.cache_creation_input_tokens or 0)
                   + (u.cache_read_input_tokens or 0))
        custo = None
        if self.model in PRICES:
            pin, pout = PRICES[self.model]
            custo = (entrada * pin + u.output_tokens * pout) / 1e6
        return text, _usage(entrada, u.output_tokens, 0, custo), \
            {"role": "assistant", "content": resp.content}

    def _complete_openai(self, system, messages):
        msgs = [{"role": "system", "content": system}] + messages
        resp = self._openai.chat.completions.create(model=self.model, messages=msgs)
        text = resp.choices[0].message.content or ""
        usage = _usage(0, 0)
        if resp.usage:
            raw = resp.usage.model_dump()
            entrada = raw.get("prompt_tokens") or 0
            # A xAI não conta o raciocínio em completion_tokens, mas conta em total_tokens.
            saida = max(raw.get("completion_tokens") or 0, (raw.get("total_tokens") or 0) - entrada)
            raciocinio = (raw.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            ticks = raw.get("cost_in_usd_ticks")
            usage = _usage(entrada, saida, raciocinio, ticks / XAI_TICKS_PER_USD if ticks else None)
        return text, usage, {"role": "assistant", "content": text}

    def list_models(self) -> list[str]:
        try:
            if self.provider == "anthropic":
                return sorted(m.id for m in self._anthropic.models.list())
            return sorted(m.id for m in self._openai.models.list())
        except (anthropic.APIError, openai.APIError) as e:
            raise AIError(f"Não foi possível listar modelos: {e}")


def parse_nonce(text: str) -> int | None:
    """Lê o nonce da resposta. Vale só se a primeira linha for apenas o número;
    números soltos no meio de um texto (ex.: o "256" de "SHA-256") não contam."""
    first = next((line for line in text.strip().splitlines() if line.strip()), "")
    clean = first.strip().strip("`*\"'. ")
    clean = re.sub(r"(?i)^nonce\s*[:=]\s*", "", clean)
    if re.fullmatch(r"0x[0-9a-fA-F]{1,8}", clean):
        return int(clean, 16)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+|\d+", clean):
        value = int(re.sub(r"[.,]", "", clean))
        return value if value <= MAX_NONCE else None
    return None


class Copilot:
    """Laço de palpites da IA + chat + contagem de tokens."""

    def __init__(self, controller):
        self.ctrl = controller
        self.running = False
        self._stop = threading.Event()
        self.calls = 0
        self.session = _usage(0, 0, 0, 0.0)
        self.total = self._load_usage()
        self.cost_known = False
        self.last_answer = ""
        self.last_previous: dict | None = None
        self.last_error: str | None = None
        self.avg_latency: float | None = None
        self.guesses: collections.deque = collections.deque(maxlen=200)
        self.ai = {"total": 0, "melhor": None, "zeros": collections.Counter()}
        self.rnd = {"total": 0, "melhor": None, "zeros": collections.Counter()}
        # (rede, altura) -> último nonce testado nesse bloco. A chave é a altura, e não o
        # candidato: o candidato é remontado a cada 90 s na mesma altura (transações e
        # horário novos) e a sequência de nonces anteriores deve continuar.
        self._previous: dict[tuple, dict] = {}
        self.chat_history: list = []
        self.chat_log: list[dict] = []
        self._chat_key = None
        self._chat_lock = threading.Lock()
        self._usage_lock = threading.Lock()

    # ---- contagem de tokens (persistida em data/uso_ia.json) ----
    @staticmethod
    def _load_usage() -> dict:
        base = _usage(0, 0, 0, 0.0)
        base["chamadas"] = 0
        try:
            base.update(json.loads(USAGE_FILE.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return base

    def _account(self, usage: dict) -> None:
        with self._usage_lock:
            for bucket in (self.session, self.total):
                for key in ("entrada", "saida", "raciocinio", "total"):
                    bucket[key] += usage[key]
                if usage["custo_usd"] is not None:
                    bucket["custo_usd"] = (bucket["custo_usd"] or 0) + usage["custo_usd"]
            if usage["custo_usd"] is not None:
                self.cost_known = True
            self.total["chamadas"] += 1
            USAGE_FILE.write_text(json.dumps(self.total, indent=2), encoding="utf-8")

    def _client(self) -> AIClient:
        cfg = self.ctrl.config["ia"]
        p = cfg["provedor"]
        return AIClient(p, cfg["chaves"].get(p, ""), cfg["modelos"].get(p, ""),
                        cfg.get("base_url_compat"))

    # ---- palpites ----
    def start(self) -> None:
        if self.running:
            return
        self._client()          # valida chave/modelo antes de começar
        self.running = True
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="ia-palpites").start()
        self.ctrl.log("IA começou a calcular nonces.", "ok")

    def stop(self) -> None:
        if self.running:
            self.running = False
            self._stop.set()
            self.ctrl.log("IA parou de calcular nonces.")

    def _loop(self) -> None:
        backoff = 5
        while self.running:
            cfg = self.ctrl.config["ia"]
            job = self.ctrl.current_job
            if job is None or job.job_id in self.ctrl.solved_jobs:
                self._stop.wait(2)
                continue
            if self.calls >= int(cfg["max_chamadas"]):
                self.ctrl.log(f"Limite de {cfg['max_chamadas']} chamadas à IA atingido. "
                              "Aumente o limite na aba IA para continuar.")
                self.running = False
                break
            try:
                client = self._client()
                previous = self._previous.get(self._block_key(job))
                prompt = self._guess_prompt(job, previous)
                started = time.time()
                text, usage, _ = client.complete(SYSTEM_GUESS, [{"role": "user", "content": prompt}])
                elapsed = time.time() - started
                self.avg_latency = elapsed if self.avg_latency is None else \
                    0.7 * self.avg_latency + 0.3 * elapsed
                self.calls += 1
                self._account(usage)
                self.last_answer = text.strip()[:300]
                self.last_previous = previous
                nonce = parse_nonce(text)
                if nonce is None:
                    raise AIError("A IA não respondeu só com o nonce (resposta descartada): "
                                  f"{self.last_answer[:80]!r}")
                self.last_error, backoff = None, 5
            except AIError as e:
                self.last_error = str(e)
                self.ctrl.log(f"IA: {e}", "erro")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 120)
                continue
            current = self.ctrl.current_job
            if current is None or self._block_key(current) != self._block_key(job):
                # O nonce foi calculado para um cabeçalho que não vale mais.
                self.ctrl.log(f"A rede fechou o bloco {job.height} enquanto a IA calculava: "
                              f"resposta {nonce} descartada. Seguindo para o próximo bloco.")
            elif job.job_id not in self.ctrl.solved_jobs:
                self._evaluate(job, nonce)
            self._stop.wait(max(0.0, float(cfg["intervalo"])))

    @staticmethod
    def _block_key(job) -> tuple:
        return job.network, job.height

    @staticmethod
    def _guess_prompt(job, previous: dict | None) -> str:
        s = job.summary()
        prev_block = s.get("nonce_bloco_anterior")
        lines = [
            f"Altura do bloco candidato: {s['altura']}",
            f"Cabeçalho do bloco candidato (76 bytes, sem o nonce, hex): {s['cabecalho_sem_nonce']}",
            f"Alvo (hex): {s['alvo']}",
            f"Nonce do bloco anterior (altura {s['altura'] - 1}): "
            + (str(prev_block) if prev_block is not None else "desconhecido"),
        ]
        if previous:
            lines.append(f"Nonce anterior testado neste bloco: {previous['nonce']} "
                         f"(hash {previous['hash']}, não fechou o bloco)")
        else:
            lines.append("Nonce anterior testado neste bloco: nenhum (esta é a primeira tentativa)")
        lines.append("Calcule o próximo nonce, levando o tempo que precisar. "
                     "Responda somente com o nonce (apenas os dígitos, nada mais).")
        return "\n".join(lines)

    def _evaluate(self, job, nonce: int) -> None:
        result = self.ctrl.try_nonce(job, nonce, origin="IA")
        self._previous[self._block_key(job)] = {"nonce": nonce, "hash": result["hash"]}
        while len(self._previous) > 20:
            self._previous.pop(next(iter(self._previous)))
        self._record(self.ai, result)
        self.guesses.appendleft({"job_id": job.job_id, "altura": job.height, "nonce": nonce,
                                 "hash": result["hash"], "zeros_bits": result["zeros_bits"],
                                 "valido": result["valido"], "quando": time.time()})
        # Linha de base honesta: um nonce sorteado ao acaso para cada nonce da IA.
        self._record(self.rnd, job.check(random.getrandbits(32)))

    @staticmethod
    def _record(stats: dict, result: dict) -> None:
        stats["total"] += 1
        stats["zeros"][result["zeros_bits"]] += 1
        best = stats["melhor"]
        if best is None or result["zeros_bits"] > best["zeros_bits"]:
            stats["melhor"] = {"nonce": result["nonce"], "hash": result["hash"],
                               "zeros_bits": result["zeros_bits"]}

    # ---- chat ----
    def chat(self, message: str) -> str:
        with self._chat_lock:
            client = self._client()
            key = (client.provider, client.model)
            if key != self._chat_key:           # formatos de histórico diferem entre provedores
                self.chat_history, self._chat_key = [], key
            state = json.dumps(self.ctrl.ai_context(), ensure_ascii=False, default=str)
            user_msg = {"role": "user",
                        "content": f"[Estado atual do minerador]\n{state}\n\n[Mensagem]\n{message}"}
            messages = self.chat_history + [user_msg]
            text, usage, assistant_msg = client.complete(SYSTEM_CHAT, messages)
            self._account(usage)
            self.chat_history = messages + [assistant_msg]
            self.chat_log += [{"papel": "voce", "texto": message, "quando": time.time()},
                              {"papel": "ia", "texto": text, "quando": time.time()}]
            return text

    def clear_chat(self) -> None:
        with self._chat_lock:
            self.chat_history, self.chat_log = [], []

    # ---- estado ----
    @staticmethod
    def _stats_view(stats: dict) -> dict:
        total = stats["total"]
        mean = sum(z * c for z, c in stats["zeros"].items()) / total if total else 0
        return {"total": total, "melhor": stats["melhor"], "media_zeros": mean,
                "histograma": {str(z): c for z, c in sorted(stats["zeros"].items())}}

    def status(self) -> dict:
        cfg = self.ctrl.config["ia"]
        return {
            "rodando": self.running,
            "provedor": cfg["provedor"],
            "modelo": cfg["modelos"].get(cfg["provedor"], ""),
            "chamadas": self.calls,
            "limite_chamadas": cfg["max_chamadas"],
            "tokens_sessao": dict(self.session),
            "tokens_total": dict(self.total),
            "custo_conhecido": self.cost_known or bool(self.total.get("custo_usd")),
            "tempo_medio_chamada": self.avg_latency,
            "ultima_resposta": self.last_answer,
            "ultimo_nonce_anterior": self.last_previous,
            "ultimo_erro": self.last_error,
            "palpites": list(self.guesses)[:60],
            "ia": self._stats_view(self.ai),
            "aleatorio": self._stats_view(self.rnd),
            "chat": self.chat_log[-40:],
        }
