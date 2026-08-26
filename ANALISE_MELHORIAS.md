# SubNexus — Análise de Melhorias (Funcionalidades e Desempenho)

Data: 25/08/2026
Escopo: `vtt_auto_editor.py` (2.863 linhas) e `interface_legendas_dark_progress_clean.py` (2.048 linhas).

## 1. Resumo executivo

O motor de edição VTT é **rápido e estável** (um arquivo com 2.500 cues processa em ~0,35s —
benchmark abaixo), então o gargalo de desempenho estava na **interface** (varreduras de
pasta a cada tick do auto-refresh e um processo PowerShell por rerun).

A maior descoberta funcional foi que **várias proteções e validações existentes no código
nunca eram invocadas** (código morto): caracteres suspeitos, trava de instância única e
o `config.json` no modo `--cms-flow`. Além disso, a interface tinha um **bug de runtime**:
qualquer clique nos botões da fila (`Adicionar à fila`, `Processar`, `Remover`, `Limpar fila`)
disparava exceção no Streamlit ≥ 1.37 por `st.rerun(scope="fragment")` fora do contexto de
fragmento. Todos os itens abaixo já foram **corrigidos e validados com testes**.

| Categoria | Corrigido nesta rodada |
|---|---:|
| Bugs funcionais (motor) | 5 |
| Bugs funcionais (interface) | 3 |
| Robustez do fluxo CMS | 3 |
| Desempenho (interface) | 3 |
| Limpeza de código morto | 3 (~210 linhas) |
| Qualidade (testes, requirements, gitignore) | 3 |

---

## 2. Bugs funcionais — motor (`vtt_auto_editor.py`)

### 2.1 Validação de caracteres suspeitos era código morto
`validate_suspicious_characters()` existia, o relatório TXT tinha a seção
"CARACTERES SUSPEITOS" e `build_status()` verificava `suspicious_characters` — mas a função
**nunca era chamada**. Consequência: o relatório sempre mostrava `0` e o status nunca virava
`ATENÇÃO — REVISAR PROBLEMAS` por causa de caracteres de encoding/OCR (ex.: `ŕ`).

**Correção:** `process_file()` agora executa a validação e grava os achados no relatório
JSON/TXT; o status final considera os caracteres suspeitos.
(Validado por `tests/test_vtt_engine.py::test_process_file_flags_suspicious_characters`.)

### 2.2 Trava de instância única nunca era acionada
`acquire_single_instance_lock()` / `notify_already_running()` estavam definidos, mas o
`main()` nunca os chamava. Abrir o `.bat` duas vezes (ou rodar dois fluxos CMS) corrompia o
perfil persistente do navegador (`perfil_navegador_cms`) e o CSV de status.

**Correção:** `main()` agora adquire a trava logo após o parse dos argumentos; se já houver
instância, avisa (pop-up/terminal) e encerra com `exit(1)`.

### 2.3 Linha final duplicada no `logs/cms_fluxo_status.csv`
No sucesso, a linha `Enviado` era gravada **duas vezes** (uma no bloco `try` e outra no
`finally`), em ambos os fluxos (`run_cms_flow` e `run_cms_upload_existing_flow`). O CSV
acumulava linhas finais duplicadas em todo processamento bem-sucedido.

**Correção:** a linha final é gravada uma única vez, no `finally`.

### 2.4 `--cms-flow` ignorava o `config.json`
O `config.json` só era lido **depois** do `return` do ramo `--cms-flow` — ou seja, o fluxo
real usado pela interface (download + edição + upload) sempre rodava com os padrões
(`fps=30`, 33/2/66), mesmo com `config.json` customizado.

**Correção:** o config é carregado e aplicado também no ramo CMS.

### 2.5 Página lenta do CMS virava "Sem legenda" (status final incorreto)
A espera do botão `DOWNLOAD SUBTITLE` era de 12s; estourou → `CmsNoSubtitleError` →
"Sem legenda" (tratado pela interface como **status final**, 100%, amarelo) — mesmo quando
era só Cloudflare/rede lenta.

**Correção:** antes de classificar "Sem legenda", o script faz uma segunda espera de 18s.
Página lenta → "Erro CMS" (recuperável/reprocessável); ausência real do botão → "Sem legenda".

---

## 3. Robustez do fluxo CMS

### 3.1 Retry de download transitório
Falha de rede/timeout durante o download agora é tentada **mais 1 vez** (5s de intervalo).
O download é idempotente (salva em `entrada/` com nome único), então a repetição é segura.
Erros de verdade (`CmsNoSubtitleError`) não são repetidos.

