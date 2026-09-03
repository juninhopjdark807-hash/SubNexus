# Análise crítica de `benchmark_cms.py`

**Data da análise:** 2026-09-02

**Escopo:** revisão estática do código no commit-base `8b9be52`; não houve execução no Windows nem acesso autenticado ao CMS. A árvore de acessibilidade real, os domínios do player e os endpoints de API ainda precisam ser levantados em uma estação-alvo.

## Conclusão executiva

A arquitetura atual **não é adequada como fonte de evidência para um benchmark corporativo por etapa**. Ela pode ser útil como protótipo de descoberta da árvore de acessibilidade, mas não deve alimentar números publicados.

O problema central não é uma expressão regular isolada: o código registra a **presença de palavras na árvore acessível** como se fosse uma ação do usuário ou a conclusão de uma operação. Estes são eventos diferentes:

1. `available`: o controle apareceu/ficou habilitado;
2. `intent`: o usuário o acionou;
3. `accepted`: o CMS aceitou a ação/iniciou a operação;
4. `completed`: a operação terminou com sucesso ou falha conhecida.

O script atual mede quase exclusivamente o primeiro evento e nomeia o resultado como se fosse o segundo ou o quarto. Além disso, o tempo total não corresponde ao fluxo declarado: o Content ID é digitado antes do início da medição, excluindo “identificar Content ID na planilha”, e o encerramento inclui a troca de foco do CMS para o terminal.

### Recomendação principal

Em ordem de preferência:

1. **Telemetria no frontend/backend do CMS**, se houver possibilidade de alteração ou acesso ao audit log/API do CMS.
2. Caso contrário, **Chrome normal + extensão Manifest V3 estritamente passiva + coletor nativo do Windows**. A extensão observa eventos DOM confiáveis, downloads, abas, navegação e respostas de rede; não sintetiza cliques, não assume controle do `BrowserContext`, não muda o destino de downloads e não usa Playwright/CDP.
3. Usar **eventos do Windows e watcher de filesystem como evidência complementar**, especialmente para Subtitle Edit, troca de aplicativo e disponibilidade física do arquivo.
4. Manter UI Automation apenas como fallback/diagnóstico. OCR deve ser o último recurso.

Se instalação de extensão e telemetria do CMS forem proibidas, a alternativa metodologicamente defensável é medir apenas o **tempo total por hotkey global**, complementar com gravação auditável e codificação humana das etapas. Não se deve apresentar os eventos heurísticos atuais como tempos precisos de etapa.

### Implementação resultante

A alternativa recomendada foi implementada em `benchmark_cms_passivo.py` + `benchmark_extension/`. Para permitir execução direta em Python sem instalar previamente um host nativo assinado no Registro do Windows, a primeira versão usa transporte HTTP autenticado e restrito a `127.0.0.1`, com fila, sequência, deduplicação e log append-only. Em distribuição corporativa empacotada, esse transporte pode ser trocado por Native Messaging sem alterar o contrato de eventos.

---

## 1. Capacidade de `pywinauto`/Windows UI Automation no Chrome

### Resposta curta

**Consegue observar parte da aplicação web, mas não com confiabilidade suficiente para ser a fonte primária deste benchmark.**

O Chrome projeta sua árvore interna de acessibilidade para APIs nativas do Windows, incluindo UI Automation. Essa árvore não é o DOM. Ela é derivada de HTML, CSS, ARIA, estado de renderização e decisões de poda do Chrome. Portanto:

- elementos sem semântica acessível, `aria-hidden`, canvas, controles customizados, partes virtualizadas e alguns componentes do player podem não aparecer;
- nome, papel, estado e hierarquia dependem da implementação do CMS e podem mudar com uma atualização do CMS ou do Chrome;
- um controle visível pode aparecer como `Button`, `Text`, `Pane`, `Group` ou apenas como nome de um ancestral;
- abas em background, conteúdo não renderizado e elementos fora da tela podem ter exposição diferente;
- consultar a árvore pode ativar o modo de acessibilidade completo do Chrome e gerar custo de CPU/serialização.

