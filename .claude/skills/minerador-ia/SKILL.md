---
name: minerador-ia
description: Instala, abre, configura, testa, diagnostica e prepara para publicação o Minerador IA, o minerador solo de Bitcoin deste repositório em que uma IA escolhe os nonces. Use sempre que o usuário quiser fazer o programa funcionar, rodar, conectar, configurar carteira, chave de API ou modelo, testar no regtest, entender um erro (como "Failed to fetch", "Servidor parado", "token inválido" ou erro de nó), conferir gastos com a IA ou subir o projeto para o GitHub, mesmo que não cite o nome do programa e diga só "o minerador" ou "não está conectando".
---

# Minerador IA

Leve o programa até um estado comprovadamente funcionando, sem gastar o dinheiro do usuário sem permissão e sem expor segredos. Os comandos partem da raiz do repositório. Para detalhes de funcionamento, leia `DOCUMENTACAO.md`: a seção 5 cobre o ciclo interno, a 10 os erros, a 11 as limitações e a 13 a referência técnica.

## Regras que protegem o usuário

- **Fale a verdade sobre as chances.** O SHA-256 não tem padrão, então o nonce da IA vale o mesmo que um sorteio. Na mainnet a chance é de cerca de 1 em centenas de sextilhões por tentativa. Nunca sugira que o programa dá lucro, mesmo se o usuário esperar isso, porque ele pode gastar dinheiro real com base nessa promessa.
- **Peça confirmação antes de gastar.** Cada chamada à IA é cobrada, inclusive no regtest e no chat. Não inicie os palpites nem envie mensagens ao chat sem o usuário pedir. Para provar que o programa funciona, use `testar_regtest.py`, que não chama nenhuma IA.
- **Nunca peça a seed nem a chave privada.** O programa só precisa do endereço público. Se o usuário oferecer esses dados, recuse e explique que quem os tem controla a carteira.
- **Não exiba segredos.** As chaves ficam em texto puro em `data/config.json`. Não mostre esse arquivo inteiro: para saber se uma chave existe, use `diagnostico.py`. O usuário digita a chave na interface. Se ele colar uma chave no chat, avise que ela deve ser trocada no site do provedor.
- **Preserve os dados locais.** Não apague `data/`. Ela pode conter `blocos_encontrados.json`, com blocos que não podem ser recriados. Para apagar a blockchain de teste, confirme antes, porque isso apaga também a carteira de teste.

## 1. Comece pelo diagnóstico

```
python .claude/skills/minerador-ia/scripts/diagnostico.py
```

Ele não altera nada e não mostra segredos. Mostra Python, dependências, configuração, Bitcoin Core e o estado do servidor. Use o resultado para decidir qual etapa abaixo falta, em vez de refazer tudo. Serve qualquer Python 3.10 ou mais novo, mesmo antes da instalação.

O script olha a porta 8765. Se o servidor foi aberto com outra porta, passe `--porta N`, senão ele acusa "parado" por engano. O código de saída é 1 quando alguma linha sai como `[erro]`, o que inclui servidor parado.

