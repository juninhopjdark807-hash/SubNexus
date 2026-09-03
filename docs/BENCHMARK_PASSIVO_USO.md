# Benchmark passivo do CMS — instalação e uso

## O que foi implementado

Esta alternativa mantém o **Google Chrome real** e o perfil `perfil_navegador_cms`, mas substitui Playwright/CDP e o polling integral por duas partes:

1. uma extensão Manifest V3 estritamente observadora;
2. o coletor `benchmark_cms_passivo.py`, executado localmente no Windows.

A extensão não clica, não navega, não fecha abas, não altera o DOM, não define pasta de download e não assume controle do navegador. Ela assina eventos normais do Chrome e envia metadados ao coletor em `127.0.0.1:8765`.

## Arquivos

```text
benchmark_cms_passivo.py                entrada principal
benchmark_passivo/                      coletor, servidor e observadores Windows
benchmark_extension/                    extensão Chrome Manifest V3
benchmark_passivo_config.json           configuração de endpoints e privacidade
Instalar_Benchmark_Passivo.bat          instalação única da extensão
Iniciar_Benchmark_Passivo.bat           execução normal
logs/benchmark_passivo/                 eventos brutos e CSV derivados
tests/test_benchmark_passivo.py         testes da correlação/máquina de estados
```

## 1. Instalação única

Feche todas as janelas que usam `perfil_navegador_cms` e execute:

```text
Instalar_Benchmark_Passivo.bat
```

O script abrirá:

- o Chrome desse perfil em `chrome://extensions`;
- a pasta `benchmark_extension` no Explorer.

No Chrome:

1. ative **Modo do desenvolvedor**;
2. clique em **Carregar sem compactação**;
3. selecione a pasta `benchmark_extension`;
4. confirme que **SubNexus — Observador Passivo do Benchmark** está ativa;
5. feche completamente o Chrome.

A instalação manual é intencional. Desde o Chrome 137, builds oficiais do Google Chrome não aceitam mais `--load-extension`; usar essa flag faria o launcher parecer funcionar sem carregar o observador. Em distribuição corporativa, a extensão deve ser empacotada/assinada e instalada pela política oficial da organização.

## 2. Executar uma tentativa

Execute:

```text
Iniciar_Benchmark_Passivo.bat
```

O coletor:

1. abre o listener apenas em `127.0.0.1`;
2. registra as hotkeys globais;
3. abre o `chrome.exe` real com `perfil_navegador_cms`;
4. espera o handshake da extensão;
5. mostra `BENCHMARK PASSIVO PRONTO`.

Depois:

1. vá para a planilha;
2. pressione **Ctrl+Alt+F8** para iniciar sem trocar de janela;
3. execute o fluxo manual completo normalmente;
4. após o `Validate` final, o coletor encerra quando observar a resposta correlacionada ou uma confirmação de sucesso do CMS;
5. se a confirmação automática não ocorrer, pressione **Ctrl+Alt+F9**. Essa tentativa será identificada como encerramento manual.

Não há ENTER entre etapas e não é necessário voltar ao terminal.

## 3. Eventos observados

### CMS

- pesquisa/submit do Content ID;
- primeiro e segundo `Editar` como eventos distintos;
- `Download`;
- abertura do upload;
- arquivo selecionado;
- idioma selecionado;
- confirmação do upload;
- `Play`;
- opção de player;
- `Validate Media`;
- `Approve`;
- `Validate` final;
- notificações de sucesso/falha.

Os cliques são capturados no DOM em fase de captura. O listener não chama `preventDefault`, `stopPropagation` nem altera elementos.

### Chrome

- criação e conclusão/interrupção do download por `chrome.downloads`;
- nova aba/janela do player com aba de origem por `webNavigation.onCreatedNavigationTarget`;
- commit/conclusão da navegação do target;
- requisições mutáveis (`POST`, `PUT`, `PATCH`, `DELETE`) iniciadas pela aba do CMS, inclusive quando a API usa outro host;
- status HTTP das respostas.

### Player

Nas abas identificadas como targets do CMS:

- metadata/canplay (`player.ready`);
- play;
- pause;
- seeking/seeked;
- ended;
- erro de mídia.

O script de mídia é carregado em páginas HTTPS porque o domínio do player ainda não foi informado. O service worker descarta eventos de abas que não tenham sido abertas pelo CMS. Depois do piloto, os `matches` e `host_permissions` devem ser restringidos aos domínios reais do player.

### Windows/filesystem

- mudança de aplicativo em foreground, sem varrer a árvore UIA;
- entrada/saída do Subtitle Edit;
- confirmação de que o arquivo baixado existe, está estável e é legível;
- modificações posteriores no VTT baixado.

## 4. Término automático e nível de confiança

O `benchmark_passivo_config.json` contém padrões de URL para upload e validações.

O CSV registra `end_confidence`:

| Valor | Significado |
|---|---|
| `endpoint_pattern` | A URL da requisição corresponde a um padrão explícito da ação. É o modo preferido. |
| `ui_success` | O CMS publicou uma notificação/estado acessível de sucesso após a ação. |
| `correlated_mutating_request` | Primeira requisição mutável, mesma aba e janela temporal da ação. Funciona como descoberta, mas precisa ser substituída por endpoint explícito antes da coleta oficial. |
| `manual_boundary` | Encerramento por Ctrl+Alt+F9. |
| `intent_only` | Encerramento no clique, disponível apenas se ativado deliberadamente na configuração. |