A própria documentação do `pywinauto` historicamente recomenda iniciar Chrome com `--force-renderer-accessibility`. O comando atual (`benchmark_cms.py:205-213`) não usa a opção e também não executa um preflight que confirme que o `Document` do CMS e controles esperados estão realmente expostos. Versões atuais do Chrome podem habilitar acessibilidade sob demanda, mas isso não deve ser presumido em uma coleta corporativa.

Outro problema é o modo de leitura: `get_window_text()` percorre primeiro todos os descendentes `Text` e depois todos os descendentes novamente (`benchmark_cms.py:357-389`). Isso perde identidade/contexto e pode ser caro em uma SPA dinâmica. O intervalo nominal de 250 ms não é a resolução real, pois o código dorme **depois** de uma varredura de duração ilimitada.

### Veredito

- Útil para inspeção, preflight e sinal secundário.
- Inadequado, sozinho, para provar “o usuário clicou” ou “a operação terminou”.
- O polling integral atual pode ser mais intrusivo que uma extensão passiva baseada em eventos.

---

## 2. Detecção confiável de cliques ou mudanças de estado sem controlar o navegador

### Observação puramente externa

É possível obter sinais, mas não uma semântica completa e confiável:

- hook global de mouse/teclado informa que houve entrada e suas coordenadas;
- `ElementFromPoint`/UIA pode tentar associar a coordenada a um elemento acessível;
- `InvokePattern.InvokedEvent`, foco e mudanças de propriedades UIA podem indicar ativação;
- `SetWinEventHook` informa criação de janela e troca de foreground.

Esses sinais não provam que:

- o alvo era o botão correto do Content ID correto;
- o clique não foi cancelado ou caiu sobre um overlay;
- a aplicação aceitou a ação;
- a requisição terminou com sucesso.

Também não cobrem igualmente mouse, teclado, atalhos, toque e controles web sem `InvokePattern` correto. Um evento `Invoked` indica ativação reportada pelo provider, não necessariamente um clique físico, e continua sem representar conclusão de backend.

### Observação interna, mas não controladora

Uma extensão passiva consegue separar melhor os eventos:

- listener em fase de captura para `click`, `change`, `submit`, `play`, `pause`, `visibilitychange`, sem `preventDefault` ou mutação do DOM;
- `event.isTrusted` como evidência de evento originado pelo agente do usuário (não é, sozinho, prova antifraude);
- `chrome.downloads`, `chrome.tabs`, `chrome.windows` e `chrome.webNavigation` para eventos do navegador;
- `chrome.webRequest` somente observacional para início/fim/status das chamadas relevantes;
- MutationObserver estreito para transições de estado/success toast, nunca sobre o documento inteiro sem filtro.

Isso é **instrumentação**, mas não é automação nem controle. Para validade do benchmark, “não reagir e não perturbar” é um requisito mais importante do que “estar fora do processo do Chrome”.

---

## 3. Validade dos detectores atuais

| Campo atual | O que o código realmente detecta | Avaliação |
|---|---|---|
| `editar` | Primeira ocorrência de `Editar` ou `Edit` em qualquer janela Chrome (`:520-524`) | **Inválido como clique.** Pode ser botão disponível, título ou outro Chrome; não representa os dois `Editar` do fluxo. |
| `download_ui` | Palavra `Download` presente (`:526-530`) | **Inválido como início/fim.** No máximo indica disponibilidade do controle. |
| `download_completed` | Arquivo novo/modificado escolhido heurísticamente em `~/Downloads` (`:566-576`) | **Baixa confiabilidade na implementação atual.** Sem correlação com Chrome, CMS, Content ID ou extensão `.vtt`. |
| `upload_ui` | Primeira palavra `Upload` (`:532-536`) | **Inválido.** Pode ser botão inicial, título do modal, botão de confirmação ou status. |
| `play` | Primeira palavra `Play` (`:538-542`) | **Inválido.** Pode ser controle disponível, texto do player ou conteúdo de outra aba. |
| `validate_media` | Texto `Validate Media` presente (`:544-548`) | **Inválido como clique/conclusão.** Não verifica visibilidade do descendente, habilitação, transição ou resposta. |
| `approve` | Palavra `Approve` presente (`:550-554`) | **Inválido pelo mesmo motivo.** |
| `validate` | Palavra `Validate` presente (`:556-560`) | **Falso positivo determinístico:** também casa com `Validate Media`. |
| `nova_janela_chrome` | Quantidade absoluta de janelas Chrome maior que 1 (`:582-583`) | **Inválido.** Não detecta nova aba e aceita qualquer segunda janela Chrome como player. |

