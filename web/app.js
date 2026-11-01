"use strict";

const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (id) => document.getElementById(id);
let S = null;          // último status do servidor
let CFG = null;        // configuração (chaves mascaradas)
let lastBlockId = null;
let lastChartKey = "";
let lastChatLen = -1;
let chatPending = false;

// ------------------------------------------------------------------ utilidades
async function api(path, body) {
  const opts = { headers: { "X-Token": TOKEN, "Content-Type": "application/json" } };
  if (body !== undefined) { opts.method = "POST"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.erro || `Erro ${r.status}`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const SCALES = [[1e33, "decilhões"], [1e30, "nonilhões"], [1e27, "octilhões"], [1e24, "septilhões"],
  [1e21, "sextilhões"], [1e18, "quintilhões"], [1e15, "quatrilhões"], [1e12, "trilhões"],
  [1e9, "bilhões"], [1e6, "milhões"]];

function fmtBig(n) {
  if (n == null || !isFinite(n)) return "—";
  for (const [v, name] of SCALES) {
    if (Math.abs(n) >= v) return `${(n / v).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${name}`;
  }
  return Math.round(n).toLocaleString("pt-BR");
}
const fmtInt = (n) => (n ?? 0).toLocaleString("pt-BR");
const fmtBTC = (sats) => sats == null ? "—" : `${(sats / 1e8).toLocaleString("pt-BR", { minimumFractionDigits: 8, maximumFractionDigits: 8 })} BTC`;
const fmtUSD = (v) => `US$ ${(v || 0).toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
const fmtClock = (ts) => new Date(ts * 1000).toLocaleTimeString("pt-BR");
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("pt-BR");

function fmtDuration(seconds) {
  if (!isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} segundos`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutos`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1).replace(".", ",")} horas`;
  const days = seconds / 86400;
  if (days < 365) return `${Math.round(days)} dias`;
  return `${fmtBig(days / 365.25)} anos`;
}

function hashHtml(hash) {
  const zeros = hash.match(/^0*/)[0];
  return `<span class="zeros">${zeros}</span>${esc(hash.slice(zeros.length))}`;
}

let toastTimer;
function toast(msg, kind = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), kind === "err" ? 7000 : 4000);
}

async function busy(btn, fn) {
  btn?.classList.add("busy");
  try { return await fn(); }
  catch (e) { toast(e.message, "err"); }
  finally { btn?.classList.remove("busy"); }
}

// ------------------------------------------------------------------ abas
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  if (name === "bloco") loadBlock(true);
  try { localStorage.setItem("aba", name); } catch (_) { /* sem armazenamento */ }
}
$("tabs").addEventListener("click", (e) => { if (e.target.dataset.tab) showTab(e.target.dataset.tab); });
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

// ------------------------------------------------------------------ configuração
async function loadConfig() {
  CFG = await api("/api/config");
  $("inAddress").value = CFG.endereco || "";
  showAddrInfo(CFG.endereco_info);
  document.querySelectorAll('input[name="modo"]').forEach((r) => (r.checked = r.value === CFG.modo));
  $("inIncludeTxs").checked = CFG.incluir_transacoes;
  $("inMaxTxs").value = CFG.max_transacoes;
  $("inAutoSend").checked = CFG.envio_automatico;
  $("inNodeHost").value = CFG.no.host;
  $("inNodePort").value = CFG.no.porta;
  $("inNodeUser").value = CFG.no.usuario;
  $("inNodePass").value = "";
  $("inNodePass").placeholder = CFG.no.senha ? `salva (${CFG.no.senha})` : "";
  $("inNodeCookie").value = CFG.no.cookie;
  const sel = $("inProvider");
  if (!sel.options.length) {
    for (const [id, name] of Object.entries(CFG.provedores)) sel.add(new Option(name, id));
  }
  sel.value = CFG.ia.provedor;
  fillProviderFields();
  $("inInterval").value = CFG.ia.intervalo;
  $("inMaxCalls").value = CFG.ia.max_chamadas;
  $("inBaseUrl").value = CFG.ia.base_url_compat || "";
  updateModeBoxes();
}