### 3.2 Recuperação de aba morta no meio da fila
Se a aba morria durante um item (crash, fechamento, target closed), o erro se propagava e
**todos os itens restantes da fila caíam no mesmo erro**. Agora, em exceção, o fluxo verifica
se a aba está fechada e recria-a (`cms_prepare_page`) para continuar o restante da fila; se o
contexto inteiro do navegador morreu, encerra o fluxo com log.

### 3.3 Interpretação do `config.json` no fluxo CMS (ver 2.4)

---

## 4. Bugs funcionais — interface (Streamlit)

### 4.1 `st.rerun(scope="fragment")` quebrava todo clique na fila (BUG DE RUNTIME)
No Streamlit 1.62, quando um widget **dentro** de um fragmento é clicado, roda um *full
rerun*; nesse contexto `st.rerun(scope="fragment")` **lança `StreamlitAPIException`**
(confirmado no código da fonte do Streamlit e reproduzido com `AppTest`). Resultado: qualquer
clique em `Adicionar à fila`, `Processar`, `Remover` ou `Limpar fila` exibiam a caixa de erro
vermelha na tela.

**Correção:** substituídas as 4 chamadas por `st.rerun()` (legal em full run; o fragmento
re-renderiza no mesmo ciclo). Validado: todos os fluxos de fila executam sem exceção.

### 4.2 Override obsoleto mascarava reprocessos bem-sucedidos
A interface guarda "overrides" de progresso em memória (ex.: `Erro`, 100%). Como o override
era aplicado quando `override_progress >= current_progress`, um **erro antigo** cobria um
**sucesso novo** do CSV (100 ≥ 100) — o item ficava travado em vermelho mesmo depois de
reprocessar com sucesso.

**Correção:** o override perde para o CSV quando a última linha do CSV para aquele Content ID
é **mais recente** (comparação por timestamp) e tem status final.

### 4.3 `Limpar execução atual` corrompia o fluxo em andamento
O botão renomeava `processo_atual.pid`, o CSV de status e a flag de parada **mesmo com o
processo rodando**, perdendo o rastreamento e corrompendo o CSV no meio da fila.

**Correção:** se há processo vivo (`is_pid_running()`), a limpeza é bloqueada com aviso.

---

## 5. Melhorias de desempenho — interface

| # | Problema | Correção | Efeito |
|---|---|---|---|
| 1 | `file_status()` refazia `glob`/`iterdir` de `entrada/` e `saida/` **para cada Content ID, a cada tick** do auto-refresh (3s) — com 300 itens pendentes e 300 arquivos, eram ~600 varreduras de pasta por tick | Índice `nome → caminho` por pasta, cacheado em `session_state` e invalidado pelo `mtime` da pasta; correspondência exata primeiro, fallback por substring | O custo por tick caiu de O(itens × arquivos) para O(1) (índice cacheado) + 1 passe na lista de nomes |
| 2 | `cms_manual_browser_open()` subia um **processo PowerShell** (timeout de 4s) a cada rerun completo da UI | Cache de 5s do resultado; a checagem antes de iniciar o fluxo continua fresca (`_cms_manual_browser_open_raw`) | Menos processos simultâneos e CPU liberada enquanto a UI atualiza |
| 3 | `image_data_uri()` re-leria e re-encoderia o logo em base64 a cada rerun | `@st.cache_data` | Sem custo repetido de E/S + base64 |

### Benchmark do motor (sem regressão)

Arquivo sintético com 2.500 cues (≈ 1h30 de vídeo, 211 KB), Python 3.11, Linux:

| Etapa | Antes | Depois |
|---|---:|---:|
| parse | 0,007s | 0,005s |
| edição de todos os cues | 0,322s | 0,285s |
| reparo de sobreposição + validações | 0,046s | 0,055s (inclui nova validação de caracteres) |

Conclusão: o motor segue com folga; não havia necessidade de refatorar o algoritmo de
divisão (regras determinísticas delicadas). O ganho de desempenho real veio da interface.

---

## 6. Novas funcionalidades na fila (pequenas, de alto valor)

- Botão **📄 Rel.** por item: abre o relatório TXT (ou JSON) do processamento, quando existe.
- Botão **▶ .vtt** por item: abre o arquivo final `saida/{content_id}.vtt` sem sair da interface.

---

## 7. Limpeza de código morto

- ~99 linhas irrealcancáveis em `main()` (bloco de renderização antigo duplicando toda a
  fila, incluindo o anti-padrão `time.sleep(secs) + st.rerun()` que bloqueava a thread).
- Bloco duplicado (irrealcancável) no final de `display_button_label()`.
- Função `cmd()` não utilizada (a construção do comando já vivia em `start_flow()`).