Não há máquina de estados, detecção de borda (“não existia” → “existe”), identidade do elemento, papel, janela/aba, URL, Content ID, estado `enabled`, nem correlação temporal. Se vários rótulos já estiverem na tela, serão marcados na primeira varredura após `begin()`.

Os seletores já existentes em `vtt_auto_editor.py` mostram que o CMS usa nomes mais específicos, por exemplo `DOWNLOAD SUBTITLE` (`vtt_auto_editor.py:2148`) e `UPLOAD SUBTITLE` (`vtt_auto_editor.py:2210`). Mesmo substituir as regex por nomes exatos continuaria detectando presença, não acionamento ou conclusão.

---

## 4. Confiabilidade da detecção de download

A troca de um arquivo `.crdownload` por um nome final é um sinal externo razoável de que o Chrome finalizou a gravação, mas **não é suficiente sem atribuição e sem confirmação de estabilidade**.

### Problemas concretos atuais

1. `find_completed_download()` recebe `time.time() - 1` a cada varredura (`benchmark_cms.py:566-569`), e não o horário real de início. Se a varredura UIA demorar mais de um segundo, um download novo pode ser perdido para sempre.
2. O snapshot-base nunca é atualizado (`:566-568`). Arquivo preexistente alterado continua candidato; saves posteriores do Subtitle Edit podem parecer downloads.
3. Arquivos preexistentes alterados não passam por qualquer filtro temporal (`:288-290`).
4. Qualquer aplicativo pode criar/modificar qualquer tipo de arquivo em `~/Downloads` e vencer a ordenação por `mtime`.
5. Não há filtro por `.vtt`, nome esperado, URL, MIME type, Content ID ou PID.
6. O perfil pode estar configurado para outra pasta de downloads.
7. Não há evento de início, portanto não existe duração real do download.
8. O `stat()` usado durante a ordenação (`:295-298`) pode falhar se o arquivo desaparecer no intervalo.
9. A ausência de `.crdownload` não comprova, sozinha, que o arquivo já está disponível para abertura exclusiva ou que passou por toda verificação de segurança.

### Solução recomendada

Usar `chrome.downloads.onCreated` para obter `downloadId`, URL/referrer, nome, início e estado; correlacionar o evento com o clique exato no botão do CMS e com a aba de origem; e usar `chrome.downloads.onChanged` até `state=complete` ou `interrupted`. A documentação do Chrome define que, no estado completo, o temporário foi renomeado para o destino.

Depois, um watcher nativo (`ReadDirectoryChangesW`, normalmente via `watchdog`) confirma:

- caminho final esperado;
- tamanho estável;
- arquivo abrível;
- hash opcional;
- janela temporal e Content ID correlatos.

O evento do navegador deve ser a fonte semântica; o filesystem é a confirmação física.

---

## 5. Detecção da nova guia/janela do player

`Desktop(...).windows()` retorna janelas top-level; uma aba nova dentro da mesma janela não aumenta `len(windows)`. A lógica atual não detecta abas. Além disso, `len(windows) > 1` não compara com um baseline e inclui Chrome de qualquer perfil/processo. `PLAYER_PATTERNS` (`benchmark_cms.py:115-119`) nunca é usado.

### Solução confiável

Na extensão:

1. registrar o clique confiável em `Play` e a seleção do player;
2. escutar `chrome.webNavigation.onCreatedNavigationTarget`, que informa a aba de origem e a nova aba/janela de destino;
3. correlacionar `sourceTabId`, `targetTabId`, URL, `windowId`, `openerTabId` e intervalo temporal;
4. acompanhar `tabs.onUpdated`/`webNavigation.onCommitted`/`onCompleted`;
5. no domínio do player, emitir eventos separados para `player_dom_ready`, `loadedmetadata`, primeiro `play` e erro;
6. tratar também player em mesma aba, popup bloqueado, iframe e SPA sem navegação completa.