function fillProviderFields() {
  const p = $("inProvider").value;
  $("inApiKey").value = "";
  $("inApiKey").placeholder = CFG.ia.tem_chave[p] ? `chave salva (${CFG.ia.chaves[p]}); cole outra para trocar` : "cole a chave aqui";
  $("inModel").value = CFG.ia.modelos[p] || "";
  $("baseUrlField").hidden = p !== "compat";
  $("modelList").innerHTML = "";
}
$("inProvider").addEventListener("change", fillProviderFields);

function selectedMode() {
  return document.querySelector('input[name="modo"]:checked')?.value || "publico";
}
function updateModeBoxes() {
  const m = selectedMode();
  $("nodeBox").hidden = m !== "no";
  $("regtestBox").hidden = m !== "regtest";
}
$("modes").addEventListener("change", updateModeBoxes);

function modeBody() {
  const body = {
    modo: selectedMode(),
    incluir_transacoes: $("inIncludeTxs").checked,
    max_transacoes: Number($("inMaxTxs").value || 0),
    envio_automatico: $("inAutoSend").checked,
    no: { host: $("inNodeHost").value, porta: Number($("inNodePort").value || 8332),
      usuario: $("inNodeUser").value, cookie: $("inNodeCookie").value },
  };
  if ($("inNodePass").value) body.no.senha = $("inNodePass").value;
  return body;
}

function aiBody() {
  const p = $("inProvider").value;
  const ia = { provedor: p, modelos: { [p]: $("inModel").value.trim() },
    intervalo: Number($("inInterval").value || 0), max_chamadas: Number($("inMaxCalls").value || 1),
    base_url_compat: $("inBaseUrl").value.trim() };
  const key = $("inApiKey").value.trim();
  if (key) ia.chaves = { [p]: key };
  return { ia };
}

// ---- endereço
function showAddrInfo(info) {
  const el = $("addrInfo");
  if (!info) { el.textContent = " "; el.className = "addr-info muted"; return; }
  if (info.valido) {
    el.textContent = `✓ Endereço válido · ${info.tipo} · ${info.rede}`;
    el.className = "addr-info ok";
  } else {
    el.textContent = `✗ ${info.erro}`;
    el.className = "addr-info bad";
  }
}
let addrTimer;
$("inAddress").addEventListener("input", () => {
  clearTimeout(addrTimer);
  const v = $("inAddress").value.trim();
  if (!v) return showAddrInfo(null);
  addrTimer = setTimeout(async () => showAddrInfo(await api("/api/endereco/validar", { endereco: v })), 250);
});
$("btnSaveAddress").addEventListener("click", (e) => busy(e.target, async () => {
  CFG = await api("/api/config", { endereco: $("inAddress").value.trim() });
  showAddrInfo(CFG.endereco_info);
  toast("Endereço salvo.", "ok");
}));

$("btnSaveMode").addEventListener("click", (e) => busy(e.target, async () => {
  await api("/api/config", modeBody());
  await loadConfig();
  toast("Opções salvas. Reconecte para aplicar.", "ok");
}));

async function connect(btn) {
  await busy(btn, async () => {
    await api("/api/config", modeBody());
    await loadConfig();
    toast("Conectando…");
    await api("/api/conectar", {});
    toast("Conectado! Montando o bloco candidato…", "ok");
    await refresh();
  });
}
$("btnConnect2").addEventListener("click", (e) => connect(e.target));
$("btnConnect").addEventListener("click", (e) => {
  if (S?.ativo) return busy(e.target, async () => { await api("/api/desconectar", {}); await refresh(); });
  connect(e.target);
});

$("btnP2PTest").addEventListener("click", (e) => busy(e.target, async () => {
  const box = $("p2pResult");
  box.hidden = false;
  box.innerHTML = '<p class="muted">Procurando nós da rede Bitcoin pelos DNS seeds…</p>';
  const r = await api("/api/p2p/testar", {});
  box.innerHTML = `<p class="${r.ok ? "ok-text" : "bad-text"}">${r.ok ? "✓" : "✗"} ${r.enviados} de ${r.tentados} nós responderam ao aperto de mão do protocolo.</p>
    <ul>${(r.resultados || []).map((x) => `<li>${esc(x.no)} — ${x.ok ? `${esc(x.versao)} (altura ${fmtInt(x.altura)})` : `<span class="bad-text">${esc(x.erro)}</span>`}</li>`).join("")}</ul>`;
}));