A opção padrão:

```json
"allow_generic_mutating_request": true
```

permite que a primeira execução funcione mesmo antes do mapeamento dos endpoints, mas adiciona uma `quality_flag`. Após o piloto, abra o JSONL, encontre as rotas corretas e ajuste `network_action_patterns`. Para a coleta corporativa, recomenda-se então usar:

```json
"allow_generic_mutating_request": false
```

Assim nenhuma requisição genérica poderá ser apresentada como conclusão da validação.

## 5. Saídas

### Eventos brutos

```text
logs/benchmark_passivo/session_<data>_<id>.jsonl
```

Cada linha contém:

- nome e fonte do evento;
- timestamp do navegador;
- timestamp de recebimento do coletor;
- estimativa no relógio monotônico;
- aba, janela e frame;
- `trial_id`;
- evidência sanitizada.

O log é append-only e permite recalcular métricas depois de refinar os detectores.

### Resumo

```text
logs/benchmark_passivo/benchmark_passivo.csv
```

As colunas terminadas em `_at_s` são offsets desde Ctrl+Alt+F8. As colunas terminadas em `_seconds` são durações derivadas somente quando os dois limites necessários foram confirmados. Também são registrados:

- total da tentativa;
- identificação até o submit da pesquisa;
- transferência do download;
- ciclo de edição manual;
- preenchimento e processamento do upload;
- abertura do player e QC;
- processamento de Validate Media, Approve e Validate;
- tempo de foreground do Subtitle Edit;
- motivo/confiança do fim;
- `quality_valid=yes/no` e flags explícitas para eventos faltantes, ordem, perda ou correlação heurística;
- Content ID detectado;
- identificadores de sessão/tentativa.

## 6. Privacidade

Por padrão:

- query strings e fragments são removidos das URLs;
- caminhos completos são substituídos por nome do arquivo e hash curto do caminho;
- títulos de janela não são salvos;
- headers, cookies, authorization e corpos de requisição não são coletados;
- conteúdo da legenda e conteúdo audiovisual não são coletados.

As permissões da extensão são amplas apenas para encontrar o domínio ainda desconhecido do player. Use um perfil dedicado e restrinja os hosts depois do piloto.

## 7. Configuração importante

Arquivo:

```text
benchmark_passivo_config.json
```

### Não encerrar com requisição genérica

Para a coleta oficial:

```json
{
  "trial": {
    "allow_generic_mutating_request": false
  }
}
```

### Identificar o operador sem armazenar nome pessoal

Use um código pseudonimizado aprovado para o estudo:

```text
py benchmark_cms_passivo.py --operator-id OP07
```

Também é possível definir `SUBNEXUS_OPERATOR_ID=OP07` antes de executar o `.bat`.

### Manter o coletor para várias tentativas

```text
py benchmark_cms_passivo.py --keep-running --operator-id OP07
```

Use Ctrl+Alt+F8 para iniciar a próxima tentativa e Ctrl+C no terminal somente depois de terminar a sessão de coleta.

### Iniciar apenas o coletor

```text
py benchmark_cms_passivo.py --no-launch
```

Útil quando o Chrome do perfil já foi aberto deliberadamente.

## 8. Solução de problemas

### `EXTENSÃO NÃO DETECTADA`

- confirme que ela foi carregada no perfil `perfil_navegador_cms`, não no perfil pessoal;
- confirme que está habilitada em `chrome://extensions`;
- feche totalmente o Chrome depois da instalação;
- confirme que a porta 8765 não está ocupada;
- clique em **Erros** no cartão da extensão e consulte o service worker.

### Download não aparece

- confira se o clique foi realmente em `Download`/`DOWNLOAD SUBTITLE`;
- veja no JSONL se existe `cms.download.intent`;
- confira se `browser.download.created` apareceu;
- downloads que não passam por `chrome.downloads` exigirão um detector específico, identificado no piloto.

### Nova aba aparece, mas `player.ready` não

- `browser.player_target.created` confirma a abertura;
- alguns players usam canvas, iframe sem permissão ou componente que não expõe `HTMLMediaElement`;
- adicione o domínio real do iframe/player ao manifesto e recarregue a extensão;
- nunca use somente `player.ready` para descartar uma tentativa sem consultar o target criado.

### Validate final não encerra

Pressione Ctrl+Alt+F9. Depois procure no JSONL:

```text
cms.validate.intent
browser.request.started
browser.request.completed
cms.notification.success
```

Use a URL sanitizada da requisição correta para ajustar `network_action_patterns`.

## 9. Validação antes do benchmark oficial

A implementação remove os falsos positivos determinísticos do script UIA e separa intenção de conclusão, mas os seletores e endpoints reais ainda precisam de validação no CMS autenticado.

Antes de publicar dados:

1. execute algumas tentativas piloto;
2. confronte JSONL/CSV com gravação de tela ou observação humana;
3. refine os endpoints;
4. desative correlação genérica;
5. valide download, player e Subtitle Edit em todas as estações;
6. congele a versão da extensão, configuração e Chrome para a amostra oficial.