“Destino criado”, “página carregada”, “player pronto” e “QC iniciado” devem ser quatro timestamps distintos. A criação da guia não prova que o vídeo está reproduzível.

Sem extensão, UIA pode comparar os `RuntimeId`/nomes de controles `TabItem` e um `SetWinEventHook` pode detectar novas janelas, mas essa opção continua heurística e deve ser validada contra gravação.

---

## 6. Separação entre aparecimento, clique e término

O coletor deve usar um esquema de evento append-only, por exemplo:

```json
{
  "trial_id": "uuid",
  "content_id": "...",
  "stage": "upload",
  "phase": "intent|accepted|completed|failed",
  "source": "dom|downloads_api|web_request|cms_audit|filesystem|win_event",
  "source_timestamp": "...",
  "collector_qpc_ns": 0,
  "tab_id": 0,
  "correlation_id": "...",
  "evidence": {},
  "confidence": "primary|corroborating|heuristic"
}
```

Exemplo para upload:

- `upload.available`: botão exato visível e habilitado;
- `upload.open.intent`: click confiável no botão;
- `upload.dialog.completed`: modal correto aberto;
- `upload.file_selected`: `change` no `input[type=file]`, com nome/tamanho, sem conteúdo;
- `upload.language_selected`: valor/estado selecionado mudou para o idioma esperado;
- `upload.submit.intent`: click confiável no botão de confirmação do modal;
- `upload.request.accepted`: requisição de upload iniciada;
- `upload.completed`: resposta de aplicação bem-sucedida e/ou estado de sucesso confirmado pelo CMS;
- `upload.failed`: status de erro, timeout ou toast de falha.

Uma máquina de estados por `trial_id + content_id` rejeita eventos fora de ordem, duplicados e de outra aba. O CSV de métricas é derivado depois; o log bruto nunca é sobrescrito, permitindo corrigir detectores sem refazer a coleta.

---

## 7. Arquitetura recomendada

```text
┌──────────────────────────── Chrome normal ────────────────────────────┐
│ CMS/player + extensão MV3 passiva                                    │
│ DOM events | tabs/navigation | downloads | webRequest observacional  │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ Native Messaging (JSON + sequência/ACK)
                                ▼
┌──────────────────────── coletor Windows ──────────────────────────────┐
│ relógio QPC | hotkey global | foreground/window events               │
│ watcher Downloads/VTT | processo/janela Subtitle Edit | healthcheck  │
└───────────────┬───────────────────────────────┬───────────────────────┘
                │                               │
                │ opcional                      │ append-only
                ▼                               ▼
        CMS audit/backend logs             JSONL/SQLite bruto
                                                │
                                                ▼
                                  correlator/máquina de estados
                                                │
                                                ▼
                                  CSV de métricas + relatório QA
```

### Por que é melhor que Playwright

A extensão não cria um contexto automatizado, não intercepta downloads para salvá-los em diretório temporário, não fecha/assume popups, não injeta flags de automação e não precisa de CDP. Ela usa o Chrome real e o perfil normal, apenas assinando eventos.

### Por que é melhor que o polling UIA

- observa o elemento/aba/requisição exatos, não uma palavra concatenada;
- recebe eventos, em vez de varrer toda a árvore quatro vezes por segundo;
- consegue correlacionar aba de origem, target, download ID e URL;
- separa intenção de resposta/conclusão;
- tende a ter menor efeito observador, que ainda deve ser medido em A/B.

### Se houver acesso ao CMS

Instrumentação do frontend e logs/audit trail do backend são ainda melhores para `accepted/completed`. O backend deve gerar um correlation ID para download, upload e transições Validate/Approve. A extensão ainda é útil para ação humana, conclusão física do download, abertura do player e reprodução.

---

## 8. Papel recomendado de cada tecnologia