// ---- IA
$("btnSaveAi").addEventListener("click", (e) => busy(e.target, async () => {
  await api("/api/config", aiBody());
  await loadConfig();
  toast("Configuração da IA salva.", "ok");
}));
$("btnListModels").addEventListener("click", (e) => busy(e.target, async () => {
  const model = $("inModel").value;
  await api("/api/config", aiBody());
  await loadConfig();
  $("inModel").value = model || $("inModel").value;
  const r = await api(`/api/ia/modelos?provedor=${encodeURIComponent($("inProvider").value)}`);
  $("modelList").innerHTML = r.modelos.map((m) => `<option value="${esc(m)}">`).join("");
  toast(`${r.modelos.length} modelos disponíveis: clique no campo Modelo para escolher.`, "ok");
}));

async function aiStart(btn) {
  await busy(btn, async () => {
    if (btn.id === "btnAiStart2") { await api("/api/config", aiBody()); await loadConfig(); }
    await api("/api/ia/iniciar", {});
    toast("A IA começou a calcular nonces.", "ok");
    await refresh();
  });
}
const aiStop = (btn) => busy(btn, async () => { await api("/api/ia/parar", {}); await refresh(); });
$("btnAiStart").addEventListener("click", (e) => aiStart(e.target));
$("btnAiStart2").addEventListener("click", (e) => aiStart(e.target));
$("btnAiStop").addEventListener("click", (e) => aiStop(e.target));
$("btnAiStop2").addEventListener("click", (e) => aiStop(e.target));

// ---- chat
async function sendChat(text) {
  if (!text || chatPending) return;
  chatPending = true;
  const chat = $("chat");
  chat.insertAdjacentHTML("beforeend", `<div class="msg voce">${esc(text)}</div><div class="msg ia pending" id="pendingMsg">pensando…</div>`);
  chat.scrollTop = chat.scrollHeight;
  $("btnChatSend").disabled = true;
  try {
    await api("/api/ia/chat", { mensagem: text });
  } catch (e) {
    toast(e.message, "err");
  } finally {
    chatPending = false;
    $("btnChatSend").disabled = false;
    lastChatLen = -1;
    await refresh();
  }
}
$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("chatInput").value.trim();
  $("chatInput").value = "";
  sendChat(t);
});
document.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => sendChat(b.dataset.ask)));
$("btnChatClear").addEventListener("click", async () => { await api("/api/ia/chat/limpar", {}); lastChatLen = -1; refresh(); });

