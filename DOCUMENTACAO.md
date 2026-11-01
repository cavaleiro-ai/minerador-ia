# Minerador IA: como funciona, passo a passo

O Minerador IA monta blocos de Bitcoin de verdade, pede a uma inteligência artificial um número (o **nonce**) para cada tentativa, confere esse número com SHA-256 duplo e, se ele fechar o bloco, transmite o bloco para a rede.

> **Antes de começar:** o programa é tecnicamente completo, mas não é uma forma de ganhar dinheiro. O SHA-256 não tem padrão, então o nonce da IA vale o mesmo que um número sorteado. Na mainnet a chance é de cerca de **1 em 637 sextilhões por tentativa** (medido em 31/10/2026) e cada chamada à IA custa dinheiro. Para ver um bloco ser aceito de verdade, use o [roteiro gratuito no regtest](#4-teste-completo-sem-gastar-nada-regtest).

**Índice**

1. [Visão geral](#1-visão-geral)
2. [Conceitos em um minuto](#2-conceitos-em-um-minuto)
3. [Passo a passo de uso](#3-passo-a-passo-de-uso)
4. [Teste completo sem gastar nada (regtest)](#4-teste-completo-sem-gastar-nada-regtest)
5. [O que acontece por dentro](#5-o-que-acontece-por-dentro)
6. [Os três modos de mineração](#6-os-três-modos-de-mineração)
7. [Chances e custos](#7-chances-e-custos)
8. [Segurança e privacidade](#8-segurança-e-privacidade)
9. [Arquivos do projeto](#9-arquivos-do-projeto)
10. [Problemas comuns](#10-problemas-comuns)
11. [Limitações conhecidas](#11-limitações-conhecidas)
12. [Testes e o que já foi verificado](#12-testes-e-o-que-já-foi-verificado)
13. [Referência técnica](#13-referência-técnica)

---

## 1. Visão geral

```
  mempool.space  ou  Bitcoin Core
          │  topo da cadeia, dificuldade, transações
          ▼
  ┌─────────────────────┐
  │ 1. Bloco candidato  │  coinbase pagando o seu endereço + transações
  └──────────┬──────────┘
             │  cabeçalho (76 bytes), alvo, nonces anteriores
             ▼
  ┌─────────────────────┐
  │ 2. IA (API paga)    │  responde só com um número: o nonce
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐   hash acima do alvo (quase sempre)
  │ 3. SHA-256 duplo    │ ───────────────► registra e volta ao passo 2
  │    hash ≤ alvo?     │
  └──────────┬──────────┘
             │  hash dentro do alvo
             ▼
  ┌─────────────────────┐
  │ 4. Monta o bloco    │  salva em data/blocos_encontrados.json
  │    e transmite      │  envia pela rede P2P ou pelo seu nó
  └─────────────────────┘
```

O processador do PC quase não trabalha: conferir um nonce custa só dois cálculos de SHA-256. O custo está nas chamadas à API da IA.

## 2. Conceitos em um minuto

| Termo | O que é |
|---|---|
| **Bloco candidato** | O bloco que o programa está tentando fechar. Só vale enquanto ninguém fechar aquela altura primeiro. |
| **Altura** | O número do bloco na cadeia. |
| **Cabeçalho** | Os 80 bytes que passam pelo hash: versão, hash do bloco anterior, raiz de merkle, horário, bits e nonce. Sem o nonce são 76 bytes. |
| **Nonce** | O número de 0 a 4.294.967.295 que ocupa os últimos 4 bytes do cabeçalho. É o que a IA responde. |
| **Hash** | O resultado de SHA-256 aplicado duas vezes ao cabeçalho. Mudar 1 no nonce muda o hash inteiro. |
| **Alvo** | O limite definido pela rede. O bloco é válido se o hash for menor ou igual ao alvo. |
| **Zeros no início** | Outra forma de ver o alvo: em 31/10/2026, o hash precisava começar com 79 bits zero. |
| **Coinbase** | A primeira transação do bloco. É ela que paga a recompensa ao seu endereço. |
| **Mempool** | As transações que esperam entrar em um bloco. As taxas delas somam na recompensa. |
| **Regtest** | Uma blockchain privada no seu PC, com as regras do Bitcoin e dificuldade mínima. As moedas dela não têm valor. |

## 3. Passo a passo de uso

### Passo 1: abrir o programa

Baixe o projeto e dê dois cliques em [iniciar.bat](iniciar.bat). O navegador abre em http://127.0.0.1:8765. A janela preta é o servidor e precisa ficar aberta.

Na primeira vez, o `.bat` cria o ambiente Python em `.venv` e instala as dependências. É preciso ter o Python 3.10 ou mais novo.

### Passo 2: cadastrar o endereço de recompensa

Na aba **Carteira & Rede**, cole o seu endereço público (`bc1…`, `1…` ou `3…`) e clique em **Salvar endereço**. O programa confere o endereço enquanto você digita e mostra o tipo e a rede.

Use só o endereço público. O programa nunca precisa da frase de recuperação (seed) nem da chave privada.

### Passo 3: escolher o modo

Ainda em **Carteira & Rede**, escolha um dos modos da [seção 6](#6-os-três-modos-de-mineração). O padrão é **Mainnet solo, sem nó**.

| Opção | Efeito |
|---|---|
| **Incluir transações da mempool** | Coloca transações no bloco para ganhar as taxas. Só vale no modo sem nó. |
| **Máximo de transações** | Padrão 25, limite 500. Só vale no modo sem nó. |
| **Transmitir automaticamente** | Envia o bloco assim que um nonce válido aparece. **Deixe ligado** (veja a [seção 11](#11-limitações-conhecidas)). |

### Passo 4: conectar

Clique em **Salvar e conectar**. O indicador no topo muda para **Conectado** e o bloco candidato aparece em poucos segundos no **Painel**. No teste de 31/10/2026, levou 8 segundos no modo sem nó.

Em **Testar conexão com a rede Bitcoin** você confere se o PC alcança os nós da rede. Esse botão só faz o aperto de mão do protocolo e não envia nada.

### Passo 5: configurar a IA

Na aba **Inteligência Artificial**:

1. Escolha o **provedor**: xAI Grok, Anthropic Claude, OpenAI ou outra API compatível com OpenAI (nesse caso, informe a URL base).
2. Cole a **chave da API**. Ela é criada no site do provedor.
3. Escolha o **modelo**. O botão **Listar modelos** preenche as opções disponíveis para a sua chave.
4. Ajuste o **intervalo entre chamadas** (padrão 5 s) e o **limite de chamadas** (padrão 200). O limite é a sua proteção contra gastos.
5. Clique em **Salvar**.

### Passo 6: iniciar os palpites

Clique em **Iniciar palpites**. A partir daí, cada chamada segue o ciclo descrito na [seção 5](#5-o-que-acontece-por-dentro) até você parar ou o limite ser atingido.

Desconectar ou reconectar também para a IA. Depois de **Salvar e conectar**, clique em **Iniciar palpites** de novo.

### Passo 7: acompanhar

| Aba | O que mostra |
|---|---|
| **Painel** | Altura, dificuldade, melhor palpite, tokens gastos, a chance real e o último nonce enviado e recebido |
| **Carteira & Rede** | Endereço, modo, opções e o laboratório regtest |
| **Inteligência Artificial** | Provedor e modelo, gráfico IA × acaso, chat com o copiloto e lista de palpites |
| **Bloco atual** | Cabeçalho, coinbase e transações incluídas |
| **Validação manual** | Testa um nonce digitado, emite o bloco se ele for válido e verifica blocos reais da blockchain pela altura |
| **Blocos enviados** | Cada envio feito e o resultado |
| **Registro** | Os últimos eventos do programa, inclusive erros |

O gráfico **IA × acaso** é a prova honesta do programa: para cada nonce da IA, um nonce sorteado é testado ao lado. As duas distribuições devem ficar iguais, a menos de variação estatística.

### Passo 8: encerrar

Clique em **Parar**, depois feche a janela preta. No modo regtest, clique antes em **Desligar nó**.

Configuração, tokens acumulados e blocos enviados ficam salvos em `data/`. Palpites, gráfico, chat e registro ficam só na memória e somem ao fechar.

## 4. Teste completo sem gastar nada (regtest)

Este roteiro leva um bloco com transações até a aceitação por um Bitcoin Core real, sem IA paga e sem endereço próprio. A sequência foi executada em 31/10/2026 com os resultados indicados.

1. Em **Carteira & Rede**, selecione **Regtest** e clique em **Salvar opções**. O Bitcoin Core portátil não vem no repositório: na primeira vez, clique em **Baixar Bitcoin Core** e espere o laboratório mostrar **instalado**. O download é conferido com o SHA256 oficial. Depois, clique em **Salvar e conectar**.
2. Clique em **Preparar 101 blocos**. Resultado: altura 101, saldo disponível de 50 BTC de teste e 5.000 BTC imaturos. Recompensas só podem ser gastas após 100 confirmações, por isso são 101 blocos.
3. Clique em **Criar 5 transações de teste** e aguarde cerca de 10 segundos. O bloco candidato passa a ter 6 transações: a coinbase e as 5 novas.
4. Abra **Validação manual** e clique em **Sortear um nonce**. No regtest, cerca de 1 em cada 2 tentativas é válida. Repita até aparecer **Nonce válido**.
5. Clique logo em **Emitir bloco** e confirme. Resultado: `o nó aceitou o bloco`, altura 102, mempool vazia e o bloco listado em **Blocos enviados**.

Para repetir o roteiro com a IA, siga os passos 1 a 3 e clique em **Iniciar palpites** em vez de usar a validação manual. As chamadas à API continuam sendo cobradas, mesmo no regtest.

Para recomeçar, use **Apagar blockchain de teste**. Isso apaga também a carteira de teste.

## 5. O que acontece por dentro

### Etapa 1: o servidor sobe

[run.py](run.py) inicia um servidor web local e abre o navegador. Ao iniciar, [server.py](minerador/server.py) gera um token aleatório e o controlador ([controller.py](minerador/controller.py)) carrega `data/config.json`. A interface pede o estado atual ao servidor a cada 1,5 segundo.

### Etapa 2: a fonte de dados acompanha a rede

| | Sem nó ([public_source.py](minerador/public_source.py)) | Com nó ou regtest ([node_source.py](minerador/node_source.py)) |
|---|---|---|
| Verifica o topo da cadeia | a cada 20 s | a cada 2 s |
| Remonta o candidato na mesma altura | a cada 90 s | a cada 30 s |
| Remonta na hora | bloco novo ou troca de endereço | bloco novo, troca de endereço ou após um envio |

### Etapa 3: o bloco candidato é montado

[job.py](minerador/job.py) e [btc.py](minerador/btc.py) fazem a montagem:

1. **Dados da rede.** Hash e altura do topo e `bits`. Quando a altura é múltipla de 2016, o modo sem nó calcula o novo alvo com a mesma regra do Bitcoin Core.
2. **Transações.** No modo sem nó, o programa pega a lista das 10 transações mais recentes da mempool e descarta as que dependem de outra ainda não confirmada. Depois recalcula o `txid` para conferir o dado, ordena por taxa por peso e evita gastar a mesma moeda duas vezes. No modo com nó, usa as transações do `getblocktemplate`.
3. **Coinbase.** Traz a altura do bloco, 8 bytes de extranonce e a etiqueta `/MineradorIA/`. Tem duas saídas: a recompensa (subsídio + taxas) para o seu endereço e o compromisso SegWit com valor zero.
4. **Raiz de merkle e cabeçalho.** A raiz resume todas as transações, e o cabeçalho é montado com ela. O nonce fica em aberto.

Trocar o endereço com o programa conectado vale na hora: o candidato antigo é descartado, e nenhum bloco montado com o endereço anterior é aproveitado.

### Etapa 4: a IA é chamada

O laço em [ai.py](minerador/ai.py) envia uma mensagem com este formato (valores ilustrativos e encurtados):

```
Altura do bloco candidato: 974042
Cabeçalho do bloco candidato (76 bytes, sem o nonce, hex): 00000020…
Alvo (hex): 00000000000000000001e5ac…
Nonce do bloco anterior (altura 974041): 3932395645
Nonce anterior testado neste bloco: 1234 (hash 8f3a…, não fechou o bloco)
Calcule o próximo nonce, levando o tempo que precisar. Responda somente com o nonce (apenas os dígitos, nada mais).
```

O texto pede que a IA "calcule", mas isso não dá a ela nenhuma vantagem. Um modelo não tem como escolher um nonce que produza um hash baixo sem testar de fato, e os testes necessários são astronômicos. Modelos com raciocínio só gastam mais tokens por chamada.

O programa espera até 10 minutos por cada resposta. Vale apenas a primeira linha da resposta, que precisa conter só o número. Formas como `0x7c2bac1d`, `2.083.236.893` e `Nonce: 42` são aceitas. Qualquer outra resposta é descartada, mas a chamada já foi cobrada.

Se a chamada falhar, o programa espera 5 s e dobra a espera a cada nova falha, até 120 s.

### Etapa 5: o nonce é testado

Quando a resposta chega, o programa verifica se a altura ainda é a mesma:

- **Altura mudou:** a rede fechou o bloco enquanto a IA calculava. A resposta é descartada e o laço segue para o próximo bloco.
- **Mesma altura:** o programa monta o cabeçalho de 80 bytes, calcula `SHA-256(SHA-256(cabeçalho))` e compara com o alvo. Também testa um nonce sorteado, só para a comparação do gráfico.

O nonce e o hash voltam na próxima chamada como "nonce anterior". Depois, o programa espera o intervalo configurado e repete.

### Etapa 6: o bloco é transmitido (se o nonce for válido)

1. O programa testa o nonce de novo e monta o bloco completo: cabeçalho, coinbase com witness e transações.
2. Depois envia o bloco:
   - **Modo sem nó** ([p2p.py](minerador/p2p.py)): descobre nós pelos DNS seeds oficiais, conecta-se a até 12, faz o aperto de mão e manda a mensagem `block`.
   - **Com nó ou regtest:** usa o comando `submitblock`, que responde na hora se o nó aceitou.
3. O bloco completo é salvo em `data/blocos_encontrados.json`, mesmo se o envio falhar, e aparece em **Blocos enviados**.

Na mainnet, a recompensa só pode ser gasta depois de 100 confirmações. Se outro minerador fechar a mesma altura e a rede seguir o bloco dele, o seu bloco fica de fora e a recompensa não vale.

## 6. Os três modos de mineração

| | Mainnet solo, sem nó | Mainnet com nó próprio | Regtest |
|---|---|---|---|
| **Precisa de** | Internet e endereço mainnet | Bitcoin Core sincronizado, com RPC ativo, e endereço da mesma rede | Só o Bitcoin Core portátil, baixado pelo programa |
| **Dados vêm de** | API pública do mempool.space | O seu nó | Nó local |
| **Envio do bloco** | P2P direto para os nós | `submitblock` no seu nó | `submitblock` no nó local |
| **Resposta do envio** | Só confirma a entrega | O nó diz se aceitou | O nó diz se aceitou |
| **Recompensa vai para** | Seu endereço | Seu endereço | Carteira de teste |
| **Dinheiro real?** | Sim, se um bloco fechar | Sim, se um bloco fechar | Não |
| **Chance por tentativa** | ~1 em 637 sextilhões | ~1 em 637 sextilhões | ~1 em 2 |

No modo com nó, informe host, porta RPC (padrão 8332) e usuário e senha ou o caminho do arquivo `.cookie`.

## 7. Chances e custos

Valores medidos em 31/10/2026. O **Painel** mostra os números atualizados.

| Item | Valor |
|---|---|
| Altura | 974.042 |
| Dificuldade | ~148 trilhões |
| Zeros exigidos no início do hash | 79 bits |
| Chance por tentativa | 1 em ~637 sextilhões |
| Recompensa de um candidato real | 3,125 BTC + 0,00004583 BTC em taxas (7 transações) |

Para comparar: a rede inteira testa cerca de 1 sextilhão de hashes por segundo. A 1 tentativa a cada 10 segundos, a média para fechar um bloco seria de **cerca de 200 quatrilhões de anos**, aproximadamente 15 milhões de vezes a idade do universo.

**Como o gasto é contado**

- **Chamadas X de Y** (Painel) conta só os palpites da IA desde que o programa abriu.
- **Tokens gastos** (Painel) acumula todas as sessões e inclui o chat. Fica em `data/uso_ia.json`.
- O custo em dólar depende do provedor: a xAI informa o valor, para o Claude é uma estimativa por uma tabela fixa em [ai.py](minerador/ai.py), que pode ficar defasada, e para OpenAI e APIs compatíveis nenhum valor aparece. O valor real é sempre o do painel do provedor.

## 8. Segurança e privacidade

**O que protege o programa**

- O servidor escuta só em `127.0.0.1`, então outros computadores não têm acesso.
- O cabeçalho `Host` é conferido, e cada chamada à API local exige um token criado a cada abertura. Sites abertos no navegador não conseguem comandar o minerador. Nos testes, chamadas sem token ou com outro `Host` receberam erro 403.

**O que fica sob a sua responsabilidade**

- As chaves de API ficam em **texto puro** em `data/config.json`. A tela mostra só uma versão mascarada. **Não compartilhe esse arquivo.** Se uma chave vazar, gere outra no site do provedor.
- Nunca digite a seed ou a chave privada em lugar nenhum do programa.
- A pasta `data/` está no `.gitignore`. Publique com Git, não arrastando a pasta para o site do GitHub, porque o upload pelo navegador ignora o `.gitignore`. Antes de publicar, rode `.claude/skills/minerador-ia/scripts/verificar_publicacao.py`, que procura segredos no que seria enviado sem exibi-los.
- Se uma chave chegar a ser publicada, apagá-la em um novo commit não basta, porque ela continua no histórico. Revogue-a no site do provedor.

**O que sai do seu PC**

| Destino | O que recebe |
|---|---|
| **Provedor de IA** | Cabeçalho, alvo e nonces a cada palpite. No chat, também o estado do minerador, com o seu endereço público. |
| **mempool.space** | Consultas de dados públicos, que expõem o seu IP. Essas consultas acontecem mesmo desconectado, para atualizar as estatísticas da rede. |
| **Nós da rede Bitcoin** | O seu IP, ao transmitir um bloco ou usar o teste de conexão. |

## 9. Arquivos do projeto

**Dados** (`data/`, fora do Git e criados pelo programa)

| Arquivo | Conteúdo | Pode apagar? |
|---|---|---|
| `config.json` | Endereço, modo e **chaves de API** | Sim, mas perde as configurações |
| `uso_ia.json` | Total acumulado de tokens e custo | Sim, zera o contador |
| `blocos_encontrados.json` | Blocos enviados, com o conteúdo completo. Só é criado no primeiro envio. | **Não**, se houver bloco real |
| `regtest/` | Blockchain e carteira de teste | Sim, com o botão **Apagar blockchain de teste** |

**Código**

| Arquivo | Função |
|---|---|
| [iniciar.bat](iniciar.bat) | Prepara o ambiente e abre o programa |
| [run.py](run.py) | Inicia o servidor. Aceita `--porta` e `--sem-navegador` |
| [minerador/server.py](minerador/server.py) | API web local e proteções |
| [minerador/controller.py](minerador/controller.py) | Junta tudo: configuração, teste de nonces, envio e registro |
| [minerador/ai.py](minerador/ai.py) | Provedores de IA, laço de palpites, chat e contagem de tokens |
| [minerador/job.py](minerador/job.py) | Bloco candidato: testa nonces e monta o bloco final |
| [minerador/btc.py](minerador/btc.py) | Núcleo Bitcoin: hashes, endereços, coinbase, merkle e dificuldade |
| [minerador/public_source.py](minerador/public_source.py) | Modo sem nó (mempool.space) |
| [minerador/node_source.py](minerador/node_source.py) | Modos com Bitcoin Core |
| [minerador/p2p.py](minerador/p2p.py) | Envio direto pela rede P2P |
| [minerador/regtest.py](minerador/regtest.py) | Baixa, liga e opera o nó de teste |
| [minerador/rpc.py](minerador/rpc.py) | Comunicação com o Bitcoin Core |
| [minerador/paths.py](minerador/paths.py) | Caminhos das pastas |
| [web/](web/) | Interface no navegador |
| [tests/](tests/) | Testes automáticos |
| [.claude/skills/minerador-ia/](.claude/skills/minerador-ia/SKILL.md) | Skill do Claude Code para instalar, testar, diagnosticar e publicar, com scripts prontos |
| `bitcoin-core/` | Bitcoin Core portátil para o regtest. Fica fora do Git e é baixado pelo programa |

## 10. Problemas comuns

| O que aparece | Causa | O que fazer |
|---|---|---|
| `Python nao encontrado` | Python ausente ou fora do PATH | Instale o Python 3.10 ou mais novo em python.org |
| `ModuleNotFoundError` na janela preta | A instalação das dependências falhou na primeira vez. O `.bat` não tenta de novo, porque `.venv` já existe. | Rode `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Erro de porta em uso | O programa já está aberto ou a porta está ocupada | Feche a outra janela ou rode `.venv\Scripts\python.exe run.py --porta 9000` |
| `Failed to fetch` ou indicador **Servidor parado** | A janela preta foi fechada e a página ficou aberta sem servidor | Abra o `iniciar.bat` de novo e recarregue a página com F5 |
| `token inválido` | O programa reiniciou, e o token mudou | Recarregue a página com F5 |
| `Cadastre o endereço da sua carteira antes de conectar` | Falta o endereço | Faça o [passo 2](#passo-2-cadastrar-o-endereço-de-recompensa) |
| `Endereço inválido: checksum…` | Endereço digitado errado | Copie e cole de novo |
| `O modo solo sem nó é só para a mainnet` | Endereço de testnet ou regtest | Use um endereço `bc1…`, `1…` ou `3…` |
| `Dados públicos indisponíveis` | Sem internet ou mempool.space fora do ar | O programa tenta de novo a cada 20 s |
| `Não foi possível falar com o nó` | Nó desligado ou RPC incorreto | Confira host, porta e usuário e senha ou `.cookie` |
| `Cadastre a chave da API` | Falta a chave do provedor escolhido | Faça o [passo 5](#passo-5-configurar-a-ia) |
| `Escolha um modelo na aba IA` | Modelo em branco | Use **Listar modelos** |
| `Chave da API inválida ou sem permissão` | Chave errada ou revogada | Gere outra no site do provedor |
| `Modelo … não encontrado para esta chave` | A chave não dá acesso ao modelo | Use **Listar modelos** |
| `Limite de uso da API atingido` | Rate limit do provedor | O programa tenta de novo sozinho, ou aumente o intervalo |
| `A IA não respondeu só com o nonce` | O modelo respondeu com texto, e a chamada foi cobrada | Troque de modelo se isso se repetir |
| `Limite de N chamadas à IA atingido` | Chegou ao limite configurado | Aumente o limite, clique em **Salvar** e em **Iniciar palpites**, ou reabra o programa |
| `Bitcoin Core ainda não foi baixado` | Falta o nó de teste | Clique em **Baixar Bitcoin Core** |
| `Conecte-se no modo Regtest primeiro` | **Preparar 101 blocos** sem conexão | Conecte no modo Regtest |
| `Insufficient funds` | Transações de teste sem saldo maduro | Clique antes em **Preparar 101 blocos** |

## 11. Limitações conhecidas

**Podem fazer você perder um bloco válido**

- **Um nonce válido não emitido não fica salvo.** `blocos_encontrados.json` só registra blocos que passaram pelo envio. Com a transmissão automática desligada, um nonce da IA fica só na memória e no registro.
- **A emissão manual usa o candidato atual.** O candidato muda a cada 90 s (sem nó) ou 30 s (com nó ou regtest). Se ele mudar entre **Testar** e **Emitir bloco**, o mesmo nonce deixa de ser válido e o bloco não é enviado. Por isso, deixe a transmissão automática ligada e emita na hora.
- **No modo sem nó, "enviado" não significa "aceito".** O ✓ indica que pelo menos um nó recebeu o bloco, sem confirmar que ele foi aceito. A prova é o hash aparecer em um explorador como o mempool.space.
- **O modo sem nó confia nos dados do mempool.space.** O programa confere o `txid` e as entradas confirmadas, mas não valida assinaturas nem a taxa informada. Também não confere o limite de peso do bloco, o limite de sigops ou os bloqueios de tempo das transações. Uma transação problemática faria o bloco inteiro ser rejeitado. Para eliminar esse risco, desligue **Incluir transações** ou use o modo com nó.

**Podem aumentar o gasto com a IA**

- **Parar não cancela a chamada em andamento.** Ela continua até responder, é cobrada e o nonce é testado.
- **Parar e iniciar com uma chamada em andamento cria dois laços simultâneos**, o que dobra o ritmo de gasto. Isso foi reproduzido em teste. Depois de **Parar**, espere a última chamada terminar antes de **Iniciar**. Se tiver dúvida, feche e reabra o programa.
- **O chat não entra no limite de chamadas.** Cada mensagem também reenvia a conversa inteira, então as mensagens ficam mais caras à medida que a conversa cresce.
- **O limite vale por execução e não zera ao parar e iniciar.** Respostas inválidas contam para o limite. Chamadas que falham com erro não contam.

**Outros pontos**

- **Poucas taxas no modo sem nó.** Como o programa só vê 10 transações recentes por atualização, o bloco tem poucas e a recompensa é quase só o subsídio. No teste foram 7 transações e 4.583 satoshis de taxas.
- **Nó de teste em segundo plano.** Se o programa encontrar um nó regtest já ligado, ele o reutiliza e não o desliga ao fechar. Fechar a janela preta pelo X também pode deixar o nó rodando. Use **Desligar nó**.
- **`tests/test_regtest.py` usa a sua blockchain de teste.** Veja a [seção 12](#12-testes-e-o-que-já-foi-verificado).

## 12. Testes e o que já foi verificado

Para rodar os testes sem tocar nos seus dados:

```
.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_regtest.py
```

**Atenção:** `tests/test_regtest.py` usa o mesmo `data/regtest/` do programa, mina blocos nessa blockchain e deixa o nó ligado no final. Ele é pulado se o Bitcoin Core não tiver sido baixado.

Para a mesma prova de forma isolada, em uma pasta temporária e sem chaves:

```
.venv\Scripts\python.exe .claude\skills\minerador-ia\scripts\testar_regtest.py
```

**Resultado em 31/10/2026**, em uma cópia do projeto, sem chaves ou dados pessoais e sem chamar APIs de IA:

| Verificação | Resultado |
|---|---|
| Testes automáticos | 29 de 29 passaram, incluindo o aceite de blocos por um Bitcoin Core real, por RPC e por P2P |
| Candidato real da mainnet (modo sem nó) | Montado em 8 s, com 7 transações |
| Aperto de mão com nós reais da mainnet | 4 de 6 nós responderam |
| Bloco real 840000 | Hash recalculado idêntico ao oficial |
| Roteiro regtest da [seção 4](#4-teste-completo-sem-gastar-nada-regtest) | Bloco com 6 transações aceito pelo nó |
| Instalação limpa de um clone Git, no Python 3.12 | Ambiente e dependências instalados, 27 testes sem o regtest passaram e o Bitcoin Core foi baixado e conferido |

**O que não foi verificado**

- **A transmissão de um bloco válido na mainnet nunca aconteceu.** A entrega por P2P foi comprovada só no regtest, e um bloco real exigiria um nonce válido na mainnet.
- **Chamadas reais às APIs de IA não foram feitas neste teste.** O laço de palpites foi testado com um cliente simulado.
- **A instalação limpa não passou pelo `iniciar.bat` nem pelo navegador.** Os mesmos comandos foram executados no terminal, e o regtest foi exercido pela API local.
- **Python 3.10 e 3.11, Linux e macOS não foram testados.**

## 13. Referência técnica

### Cabeçalho do bloco (80 bytes)

| Bytes | Campo | Formato |
|---|---|---|
| 0 a 3 | Versão (`0x20000000` no modo sem nó) | Inteiro little-endian |
| 4 a 35 | Hash do bloco anterior | Ordem interna (invertida em relação ao explorador) |
| 36 a 67 | Raiz de merkle | Ordem interna |
| 68 a 71 | Horário Unix | Inteiro little-endian |
| 72 a 75 | `bits` (alvo compacto) | Inteiro little-endian |
| 76 a 79 | Nonce | Inteiro little-endian |

O hash é válido quando `int.from_bytes(sha256d(cabeçalho), "little") <= alvo`. A chance por tentativa é `alvo / 2^256`.

### Transação coinbase

A coinbase fica dividida em duas partes, com o extranonce entre elas: `coinb1 + extranonce + coinb2`.

| Parte | Conteúdo |
|---|---|
| Entrada | Hash zerado, índice `0xffffffff` e `nSequence` `0xfffffffe` |
| `scriptSig` | Altura (BIP34) + 8 bytes de extranonce + `/MineradorIA/` |
| Saída 0 | Subsídio + taxas, para o script do seu endereço |
| Saída 1 | Valor 0, `OP_RETURN` com o compromisso SegWit (BIP141) |
| `nLockTime` | Altura menos 1 |
| Witness | 32 bytes zerados, só no bloco final. O `txid` e a raiz de merkle usam a versão sem witness |

Os palpites da IA usam sempre extranonce zerado. A variação do cabeçalho vem do nonce, do horário e das transações.

### Processos em execução

| Linha de execução | Função | Ritmo |
|---|---|---|
| Servidor (uvicorn) | Atende a interface | A interface consulta a cada 1,5 s |
| Dados da rede (`_network_loop`) | Hashrate, dificuldade e altura, pelo mempool.space | A cada 60 s, mesmo desconectado |
| Fonte de blocos (`fonte-publica`, `fonte-no`, `fonte-regtest`) | Monta os candidatos | Veja a [seção 5](#5-o-que-acontece-por-dentro) |
| Palpites (`ia-palpites`) | Chama a IA e testa os nonces | Duração da chamada + intervalo configurado |
| `bitcoind` | Nó regtest, em processo separado | RPC em 18443 e P2P em 18444, só em `127.0.0.1` |

### Campos de `data/config.json`

| Campo | Padrão | Significado | Quando vale |
|---|---|---|---|
| `endereco` | vazio | Endereço da recompensa | Na hora, remonta o candidato |
| `modo` | `publico` | `publico`, `no` ou `regtest` | Ao reconectar |
| `incluir_transacoes` | `true` | Coloca transações no bloco (modo sem nó) | Ao reconectar |
| `max_transacoes` | `25` | De 0 a 500 (modo sem nó) | Ao reconectar |
| `envio_automatico` | `true` | Transmite ao achar um nonce válido | Na hora |
| `no.host`, `no.porta` | `127.0.0.1`, `8332` | Endereço do RPC | Ao reconectar |
| `no.usuario`, `no.senha`, `no.cookie` | vazios | Acesso ao RPC. O cookie tem prioridade | Ao reconectar |
| `ia.provedor` | `xai` | `xai`, `anthropic`, `openai` ou `compat` | Na próxima chamada |
| `ia.chaves.*` | vazias | Chave de cada provedor, **em texto puro** | Na próxima chamada |
| `ia.modelos.*` | Definidos em `PROVIDERS` | Modelo de cada provedor | Na próxima chamada |
| `ia.base_url_compat` | vazio | URL da API compatível | Na próxima chamada |
| `ia.intervalo` | `5` | Segundos entre chamadas, de 0 a 3600 | Na próxima chamada |
| `ia.max_chamadas` | `200` | Limite por execução | Na próxima chamada |

### API local

A API só atende `127.0.0.1` ou `localhost`. Toda rota `/api/` exige o cabeçalho `X-Token`, com o token que vem na página inicial. Erros voltam como `{"erro": "mensagem"}`.

| Método e rota | Função |
|---|---|
| `GET /api/status` | Estado completo: conexão, bloco, IA, registro e blocos enviados |
| `GET /api/config`, `POST /api/config` | Lê (com chaves mascaradas) ou altera a configuração |
| `POST /api/endereco/validar` | Valida `{endereco}` |
| `POST /api/conectar`, `POST /api/desconectar` | Conecta ou desconecta. Os dois param a IA |
| `GET /api/bloco` | Detalhes do bloco candidato, com as transações |
| `POST /api/manual/testar` | Testa `{nonce, extranonce?, horario?}` sem enviar |
| `POST /api/manual/emitir` | Testa e, se o nonce for válido, envia o bloco |
| `GET /api/verificar-bloco?altura=N` | Recalcula o hash de um bloco real |
| `POST /api/hash-cabecalho` | Calcula o hash a partir dos campos do cabeçalho |
| `POST /api/ia/iniciar`, `POST /api/ia/parar` | Inicia ou para os palpites |
| `GET /api/ia/modelos?provedor=X` | Lista os modelos da chave salva |
| `POST /api/ia/chat`, `POST /api/ia/chat/limpar` | Envia `{mensagem}` ao copiloto ou limpa a conversa |
| `POST /api/regtest/baixar` | Baixa o Bitcoin Core e confere o SHA256 |
| `POST /api/regtest/ligar`, `POST /api/regtest/desligar` | Liga ou desliga o nó de teste |
| `POST /api/regtest/preparar` | Minera `{quantidade}` blocos (padrão 101) |
| `POST /api/regtest/transacoes` | Cria `{quantidade}` transações (padrão 5, máximo 50) |
| `POST /api/regtest/resetar` | Apaga a blockchain e a carteira de teste |
| `POST /api/p2p/testar` | Faz o aperto de mão com até 6 nós, sem enviar bloco |

### Formato de `data/blocos_encontrados.json`

É uma lista com o envio mais recente primeiro. Cada item tem estes campos:

| Campo | Conteúdo |
|---|---|
| `quando` | Horário Unix do envio |
| `altura`, `hash`, `nonce` | Identificação do bloco |
| `origem` | `IA` ou `você (manual)` |
| `modo`, `rede` | Modo de mineração e rede |
| `recompensa` | Valor em satoshis |
| `transacoes` | Quantidade, com a coinbase |
| `resultado` | `{ok, detalhe}` ou `{ok, motivo}` |
| `bloco_hex` | Bloco completo em hexadecimal, que permite reenviá-lo por outro meio |

### Como adicionar um provedor de IA

Qualquer API compatível com OpenAI funciona sem mudar o código: use o provedor **Outra API compatível com OpenAI** e informe a URL base. Para um provedor fixo na lista, acrescente uma entrada em `PROVIDERS`, em [ai.py](minerador/ai.py), com `nome`, `base_url` e `modelo`. A chave e o modelo passam a aparecer na interface, sem outras alterações.