| Tecnologia | Papel adequado | Não usar como |
|---|---|---|
| Telemetria/audit log do CMS | Fonte primária de aceitação/conclusão | Prova do clique físico ou arquivo já disponível no disco |
| Extensão Chrome passiva | Fonte primária para DOM, abas, download lifecycle, navegação e rede | Código que clica, altera DOM ou controla downloads |
| Windows UIA por eventos | Corroboração/fallback para controles acessíveis e diálogos nativos | Fonte única de conclusão do CMS |
| `SetWinEventHook`/foreground | Troca de aplicativo, criação/fechamento de janela, tempo ativo | Detecção de aba ou botão web |
| Hook de input | Timestamp de entrada e hotkey global | Identificação semântica isolada do alvo |
| Filesystem watcher | Confirmação física do download/save do VTT | Atribuição isolada ao CMS |
| OCR | Fallback para canvas/controle sem acessibilidade; auditoria | Fonte primária contínua de cliques/estado |
| CDP read-only | Plano alternativo controlado, após teste causal | Primeira opção se extensão for permitida |
| Playwright | Automação do processo SubNexus, não benchmark manual passivo | Observador do baseline manual nesta configuração |

Playwright e CDP não são sinônimos. Um cliente CDP somente-leitura conectado ao Chrome real pode ser menos intrusivo que um contexto Playwright, mas exige remote debugging, amplia a superfície de segurança e ainda precisa de teste de não interferência. Dado o histórico relatado, a extensão passiva é preferível.

---

## 9. Bugs e falhas concretas do código atual

### Críticos para validade

1. **Colisão `Validate`/`Validate Media`:** `r"\bValidate\b"` (`:111`) casa com `Validate Media` (`:105`), portanto `validate` pode ser marcado junto de `validate_media`.
2. **Presença tratada como ação:** todas as marcações de UI (`:520-560`) testam apenas texto concatenado, sem borda, clique, papel, estado ou conclusão.
3. **Duas edições colapsadas:** `mark()` aceita somente a primeira ocorrência por nome (`:449-451`), embora o fluxo tenha dois `Editar`.
4. **Todas as janelas Chrome misturadas:** o filtro usa apenas `process.name() == "chrome.exe"` (`:307-337`); o PID retornado por `open_chrome()` não é usado para escopo, nem há filtro por perfil, URL ou HWND.
5. **“Nova janela” não é nova nem aba:** condição absoluta `len(windows) > 1` (`:582-583`), sem comparação com baseline e incapaz de detectar guia nova.
6. **`PLAYER_PATTERNS` é código morto:** declarado em `:115-119`, nunca consultado.
7. **Janela móvel de um segundo no download:** passa `time.time() - 1` (`:566-569`) em vez do início da medição/download, criando misses dependentes da duração da varredura.
8. **Snapshot de downloads não evolui:** `download_before` é capturado em `begin()` (`:587`) e nunca atualizado; alterações posteriores e arquivos preexistentes podem gerar candidatos errados.
9. **Download não atribuído:** nenhum filtro por tipo, nome, Content ID, URL, perfil ou processo (`:234-300`).
10. **Primeira etapa fora do cronômetro:** Content ID é solicitado em `:698-700`; o cronômetro só começa em `:755-757`.
11. **Fim contaminado:** é necessário voltar ao CMD antes de `finish()` (`:750-766`), então o total inclui a troca de contexto e não conhece o instante do `Validate` concluído.
12. **Possibilidade de evento após o fim:** `finish()` fixa `finished_at` antes de `stop()` (`:766-767`); uma varredura já em andamento pode chamar `mark()` depois e produzir evento posterior ao tempo total.
13. **Sem máquina de estados:** rótulos de qualquer página/ordem podem preencher a linha; o primeiro falso positivo impede correção posterior por causa de `mark()`.
14. **Sem evidência de sucesso:** o CSV não possui outcome, erro do CMS, resposta HTTP, detector health ou motivo de invalidação.

### Desempenho, auditabilidade e robustez