---

## 8. Qualidade e portabilidade

- **`tests/test_vtt_engine.py`** — 15 testes (pytest) cobrindo: limpeza de texto
  (`<i>`, `<br>`, travessão, reticências), limites 33/2/66, palavras nunca quebradas,
  diálogo preservado, round-trip de timecodes (4 formatos), distribuição/contiguidade de
  timecodes, reparo de sobreposição, relatório com caracteres suspeitos, header WEBVTT
  preservado e trava de instância única.
  Execução: `python -m pytest tests/ -v`
- **`requirements.txt`** — dependências antes só listadas no `.bat` (`streamlit`, `pandas`,
  `playwright`).
- **`.gitignore`** — artefatos de execução (`entrada/`, `saida/`, `relatorios/`, `Revisados/`,
  `logs/`, `perfil_navegador_cms/`, `*.pid`, `config.json`, estado) fora do repositório.
- A interface agora inicia o editor com `sys.executable` (em vez de `py` fixo): funciona em
  qualquer SO e usa o mesmo interpretador que roda o Streamlit.

---

## 9. Recomendações futuras (não implementadas — exigem acesso ao CMS ou decisão de escopo)

1. **Confirmação de upload**: `cms_upload_subtitle()` aciona o botão e deixa a confirmação
   "visual". Ideal: esperar um toast/estado de sucesso no modal e registrar no CSV
   (`Enviado` só quando confirmado). Exige validar o comportamento real do CMS.
2. **Retentativa de upload falho**: hoje upload é etapa única (risco de upload duplicado se a
   rede cair após o envio mas antes da confirmação). Sugerir retry somente com verificação de
   idempotência no CMS.
3. **Modularização**: os dois arquivos monolíticos funcionam, mas cresceram; um pacote
   `subnexus/` (engine, cms_flow, ui) facilitaria testes do fluxo Playwright. Manter os nomes
   dos `.bat` compatíveis.
4. **`config.json` de exemplo** versionado no repositório com todas as chaves documentadas.
5. **Rotação de logs**: `execucao.log` e `logs/cms_fluxo_status.csv` crescem sem limite.
6. **Upload em lote**: botão para enviar vários `saida/{id}.vtt` numa única sessão de
   navegador (hoje o botão Upload da fila é por item).
7. **Teste E2E do fluxo CMS** em ambiente de staging com Playwright (hoje os testes cobrem só
   o motor; o fluxo de navegador não pode ser validado sem o CMS).

---

## 10. Como validar

```text
py -m pip install -r requirements.txt
py -m pytest tests/ -v          # 15 testes do motor
py -m streamlit run interface_legendas_dark_progress_clean.py
```

Interface validada com `streamlit.testing.v1.AppTest`: render inicial, adicionar à fila
(com dedupe), selecionar item, remover e limpar fila — **zero exceções**.

---

## 11. Migração da interface: Streamlit → Tkinter local (25/08/2026)

A interface foi migrada de Streamlit para um aplicativo de desktop em **Python puro
(Tkinter, biblioteca padrão)**:

| | Antes (Streamlit) | Depois (local) |
|---|---|---|
| Arquivo | `interface_legendas_dark_progress_clean.py` | `interface_local.py` |
| Dependências | streamlit + pandas (pip) | **nenhuma** (só biblioteca padrão) |
| Como abre | servidor web + navegador | janela de desktop via `py interface_local.py` |
| Lançamento | `Iniciar_SubNexus.bat` (streamlit run) | `Iniciar_SubNexus.bat` (py interface_local.py) |

### O que foi mantido (mesmo comportamento/contratos)

- Fila persistida em `logs/fila_interface.json` (mesmo formato JSON — a fila criada em
  uma interface continua valendo na outra).
- Status lido de `logs/cms_fluxo_status.csv` (mesmos estados/progressos, mesm
  a tolerância a CSV antigo com 8 colunas e encodings utf-8-sig/latin-1).
- Botões por item: Processar/Reprocessar/Regerar, Upload (arquivo já gerado),
  Remover, abrir Relatório (TXT/JSON) e abrir `.vtt` final.
- Ações rápidas: Change Project, Confirmar instância, abrir pastas/tempos,
  Parar fluxo, Limpar execução (bloqueado com fluxo ativo), Limpar fila.
- Idioma (Português/Espanhol) bloqueado durante a fila; auto-refresh 2/3/5/10s;
  barra de progresso geral + métricas; aviso de instância/idioma; modo demonstração
  quando o `vtt_auto_editor.py` não existe.
