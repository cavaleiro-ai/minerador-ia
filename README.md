# Minerador IA

Minerador solo de Bitcoin em que uma **inteligência artificial escolhe os nonces**. O programa monta blocos de verdade, pede um número à IA, confere esse número com SHA-256 duplo e, se ele fechar o bloco, transmite o bloco para a rede. Não usa pool, não exige nó próprio e quase não usa o processador.

> **Isto é um projeto educacional, não uma forma de ganhar dinheiro.** O SHA-256 não tem padrão, então o nonce da IA vale o mesmo que um número sorteado. Em 31/10/2026, a chance na mainnet era de cerca de **1 em 637 sextilhões por tentativa**, e cada chamada à IA é cobrada pelo provedor. Para ver um bloco ser aceito de verdade, sem gastar nada, use o [teste no regtest](#3-teste-sem-gastar-nada).

## 1. O que você precisa

- **Windows** (testado no Windows 10). Em Linux e macOS o programa não foi testado, e o Bitcoin Core precisa ser instalado à mão.
- **Python 3.10 ou mais novo** ([python.org](https://www.python.org/downloads/)). Testado com o Python 3.12. No instalador, marque **Add Python to PATH**.
- **Git**, para baixar o projeto, ou o botão **Code > Download ZIP** do GitHub.
- **Internet**, para os dados da rede Bitcoin.
- **Uma chave de API de IA**, só se você for usar os palpites da IA: xAI, Anthropic, OpenAI ou outra API compatível com OpenAI.

## 2. Como rodar

**Passo 1: baixe o projeto.**

```
git clone <URL-deste-repositório>
cd <pasta-do-projeto>
```

**Passo 2: abra o programa.** Dê dois cliques em **`iniciar.bat`**. Na primeira vez, ele cria o ambiente Python e instala as dependências, o que leva alguns minutos. Depois, o navegador abre em http://127.0.0.1:8765.

Deixe a janela preta aberta enquanto usa o programa. Fechar a janela encerra o servidor, e o navegador passa a mostrar `Failed to fetch` ou **Servidor parado**.

**Passo 3: cadastre o endereço da carteira.** Na aba **Carteira & Rede**, cole o seu endereço público (`bc1…`, `1…` ou `3…`) e clique em **Salvar endereço**. Nunca digite a frase de recuperação (seed) nem a chave privada.

**Passo 4: conecte.** Deixe o modo **Mainnet solo, sem nó** e clique em **Salvar e conectar**. O bloco candidato aparece no **Painel** em poucos segundos.

**Passo 5: configure a IA.** Na aba **Inteligência Artificial**, escolha o provedor, cole a chave, clique em **Listar modelos** e escolha um modelo. Defina um **limite de chamadas** baixo para controlar o gasto e clique em **Salvar**.

**Passo 6: inicie os palpites.** Clique em **Iniciar palpites**. A partir daqui, as chamadas são cobradas. Acompanhe os tokens no **Painel** e clique em **Parar** quando quiser encerrar.

## 3. Teste sem gastar nada

O modo regtest cria uma blockchain privada no seu PC, com as regras do Bitcoin e dificuldade mínima. As moedas dela não têm valor.

1. Em **Carteira & Rede**, selecione **Regtest**, clique em **Salvar opções** e depois em **Baixar Bitcoin Core**. O download é conferido com o SHA256 oficial.
2. Quando o laboratório mostrar **instalado**, clique em **Salvar e conectar**.
3. Clique em **Preparar 101 blocos** e depois em **Criar 5 transações de teste**. Aguarde cerca de 10 segundos.
4. Na aba **Validação manual**, clique em **Sortear um nonce** até aparecer **Nonce válido**. Cerca de 1 em cada 2 tentativas funciona.
5. Clique logo em **Emitir bloco** e confirme. O resultado esperado é `o nó aceitou o bloco`.

Para voltar à mainnet, selecione o modo de novo e clique em **Salvar e conectar**.

## 4. Problemas comuns

| O que aparece | O que fazer |
|---|---|
| `Python nao encontrado` | Instale o Python e marque **Add Python to PATH** |
| `Failed to fetch` ou **Servidor parado** | O servidor está fechado. Abra o `iniciar.bat` e recarregue a página com F5 |
| `token inválido` | Recarregue a página com F5 |
| `ModuleNotFoundError` | Rode `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Erro de porta em uso | Feche a outra janela ou rode `.venv\Scripts\python.exe run.py --porta 9000` |

A lista completa está na [seção 10 da documentação](DOCUMENTACAO.md#10-problemas-comuns).

## 5. Segurança

- O programa só precisa do **endereço público**. Quem tem a seed ou a chave privada controla a carteira.
- O servidor só aceita conexões do próprio PC e exige um token criado a cada abertura.
- Tudo o que você salva fica em `data/`, inclusive as **chaves de API em texto puro**. Essa pasta está no `.gitignore`: não a envie para lugar nenhum.
- Se uma chave vazar, revogue-a no site do provedor e gere outra.

## 6. Documentação e testes

- **[DOCUMENTACAO.md](DOCUMENTACAO.md):** como o programa funciona, passo a passo, com limitações conhecidas e referência técnica.
- **Skill do Claude Code:** em [.claude/skills/minerador-ia](.claude/skills/minerador-ia/SKILL.md). Ao abrir o projeto no Claude Code, peça, por exemplo, "faça o minerador funcionar".

Para rodar os testes:

```
.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_regtest.py
```

Os testes conferem o núcleo contra dados reais: o bloco gênese, o bloco 125552, os vetores oficiais de endereço (BIP173/BIP350) e os vetores de ajuste de dificuldade do Bitcoin Core.

Para testar blocos num Bitcoin Core real, sem tocar nos seus dados:

```
.venv\Scripts\python.exe .claude\skills\minerador-ia\scripts\testar_regtest.py
```

Esse teste roda numa pasta temporária. Se o Bitcoin Core ainda não tiver sido baixado, ele baixa uma cópia que é apagada no final.

Os comandos acima são para PowerShell ou cmd. No Git Bash, troque `\` por `/`.