15. A árvore é percorrida duas vezes por janela (`:357-389`) a cada ciclo, além de recriar `Desktop` e objetos `psutil`; `POLL_INTERVAL=0.25` não limita o custo da varredura.
16. Snapshots de até 3.000 caracteres são impressos e gravados a cada mudança (`:503-511`), podendo gerar I/O intenso em página dinâmica e contaminar a tarefa.
17. Exceções de UIA, filesystem e log são amplamente silenciadas (`:317-318`, `:334-335`, `:371-389`, `:141-142`), transformando falha do detector em campo vazio sem invalidar a coleta.
18. A assinatura usa somente os primeiros 10.000 caracteres (`:501`); mudanças depois desse limite não aparecem no log de descoberta.
19. Identidade e contexto são destruídos ao concatenar/deduplicar apenas texto (`:391-400`, `:498`): perde-se controle, janela, hierarquia, role, estado e bounding box.
20. `visible_only=True` filtra janelas top-level, não garante que cada descendente encontrado esteja visível ou habilitado.
21. O Chrome é considerado pronto após espera fixa de três segundos (`:727`), sem readiness ou healthcheck.
22. O processo retornado por `open_chrome()` não é monitorado nem persistido; Chrome pode delegar a abertura a outro processo.
23. Log bruto e CSV são compartilhados entre execuções sem `session_id`/`trial_id`, versão de detector, versão do Chrome/CMS, timezone com offset ou checksum.
24. Os campos CSV são offsets cumulativos desde o começo, não durações de etapa, mas os nomes não deixam isso explícito.
25. `sys` e `raw_text_dumped` não são usados; são indícios menores de implementação incompleta.
26. Dependências não são versionadas e não há preflight de Chrome/UIA/Downloads; comportamento pode variar entre estações.

`time.perf_counter()` é uma escolha correta para durações locais. Isso, porém, não corrige a semântica incorreta dos eventos nem a latência variável do detector.

---

## 10. Contrato de eventos para uma implementação robusta

| Etapa operacional | Intenção | Conclusão recomendada |
|---|---|---|
| Identificar Content ID | Hotkey global inicia a tentativa enquanto a planilha está em foreground; nenhuma digitação prévia no benchmark | Content ID observado no submit da busca/rota do CMS e reconciliado com a planilha/lista de teste |
| Pesquisar no CMS | Submit confiável no campo/formulário de pesquisa | Resultado/detalhe do mesmo Content ID carregado ou resposta de API correspondente |
| Primeiro `Editar` | Click confiável no controle exato e aba correta | View/modal de edição do mesmo conteúdo pronto |
| Download | Click confiável em `DOWNLOAD SUBTITLE` | `downloads.onCreated` → `state=complete`, seguido de confirmação do filesystem |
| Subtitle Edit | Processo/arquivo aberto e aplicativo em foreground | Save/rename do VTT correlato e saída do foreground; guardar múltiplos saves, não apenas o primeiro |
| Segundo `Editar` | Novo evento, com ordinal `2` | Modal/view de upload pronto |
| Selecionar arquivo | Abertura do modal/file chooser | `change` no input com nome/tamanho esperados |
| Selecionar idioma | Click/change no controle correto | Estado selecionado igual ao idioma esperado |
| Confirmar upload | Click no botão `Upload` do modal | Endpoint de upload com sucesso semântico + UI/estado confirmado |
| `Play`/selecionar player | Clicks confiáveis e distintos | Target criado e correlacionado |
| Abrir vídeo | Navegação do target | Player ready/metadata disponível, não apenas tab criada |
| QC | Primeiro `play`, eventos de pausa/seek/visibilidade e foreground | Retorno à aba CMS ou próximo `Validate Media`; registrar duração do vídeo como covariável |
| `Validate Media` | Click confiável | Resposta/estado correspondente concluído |
| `Approve` | Click confiável | Resposta/estado `approved` concluído |
| `Validate` final | Click confiável | Resposta/estado final validado; encerra automaticamente a tentativa |

### Início e fim

- **Início recomendado:** hotkey global registrada pelo coletor, sem trocar de janela, imediatamente antes de o analista começar a identificar o ID na planilha. Alternativa ainda melhor: ferramenta de amostragem revela a linha/ID e inicia o relógio no mesmo evento, desde que isso represente o processo que se quer medir.
- **Fim recomendado:** transição final confirmada pelo CMS. Uma hotkey global de contingência pode marcar `manual_end`, mas a tentativa deve ser rotulada como tal.

---

## Requisitos de validade antes de publicar resultados