- `start_flow`/`request_stop_flow`/`clean_exec`/PID/flag de parada: mesmo contrato
  de arquivos, então fluxo iniciado de qualquer uma das duas interfaces é rastreado.

### O que é novo/diferente

- A checagem do navegador do Change Project roda em **thread de segundo plano**
  (a cada 5s) — nenhum PowerShell na thread da UI.
- Iniciação do editor com `sys.executable` (mesmo interpretador).
- Status bar com mensagens de ação (equivalente aos toasts/warnings).
- A interface Streamlit **continua no repositório como legado**
  (`interface_legendas_dark_progress_clean.py`) — basta rodá-la para voltar ao modo web.

### Instalação (muda menos)

- `Iniciar_SubNexus.bat` agora verifica `py -c "import tkinter"` e abre a janela.
- `Instalar_Dependencias_SubNexus.bat` agora instala **apenas o Playwright**
  (necessário só para o fluxo CMS de download/upload) + Chromium.
  Streamlit e pandas saíram das dependências.
- `requirements.txt` documenta streamlit/pandas como **opcional** (só para o legado web).

### Validação

- `tests/test_interface_local.py`: 15 testes da camada de lógica sem display
  (fila, CSV de status, override obsoleto, file_status, botões, resumo,
  limpeza/stop/fluxo) — todos passando (suite total: 30 testes).
- Sintaxe e `pyflakes` limpos. O teste de fumaça da janela é executado quando
  há display disponível (skipped em CI sem display).

---

## 12. Correção dos arquivos .bat (iniciava sem efeito)

**Sintoma:** `Iniciar_SubNexus.bat` abria (ou nem abria) a janela de comando,
exibia as verificações e o aplicativo nunca era iniciado.

**Causa raiz:** os .bat haviam sido gravados com final de linha **apenas LF**
(gerados em ambiente Linux). O `cmd.exe` do Windows foi projetado para
arquivos batch com **CRLF**; com apenas LF o parser pode pular linhas,
encerrar o script antes do fim ou não executar o último comando —
comportamento inconsistente entre versões do Windows.

**Correções aplicadas:**

1. `Iniciar_SubNexus.bat` e `Instalar_Dependencias_SubNexus.bat` reescritos:
   - final de linha **CRLF**, conteúdo **puro ASCII**, sem BOM;
   - fluxo **100% baseado em `goto`** (nenhum bloco multi-linha `if (...)`,
     eliminando toda a classe de armadilhas de parsing do batch);
   - busca de Python com **fallback `py` → `python`**;
   - verificação de existência de `interface_local.py` e
     `vtt_auto_editor.py` **antes** de iniciar (com mensagem clara);
   - passo a passo numerado `[1/4]…[4/4]` com a pasta do projeto exibida;
   - ao final, o código de saída do aplicativo é exibido e o `pause` garante
     que a janela **nunca fecha antes do usuário ver o resultado**.
2. `.gitattributes` novo: `*.bat text eol=crlf` — qualquer checkout futuro
   (Windows ou Linux) materializa os .bat com CRLF, impedindo a regressão.
3. `interface_local.py`: o ponto de entrada agora captura exceções de
   inicialização, imprime o traceback completo no console e abre uma **janela
   de erro** (`_mostrar_erro_fatal`) — a falha nunca é mais silenciosa, nem
   quando o .py é executado sem console.

**Validação:** bytes dos .bat verificados (CRLF em todas as linhas, sem BOM,
ASCII); suíte de testes: 30 passed, 1 skipped (fumaça de GUI, sem display);
`pyflakes` limpo.

---

## 13. Correção de crash ao abrir com fila vazia (TclError)

**Sintoma:** ao executar `interface_local.py` em uma máquina limpa (sem
`logs/fila_interface.json`), o app quebrava na primeira atualização:

```
_tkinter.TclError: bad window path name
  ".../_render_queue" -> self.queue_placeholder.pack(pady=24)
```

**Causa raiz:** `_render_queue` destrói **todos** os filhos de
`queue_frame` a cada render — inclusive o `queue_placeholder`, que já
existia como filho desde o `_build_layout`. Com a fila vazia, o código
então chamava `pack()` na instância **já destruída** → `TclError`.
O bug só aparecia no caminho de fila vazia (abertura em máquina limpa ou
ao clicar em "Limpar fila"); com itens na fila o placeholder nunca era
repackado.

**Correção:** o placeholder agora é **recriado** a cada render
(`_create_queue_placeholder()`), em vez de repackar a instância antiga.
Adicionado teste de regressão `test_render_queue_empty_recreates_placeholder`
(reproduz o `TclError` exato com um mini-fake de widget antes da correção).

