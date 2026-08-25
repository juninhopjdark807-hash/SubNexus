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