1. **Ground truth:** executar pilotos com gravação de tela sincronizada e codificação humana independente das etapas. Obter precisão/recall e erro temporal por detector.
2. **Teste de efeito observador:** comparar Chrome sem observador, com extensão e com UIA em tarefas repetíveis; medir CPU, memória, download, hash do arquivo, abertura/reprodução do player e tempo de página.
3. **Critérios de aceitação prévios:** definir limites de eventos faltantes, duplicados, fora de ordem e erro temporal. Tentativas que não atendam ao contrato devem ser inválidas, não preenchidas silenciosamente.
4. **Rastreabilidade:** guardar eventos brutos append-only, versão da extensão/coletor/mapa de detectores, Chrome, CMS, SO, resolução/DPI, timezone e identificador pseudonimizado do operador.
5. **Privacidade:** não registrar cookies, headers de autenticação, conteúdo da legenda, áudio/vídeo ou query strings sensíveis. Gravações de piloto exigem aprovação e retenção definida.
6. **Protocolo experimental:** warm-up separado; condições de cache/login/rede documentadas; conteúdos pareados ou estratificados por duração do vídeo, tamanho da legenda e complexidade; registrar interrupções e retries.
7. **Métricas separadas:** tempo total de ciclo, tempo ativo do operador e espera de sistema. Para comparação, reportar distribuição/mediana e intervalo de confiança, não apenas média.

---

## Plano de implementação sugerido

### Fase 0 — especificação e levantamento

- Inspecionar manualmente DOM, árvore acessível e Network do CMS fora das coletas.
- Identificar seletores estáveis, rotas, endpoints, estados de sucesso/erro e domínios do player.
- Formalizar o contrato acima com os responsáveis pela operação.

### Fase 1 — coletor mínimo

- Serviço/CLI Windows com QPC, `trial_id`, hotkey global e JSONL/SQLite.
- Extensão MV3 limitada aos hosts CMS/player, com listeners passivos.
- `nativeMessaging` com número de sequência, ACK, buffer local e heartbeat.
- Eventos de click/change, tabs/navigation e downloads.

### Fase 2 — conclusão semântica

- Correlacionar endpoints via `webRequest` e, se possível, audit logs do CMS.
- Adicionar watcher de VTT, foreground/processo do Subtitle Edit e eventos de mídia.
- Implementar máquina de estados e regras explícitas de invalidação.

### Fase 3 — validação

- Ground truth por vídeo em amostra piloto.
- A/B de não interferência.
- Congelar versões e mapa de detectores antes da coleta oficial.

### Fase 4 — coleta e análise

- Gerar CSV somente a partir do log bruto validado.
- Produzir relatório de cobertura, tentativas excluídas e incerteza junto com os tempos.

---

## Decisão recomendada

- **Não corrigir incrementalmente as regex e continuar coletando.** Isso melhoraria aparência, não validade.
- **Não usar `logs/benchmark_automatico.csv` atual em documentação corporativa.**
- Preservar o script apenas como ferramenta experimental de inspeção UIA ou substituí-lo pela arquitetura de extensão/coletor após o levantamento do CMS.
- Se for necessário iniciar coleta imediatamente sem extensão, limitar o escopo ao tempo total via hotkey global + auditoria humana, deixando explícito que as etapas intermediárias são anotadas, não detectadas automaticamente.

---

## Referências técnicas

1. [Chromium — Accessibility Overview](https://chromium.googlesource.com/chromium/src/+/main/docs/accessibility/overview.md)
2. [pywinauto — Getting Started / backends e observação sobre Chrome](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
3. [Microsoft — UI Automation Events Overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-eventsoverview)
4. [Chrome Extensions — `chrome.downloads`](https://developer.chrome.com/docs/extensions/reference/api/downloads)
5. [Chrome Extensions — `chrome.webNavigation`](https://developer.chrome.com/docs/extensions/reference/api/webNavigation)
6. [Chrome Extensions — Content scripts e isolated worlds](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)
7. [Chrome Extensions — `chrome.webRequest`](https://developer.chrome.com/docs/extensions/reference/api/webRequest)
8. [Chrome Extensions — Native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