Os comandos com `\` são para PowerShell ou cmd. No Git Bash, troque por `/`, porque o Bash remove as barras invertidas.

## 2. Instalar

Precisa do Python 3.10 ou mais novo. No Windows, o `iniciar.bat` faz tudo na primeira abertura. Para instalar sem abrir o programa:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No Linux ou macOS, use `.venv/bin/python` e inicie com `.venv/bin/python run.py`. Nesses sistemas o programa não foi testado e o download automático do Bitcoin Core não funciona.

Se a primeira instalação falhar no meio, o `.bat` não tenta de novo, porque o `.venv` já existe. Rode o `pip install` acima.

## 3. Abrir

Abra `iniciar.bat` (ou `python run.py` com o Python do `.venv`). O endereço é http://127.0.0.1:8765. A janela do servidor precisa ficar aberta, porque fechá-la encerra o programa. Aceita `--porta N` e `--sem-navegador`.

Para abrir pelo terminal sem travar a sessão, rode `.venv\Scripts\python.exe run.py --sem-navegador` em segundo plano e confirme com `diagnostico.py` que a porta responde. Sem `--sem-navegador`, uma aba do navegador abre sozinha.

Para encerrar um servidor aberto assim, encerre o processo que você iniciou. No Windows, o `python.exe` do `.venv` é só um inicializador: quem escuta a porta é um processo filho com o executável do Python do sistema, e ele termina junto com o inicializador. Para identificá-los, use a linha de comando (`run.py`), não o caminho do executável. Não encerre outros processos Python, porque podem ser de outro programa.

## 4. Provar que funciona, sem gastar

```
python .claude/skills/minerador-ia/scripts/testar_regtest.py
```

O script exige o `.venv` já instalado e as portas 18443 e 18444 livres. Ele copia o código para uma pasta temporária, sobe um servidor separado sem chaves e minera 101 blocos. Depois cria 5 transações, acha um nonce e confirma que o nó aceitou o bloco. No fim, desliga tudo e apaga a cópia. Ele não toca em `data/`.

Se `bitcoin-core/` não existir no projeto, o script precisa de internet para baixar o Bitcoin Core dentro da cópia temporária, e esse download é apagado no fim. Por isso, a interface continua pedindo **Baixar Bitcoin Core** depois do teste, e cada execução baixa de novo. Em um teste com o download, tudo levou cerca de 40 segundos.

Se o usuário quiser ver isso na tela, guie-o pela seção 4 de `DOCUMENTACAO.md`.

## 5. Configurar para uso real

A configuração é feita na interface, e o usuário faz estes passos porque envolvem dados dele:

1. **Carteira & Rede:** colar o endereço público e clicar em **Salvar endereço**.
2. Escolher o modo e clicar em **Salvar e conectar**. O padrão é **Mainnet solo, sem nó**. Recomende deixar **Transmitir automaticamente** ligado, porque um nonce válido não enviado não fica salvo.
3. **Inteligência Artificial:** escolher provedor, colar a chave, usar **Listar modelos**, definir intervalo e limite de chamadas e clicar em **Salvar**.
4. Só depois de o usuário aceitar o custo: **Iniciar palpites**.

Antes do passo 4, sugira um limite de chamadas baixo e confirme que o usuário entende as chances. Depois de reconectar, a IA fica parada e precisa ser iniciada de novo.

## 6. Diagnosticar erros

| Sintoma | Causa provável | Como resolver |
|---|---|---|
| `Failed to fetch` ou **Servidor parado** | O servidor está fechado. A página continua aberta, mas sem ninguém para responder. | Abrir o `iniciar.bat` de novo e recarregar a página com F5 |
| `token inválido` | O servidor reiniciou e o token mudou | Recarregar a página com F5 |
| Janela fecha ao abrir ou `ModuleNotFoundError` | Dependências faltando | Rodar o `pip install` da etapa 2 |
| Erro de porta em uso | Outra cópia já está aberta | Fechar a outra janela ou usar `--porta` |
| Conectado, mas sem bloco candidato | A consulta ainda não terminou ou há erro na fonte | Esperar alguns segundos e ver a aba **Registro** |
| `Limite de N chamadas…` | O contador só zera ao reabrir o programa | Aumentar o limite, clicar em **Salvar** e em **Iniciar palpites** |
| `A IA não respondeu só com o nonce` | O modelo escreveu texto; a chamada foi cobrada | Trocar de modelo se isso se repetir |
| `Insufficient funds` no regtest | Falta saldo maduro | Clicar antes em **Preparar 101 blocos** |

Para `Failed to fetch`, confirme a causa em vez de supor: veja se a porta responde com `diagnostico.py`. Os botões de conectar salvam a configuração antes, então, se a data de `data/config.json` não mudou com o clique, o pedido nem chegou ao servidor. Se a janela do servidor fecha sozinha, abra pelo terminal para ler o erro.

Para os demais erros, veja a seção 10 de `DOCUMENTACAO.md`.

## 7. Rodar os testes

```
.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_regtest.py
```

Esse comando não altera os dados do usuário; só cria a pasta `data/` vazia se ela não existir. Evite rodar `tests/test_regtest.py` direto no projeto: ele mina na blockchain de `data/regtest/` e deixa o nó ligado. Se precisar dessa prova, use o `testar_regtest.py`, que é isolado.

## 8. Publicar no GitHub

Antes de qualquer publicação, rode:

```
python .claude/skills/minerador-ia/scripts/verificar_publicacao.py
```

Ele lista o que entraria no repositório e procura padrões de chaves e os valores reais de `data/config.json`, sem exibi-los. Trate qualquer problema apontado antes de continuar. Se uma chave já tiver sido enviada ao GitHub, apagá-la em um novo commit não basta, porque ela continua no histórico: a chave precisa ser revogada no site do provedor.

Publique com Git, não arrastando a pasta para o site, porque o upload pelo navegador ignora o `.gitignore`. Só faça commit ou push quando o usuário pedir.

## Como relatar o resultado

Diga o que foi verificado de fato e o que não foi. O envio de um bloco na mainnet nunca aconteceu de verdade, e chamadas reais à IA só acontecem com a chave do usuário. No modo sem nó, "enviado" só significa entregue: a aceitação se confirma em um explorador de blocos.