// Markdown mínimo das respostas da IA: **negrito**, *itálico* e `código`.
function richText(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/`([^`\n]+)`/g, '<code class="mono">$1</code>');
}

function renderChat(log) {
  if (chatPending || log.length === lastChatLen) return;
  lastChatLen = log.length;
  const chat = $("chat");
  chat.innerHTML = log.length
    ? log.map((m) => `<div class="msg ${m.papel === "voce" ? "voce" : "ia"}">${richText(m.texto)}</div>`).join("")
    : '<p class="muted">Pergunte qualquer coisa sobre o bloco, a mineração ou suas chances.</p>';
  chat.scrollTop = chat.scrollHeight;
}

// ---- regtest
$("btnRtDownload").addEventListener("click", (e) => busy(e.target, async () => { await api("/api/regtest/baixar", {}); toast("Download iniciado."); }));
$("btnRtPrepare").addEventListener("click", (e) => busy(e.target, async () => {
  toast("Minerando 101 blocos de preparação…");
  const r = await api("/api/regtest/preparar", { quantidade: 101 });
  toast(`${r.aceitos} blocos aceitos pelo nó.`, "ok");
}));
$("btnRtTxs").addEventListener("click", (e) => busy(e.target, async () => {
  const r = await api("/api/regtest/transacoes", { quantidade: 5 });
  toast(`${r.txids.length} transações criadas. Elas entram no próximo bloco candidato em alguns segundos.`, "ok");
}));
$("btnRtStop").addEventListener("click", (e) => busy(e.target, async () => { await api("/api/regtest/desligar", {}); toast("Nó regtest desligado."); }));
$("btnRtReset").addEventListener("click", (e) => {
  if (!confirm("Apagar toda a blockchain e a carteira de teste do regtest?")) return;
  busy(e.target, async () => { await api("/api/regtest/resetar", {}); toast("Blockchain de teste apagada.", "ok"); });
});

// ------------------------------------------------------------------ validação manual
function manualBody() {
  return { nonce: $("inNonce").value, extranonce: $("inExtranonce").value, horario: $("inNtime").value || null };
}
function renderManual(r, sent) {
  const box = $("manualResult");
  box.hidden = false;
  box.className = `result ${r.valido ? "valid" : ""}`;
  const f = r.campos;
  let envio = "";
  if (r.envio) {
    envio = r.envio.ok
      ? `<p class="ok-text">✓ Bloco transmitido: ${esc(r.envio.detalhe || "")}</p>`
      : `<p class="bad-text">✗ Envio falhou: ${esc(r.envio.motivo)}</p>`;
  } else if (sent && !r.valido) {
    envio = '<p class="bad-text">Não enviado: o hash está acima do alvo.</p>';
  }
  box.innerHTML = `
    <h3>${r.valido ? "✓ Nonce válido! Este bloco pode ser emitido." : "✗ Hash acima do alvo. Este nonce não fecha o bloco."}</h3>
    <div class="hash-big">${hashHtml(r.hash)}</div>
    <dl class="kv">
      <dt>Zeros no início</dt><dd>${r.zeros_bits} bits (precisa de ${r.zeros_necessarios})</dd>
      <dt>Dificuldade do hash</dt><dd>${r.dificuldade_hash.toLocaleString("pt-BR", { maximumFractionDigits: 6 })}</dd>
      <dt>Alvo</dt><dd class="mono break">${hashHtml(r.alvo)}</dd>
      <dt>Altura</dt><dd>${fmtInt(r.altura)}</dd>
      <dt>Nonce</dt><dd class="mono">${f.nonce} (0x${f.nonce.toString(16).padStart(8, "0")})</dd>
      <dt>Merkle root</dt><dd class="mono break">${esc(f.merkle_root)}</dd>
      <dt>Cabeçalho (80 bytes)</dt><dd class="mono break">${esc(r.cabecalho_hex)}</dd>
    </dl>${envio}`;
  $("btnEmit").disabled = !r.valido;
}
$("btnTestNonce").addEventListener("click", (e) => busy(e.target, async () => renderManual(await api("/api/manual/testar", manualBody()), false)));
$("btnEmit").addEventListener("click", (e) => {
  if (!confirm("Transmitir este bloco para a rede agora?")) return;
  busy(e.target, async () => renderManual(await api("/api/manual/emitir", manualBody()), true));
});
$("btnRandomNonce").addEventListener("click", () => {
  $("inNonce").value = crypto.getRandomValues(new Uint32Array(1))[0];
  $("btnTestNonce").click();
});
$("inNonce").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btnTestNonce").click(); });

let realFields = null;
$("btnVerifyReal").addEventListener("click", (e) => busy(e.target, async () => {
  const h = $("inRealHeight").value;
  if (h === "") throw new Error("Digite a altura do bloco.");
  const r = await api(`/api/verificar-bloco?altura=${encodeURIComponent(h)}`);
  realFields = r.campos;
  const f = r.campos;
  const box = $("realResult");
  box.hidden = false;
  box.className = `result ${r.confere && r.valido ? "valid" : ""}`;
  box.innerHTML = `
    <h3>${r.confere ? "✓ O hash calculado aqui é idêntico ao oficial" : "✗ O hash não confere"}</h3>
    <dl class="kv">
      <dt>Hash oficial</dt><dd class="mono break">${hashHtml(r.hash_oficial)}</dd>
      <dt>Hash calculado</dt><dd class="mono break">${hashHtml(r.hash_calculado)}</dd>
      <dt>Nonce vencedor</dt><dd class="mono">${f.nonce}</dd>
      <dt>Zeros no início</dt><dd>${r.zeros_bits} bits</dd>
      <dt>Horário</dt><dd>${fmtDate(f.time)}</dd>
      <dt>Bits / alvo</dt><dd class="mono break">${f.bits.toString(16)} → ${hashHtml(r.alvo)}</dd>
      <dt>Merkle root</dt><dd class="mono break">${esc(f.merkle_root)}</dd>
      <dt>Bloco anterior</dt><dd class="mono break">${esc(f.prev_hash)}</dd>
    </dl>
    <div class="row tight" style="margin-top:14px">
      <input id="inAltNonce" type="number" value="${f.nonce + 1}" min="0" max="4294967295">
      <button class="btn" id="btnAltNonce">Recalcular com outro nonce</button>
    </div>
    <div id="altResult"></div>`;
  $("btnAltNonce").addEventListener("click", async () => {
    try {
      const alt = await api("/api/hash-cabecalho", { ...realFields, nonce: Number($("inAltNonce").value) });
      $("altResult").innerHTML = `<p class="mono break" style="margin-top:10px">${hashHtml(alt.hash)}</p>
        <p class="${alt.valido ? "ok-text" : "bad-text"}">${alt.valido ? "✓ ainda válido (!)" : `✗ Inválido: só ${alt.zeros_bits} bits zero. Mudar 1 número no nonce muda o hash inteiro.`}</p>`;
    } catch (err) { toast(err.message, "err"); }
  });
}));

// ------------------------------------------------------------------ bloco atual
async function loadBlock(force) {
  if (!S?.bloco) return;
  if (!force && S.bloco.job_id === lastBlockId) return;
  if (!force && !$("tab-bloco").classList.contains("active")) return;
  const b = await api("/api/bloco");
  if (!b.job_id) return;
  lastBlockId = b.job_id;
  $("blkUpdated").textContent = `montado às ${fmtClock(b.criado_em)}`;
  $("hdrKv").innerHTML = `
    <dt>Rede</dt><dd>${esc(b.rede)} · fonte: ${esc(b.fonte)}</dd>
    <dt>Altura</dt><dd>${fmtInt(b.altura)}</dd>
    <dt>Versão</dt><dd class="mono">0x${esc(b.versao)}</dd>
    <dt>Bloco anterior</dt><dd class="mono break">${hashHtml(b.bloco_anterior)}</dd>
    <dt>Merkle root</dt><dd class="mono break">${esc(b.merkle_root)}</dd>
    <dt>Horário</dt><dd>${fmtDate(b.horario)} <span class="muted">(${b.horario})</span></dd>
    <dt>Bits</dt><dd class="mono">${esc(b.bits)}</dd>
    <dt>Alvo</dt><dd class="mono break">${hashHtml(b.alvo)}</dd>
    <dt>Dificuldade</dt><dd>${fmtBig(b.dificuldade)} <span class="muted">(${b.dificuldade.toLocaleString("pt-BR", { maximumFractionDigits: 2 })})</span></dd>
    <dt>Cabeçalho sem nonce</dt><dd class="mono break">${esc(b.cabecalho_sem_nonce)}</dd>`;
  $("outTable").querySelector("tbody").innerHTML = b.saidas.map((o, i) =>
    `<tr><td>${i}</td><td class="mono">${esc(o.endereco)}</td><td>${fmtBTC(o.valor)}</td></tr>`).join("");
  $("coinbaseHex").value = b.coinbase_hex;
  $("txSummary").textContent = `${b.transacoes.length} transações · taxas ${fmtBTC(b.taxas_total)} · subsídio ${fmtBTC(b.subsidio)}`;
  $("txTable").querySelector("tbody").innerHTML = b.transacoes.length
    ? b.transacoes.map((t, i) => `<tr><td>${i + 1}</td><td class="mono">${esc(t.txid)}</td><td>${fmtInt(t.taxa)} sats</td><td>${fmtInt(t.peso)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Bloco só com a coinbase.</td></tr>';
}