**Validação:** suíte com 31 testes passando (30 anteriores + 1 regressão),
1 skipped (fumaça de GUI sem display); `pyflakes` limpo.

---

## 14. Redesign visual da interface (elegante e moderno)

**Pedido do usuário:** "Odiei a interface, está muito feia e quadrada".

A camada visual foi reescrita por completo **sem alterar uma linha de
lógica** (fila, status, fluxo, botões mantêm exatamente o mesmo
comportamento e os mesmos atributos/métodos — coberto pelos 33 testes).

### O que mudou no visual

- **Cartões arredondados** (`RoundCard`): cabeçalho, sidebar, painéis e a
  lista da fila agora são cartões com cantos arredondados anti-aliasados
  (imagem gerada por `_rounded_photo`), sem nenhuma borda dura de 1px.
- **Botões em pill** (`RoundButton`): desenhados em canvas, com estados de
  *hover* e *pressionado*; variantes `primary` (gradiente azul→ciano),
  `default`, `cyan`, `danger` e `ghost`. API compatível com a anterior
  (`configure(command=...)`, `config(state=...)`, `config(text=...)`).
- **Paleta mais suave** (midnight): fundo `#0A0E18`, cartões `#111726`/
  `#171F33`, texto `#EEF2FA`, acento `#4E7DFF` e ciano `#3ED1E4`;
  cores de status mais suaves (verde-água, âmbar, vermelho suave).
- **Tipografia com hierarquia**: títulos de seção em maiúsculas pequenas e
  discretas, números de métricas grandes, corpo 10/9/8; IDs em Consolas
  ciano.
- **Linhas da fila** (`_QueueRow`): cartão arredondado com faixa vertical
  colorida pelo status à esquerda, checkbox arredondado, título/mensagem
  truncados com reticências, barra de progresso em pill, **chip de status
  arredondado** (sem borda) e botões em pill compactos.
- **Detalhes**: linha de gradiente azul→ciano sob o cabeçalho, banner de
  modo demonstração em pill âmbar, checkbox customizado arredondado,
  seletor de modo "Manual/Automático" em pills, medidores sem caixas
  (divisores sutis), status bar arredondada com flash em destaque.
- **Entrada de IDs**: área em "poço" arredondado (`C_CARD2`) com cursor
  azul e seleção em azul.

### Robustez adicionada

- `.gitattributes`: `*.bat binary` — os .bat ficam **armazenados com CRLF**
  no repositório (antes a normalização `text eol=crlf` guardava LF no blob
  e o arquivo no disco voltava a ficar LF, quebrando o cmd.exe de novo).
- Novo smoke test **sem display**: `tests/test_fake_tk_build.py` injeta um
  tkinter simulado (`sys.modules`) e constrói o app inteiro — valida a
  construção de cards, botões, linhas, chips e o ciclo
  adicionar → limpar fila. Suíte: **33 passed, 1 skipped**.
- `RoundButton.config(text=...)` agora refaz o desenho via `after_idle`
  (alargou o botão para o texto novo, ex.: "Processar fila inteira
  (processando...)" não fica cortado).

**Validação:** 33 testes (31 anteriores + 2 de construção fake-tk),
`pyflakes` limpo, auditoria estática (todas as chamadas `self.X()` têm
definição; todos os atributos são atribuídos), import headless ok.
A janela real só abre na máquina do usuário (Windows) via
`Iniciar_SubNexus.bat`.

---

## 15. Correção: `TclError: unknown option "-jointstyle"` no checkbox

**Sintoma:** ao abrir a interface nova (Windows, Python 3.14), o app
caía ao construir o checkbox da sidebar: `_tkinter.TclError: unknown
option "-jointstyle"`.

**Causa raiz:** `create_line` foi chamado com `capstyle="round"` e
`jointstyle="round"` — opções que não existem para itens de linha no Tk
(`jointstyle` nem sequer é o nome correto; o do polígono é `joinstyle`,
e linhas não têm opção equivalente em todas as versões do Tk).

**Correção:**

- Opções removidas dos dois `create_line` (check da sidebar e check da
  linha da fila) — a marca de check continua idêntica visualmente.
- **Blindagem do teste fake-tk:** o tkinter simulado agora valida as
  opções de `create_*` contra o conjunto do Tk 8.6 conservador e lança
  `TclError` para opção desconhecida — esse tipo de erro agora é pego
  no CI, sem depender de máquina com display.
- Auditoria estática extra: todas as chamadas `create_*` do arquivo
  conferidas com o conjunto de opções válidas (nenhuma inválida).

**Validação:** 33 passed, 1 skipped; pyflakes limpo.