// ------------------------------------------------------------------ gráfico IA × aleatório
function niceMax(v) {
  if (v <= 0) return 1;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}
function barPath(x, y, w, h, r) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
function renderChart(ai, rnd) {
  const key = JSON.stringify([ai.histograma, rnd.histograma]);
  if (key === lastChartKey) return;
  lastChartKey = key;
  const el = $("chart");
  if (!ai.total && !rnd.total) {
    el.innerHTML = '<p class="muted" style="padding-top:80px;text-align:center">O gráfico aparece quando a IA fizer os primeiros palpites.</p>';
    return;
  }
  const maxZ = Math.max(8, ...Object.keys(ai.histograma).map(Number), ...Object.keys(rnd.histograma).map(Number));
  const buckets = Array.from({ length: maxZ + 1 }, (_, z) => ({
    z,
    a: ai.total ? (ai.histograma[z] || 0) / ai.total * 100 : 0, ac: ai.histograma[z] || 0,
    r: rnd.total ? (rnd.histograma[z] || 0) / rnd.total * 100 : 0, rc: rnd.histograma[z] || 0,
  }));
  const W = el.clientWidth || 500, H = el.clientHeight || 220;
  const m = { l: 40, r: 8, t: 8, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const ymax = niceMax(Math.max(...buckets.map((b) => Math.max(b.a, b.r))));
  const y = (v) => m.t + ih - (v / ymax) * ih;
  const band = iw / buckets.length;
  const bw = Math.max(2, Math.min(18, (band - 8) / 2));
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for (let i = 0; i <= 4; i++) {
    const v = ymax * i / 4, yy = y(v);
    svg += `<line class="${i ? "gridline" : "baseline"}" x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}"/>`;
    svg += `<text class="tick" x="${m.l - 6}" y="${yy + 4}" text-anchor="end">${Math.round(v)}%</text>`;
  }
  const every = buckets.length > 24 ? 4 : buckets.length > 14 ? 2 : 1;
  buckets.forEach((b, i) => {
    const cx = m.l + band * i + band / 2;
    svg += `<path class="bar-1" d="${barPath(cx - bw - 1, y(b.a), bw, y(0) - y(b.a), 4)}"/>`;
    svg += `<path class="bar-2" d="${barPath(cx + 1, y(b.r), bw, y(0) - y(b.r), 4)}"/>`;
    if (i % every === 0) svg += `<text class="tick" x="${cx}" y="${H - m.b + 16}" text-anchor="middle">${b.z}</text>`;
    svg += `<rect class="hit" data-i="${i}" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}"/>`;
  });
  svg += `<text class="tick" x="${m.l + iw / 2}" y="${H - 2}" text-anchor="middle">zeros no início do hash (bits)</text></svg>`;
  el.innerHTML = svg;
  const tip = $("tooltip");
  el.querySelectorAll(".hit").forEach((r) => {
    r.addEventListener("mouseenter", () => {
      const b = buckets[Number(r.dataset.i)];
      tip.innerHTML = `<b>${b.z} bits zero</b>
        <div><span><i class="sw s1"></i>IA</span><span>${b.a.toFixed(1).replace(".", ",")}% (${b.ac})</span></div>
        <div><span><i class="sw s2"></i>Aleatório</span><span>${b.r.toFixed(1).replace(".", ",")}% (${b.rc})</span></div>`;
      tip.hidden = false;
      r.setAttribute("class", "hit hover-band");
    });
    r.addEventListener("mousemove", (ev) => {
      const box = $("vizRoot").getBoundingClientRect();
      let x = ev.clientX - box.left + 12;
      if (x + 170 > box.width) x = ev.clientX - box.left - 180;
      tip.style.left = `${x}px`;
      tip.style.top = `${ev.clientY - box.top + 12}px`;
    });
    r.addEventListener("mouseleave", () => { tip.hidden = true; r.setAttribute("class", "hit"); });
  });
}
window.addEventListener("resize", () => { lastChartKey = ""; if (S) renderChart(S.ia.ia, S.ia.aleatorio); });

// ------------------------------------------------------------------ renderização do status
function renderLog(list, el, limit) {
  el.innerHTML = list.slice(0, limit).map((ev) =>
    `<li><time>${fmtClock(ev.quando)}</time><span class="${ev.nivel}">${esc(ev.msg)}</span></li>`).join("")
    || '<li class="muted">Nada ainda.</li>';
}

function render() {
  const s = S, ia = s.ia, b = s.bloco;
  // topo
  $("modeChip").textContent = CFG?.modos?.[s.modo] || s.modo;
  const pill = $("connPill");
  const erro = s.fonte?.erro;
  pill.className = `pill ${s.conectado ? "on" : s.ativo ? (erro ? "err" : "wait") : "off"}`;
  pill.lastElementChild.textContent = s.conectado ? "Conectado" : s.ativo ? (erro ? "Erro de conexão" : "Conectando…") : "Desconectado";
  pill.title = erro || "";
  $("btnConnect").textContent = s.ativo ? "Desconectar" : "Conectar";
  $("btnConnect").className = s.ativo ? "btn" : "btn primary";

  // blocos de números
  $("tHeight").textContent = b ? fmtInt(b.altura) : "—";
  $("tHeightSub").textContent = b ? `${b.rede === "main" ? "mainnet" : b.rede} · ${b.num_transacoes} transações` : (s.ativo ? "montando bloco…" : "aguardando conexão");
  $("tDiff").textContent = b ? fmtBig(b.dificuldade) : "—";
  $("tDiffSub").textContent = b ? `o hash precisa começar com ${b.zeros_necessarios} bits zero` : " ";
  $("tGuesses").textContent = fmtInt(ia.ia.total);
  $("tGuessesSub").textContent = `+ ${fmtInt(ia.aleatorio.total)} aleatórios para comparar`;
  const best = ia.ia.melhor;
  $("tBest").textContent = best ? `${best.zeros_bits} bits` : "—";
  $("tBestSub").textContent = b ? `de ${b.zeros_necessarios} necessários para fechar o bloco` : "zeros no início do hash";

  // IA
  const badge = $("aiBadge");
  badge.textContent = ia.rodando ? "calculando nonces" : "parada";
  badge.className = `badge ${ia.rodando ? "on" : ""} ${ia.ultimo_erro ? "err" : ""}`;
  $("aiModelLine").textContent = `${CFG?.provedores?.[ia.provedor] || ia.provedor} · modelo ${ia.modelo || "—"}`;
  $("aiCalls").textContent = `${fmtInt(ia.chamadas)} de ${fmtInt(ia.limite_chamadas)}`;
  const ses = ia.tokens_sessao, tot = ia.tokens_total;
  $("aiTokens").textContent = `${fmtInt(ses.total)} (${fmtInt(ses.entrada)} entrada · ${fmtInt(ses.saida)} saída)`;
  $("aiCost").textContent = ia.custo_conhecido ? fmtUSD(ses.custo_usd) : "veja no painel do provedor";
  $("aiLatency").textContent = ia.tempo_medio_chamada != null ? `${ia.tempo_medio_chamada.toFixed(1).replace(".", ",")} s` : "—";
  const prev = ia.ultimo_nonce_anterior;
  $("aiPrev").textContent = ia.chamadas ? (prev ? `${prev.nonce}` : "nenhum (primeira tentativa do bloco)") : "—";
  $("aiAnswer").textContent = ia.ultima_resposta || "—";

  // tokens gastos (acumulado de todas as sessões)
  $("tTokens").textContent = fmtInt(tot.total);
  $("tTokensSub").textContent = tot.chamadas
    ? `${fmtInt(tot.chamadas)} chamadas` + (ia.custo_conhecido ? ` · ${fmtUSD(tot.custo_usd)}` : "")
    : "nenhuma chamada ainda";
  $("tTokensSub2").textContent = tot.chamadas
    ? `${fmtInt(tot.entrada)} entrada · ${fmtInt(tot.saida)} saída`
      + (tot.raciocinio ? ` (${fmtInt(tot.raciocinio)} de raciocínio)` : "")
    : "";
  $("aiError").hidden = !ia.ultimo_erro;
  $("aiError").textContent = ia.ultimo_erro || "";
  $("btnAiStart").disabled = $("btnAiStart2").disabled = ia.rodando;
  $("btnAiStop").disabled = $("btnAiStop2").disabled = !ia.rodando;

  // chance
  if (s.chance && b) {
    const p = s.chance.por_palpite;
    $("oddsEach").textContent = p >= 0.01 ? `${(p * 100).toFixed(0)}%` : `1 em ${fmtBig(1 / p)}`;
    $("oddsNeeded").textContent = fmtBig(s.chance.palpites_esperados);
    const perSec = 1 / ((CFG?.ia?.intervalo ?? 5) + (ia.tempo_medio_chamada ?? 2));
    $("oddsTime").textContent = fmtDuration(s.chance.palpites_esperados / perSec);
    const need = b.zeros_necessarios, got = best ? best.zeros_bits : 0;
    $("zmBest").style.width = `${Math.min(100, (got / Math.max(need, 1)) * 100)}%`;
    $("zmText").textContent = `${got} de ${need} bits`;
  } else {
    ["oddsEach", "oddsNeeded", "oddsTime"].forEach((id) => ($(id).textContent = "—"));
  }

  // bloco candidato (resumo)
  if (b) {
    $("bReward").textContent = `${fmtBTC(b.recompensa_total)}`;
    $("bTxs").textContent = `${b.num_transacoes} (taxas ${fmtBTC(b.taxas_total)})`;
    $("bPayout").textContent = b.saidas?.[0]?.endereco || "—";
    $("bPrev").innerHTML = hashHtml(b.bloco_anterior);
    $("bTarget").innerHTML = hashHtml(b.alvo);
  }

  // palpites
  const guesses = ia.palpites || [];
  $("hashStream").innerHTML = guesses.length
    ? guesses.slice(0, 14).map((g) => `<li><span class="h">${hashHtml(g.hash)}</span><span class="z">${g.valido ? "✓ " : ""}${g.zeros_bits} bits</span></li>`).join("")
    : '<li class="muted">Nenhum palpite ainda.</li>';
  $("guessTable").querySelector("tbody").innerHTML = guesses.length
    ? guesses.map((g) => `<tr><td class="mono">${g.nonce}</td><td class="mono">${hashHtml(g.hash)}</td><td>${g.zeros_bits}</td><td>${g.valido ? '<span class="ok-text">✓ válido</span>' : ""}</td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Nenhum palpite ainda.</td></tr>';

  // comparação
  const avg = (x) => x.total ? x.media_zeros.toFixed(2).replace(".", ",") : "—";
  $("cmpTotAi").textContent = fmtInt(ia.ia.total);
  $("cmpTotRnd").textContent = fmtInt(ia.aleatorio.total);
  $("cmpAvgAi").textContent = avg(ia.ia);
  $("cmpAvgRnd").textContent = avg(ia.aleatorio);
  $("cmpBestAi").textContent = ia.ia.melhor ? ia.ia.melhor.zeros_bits : "—";
  $("cmpBestRnd").textContent = ia.aleatorio.melhor ? ia.aleatorio.melhor.zeros_bits : "—";
  renderChart(ia.ia, ia.aleatorio);
  renderChat(ia.chat || []);

  // registro e encontrados
  renderLog(s.eventos, $("logMini"), 8);
  renderLog(s.eventos, $("logFull"), 400);
  $("foundTable").querySelector("tbody").innerHTML = s.encontrados.length
    ? s.encontrados.map((f) => `<tr><td>${fmtDate(f.quando)}</td><td>${esc(f.rede)}</td><td>${fmtInt(f.altura)}</td><td>${esc(f.origem)}</td>
        <td class="mono">${hashHtml(f.hash)}</td><td>${fmtBTC(f.recompensa)}</td>
        <td class="${f.resultado.ok ? "ok-text" : "bad-text"}">${f.resultado.ok ? "✓ " + esc(f.resultado.detalhe || "enviado") : "✗ " + esc(f.resultado.motivo)}</td></tr>`).join("")
    : '<tr><td colspan="7" class="muted">Nenhum bloco enviado ainda.</td></tr>';

  // regtest
  const rt = s.regtest;
  if (rt) {
    $("rtBadge").textContent = rt.rodando ? "nó ligado" : "nó desligado";
    $("rtBadge").className = `badge ${rt.rodando ? "on" : ""}`;
    const d = rt.download || {};
    $("rtCore").textContent = rt.instalado ? "instalado (v31.1)" : d.status === "baixando Bitcoin Core" ? `baixando ${d.percent}%` : (d.error ? `erro: ${d.error}` : "não baixado");
    $("btnRtDownload").hidden = rt.instalado;
    $("rtHeight").textContent = rt.rodando ? fmtInt(rt.altura) : "—";
    $("rtMempool").textContent = rt.rodando ? fmtInt(rt.mempool) : "—";
    $("rtBalance").textContent = rt.rodando ? `${rt.saldo_disponivel} BTC` : "—";
    $("rtImmature").textContent = rt.rodando ? `${rt.saldo_imaturo} BTC` : "—";
    $("rtAddress").textContent = rt.endereco || "—";
  }
  loadBlock(false);
}

async function refresh() {
  try {
    S = await api("/api/status");
    render();
  } catch (e) {
    $("connPill").className = "pill err";
    $("connPill").lastElementChild.textContent = "Servidor parado";
  }
}

// ------------------------------------------------------------------ início
(async function init() {
  await loadConfig();
  let tab = location.hash.slice(1);
  if (!tab) {
    try { tab = localStorage.getItem("aba") || "painel"; } catch (_) { tab = "painel"; }
  }
  showTab(document.getElementById(`tab-${tab}`) ? tab : "painel");
  await refresh();
  setInterval(refresh, 1500);
})();
