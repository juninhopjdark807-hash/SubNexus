# SubNexus — Documentação de Uso

## 1. Visão geral

O **SubNexus** é uma interface operacional para automação de legendas do CMS. O fluxo principal é:

```text
Download da legenda → Edição técnica → Validação → Upload opcional
```

O sistema foi criado para organizar Content IDs em fila, acompanhar progresso de processamento e reduzir tarefas manuais repetitivas no tratamento de legendas `.vtt`.

A interface é um aplicativo de desktop em **Python puro (Tkinter — biblioteca padrão, zero dependências)**: o arquivo `interface_local.py`.
O processamento principal é feito pelo script:

```text
vtt_auto_editor.py
```

---

## 2. Estrutura principal do sistema

A pasta do sistema deve conter, no mínimo:

```text
interface_local.py          → interface de desktop (Tkinter)
vtt_auto_editor.py
Iniciar_SubNexus.bat
```

Pastas usadas pelo sistema:

```text
entrada/       → arquivos originais baixados/localizados
saida/         → arquivos editados/finais
relatorios/    → relatórios JSON/TXT
logs/          → logs e status da execução
Revisados/     → arquivos movidos após revisão, quando aplicável
```

Arquivos de controle:

```text
content_ids_interface.txt      → lista temporária de Content IDs enviados ao script
logs/cms_fluxo_status.csv      → status lido pela interface
logs/fila_interface.json       → fila salva da interface
logs/interface_execucao.log    → log de execução chamado pela interface
logs/processo_atual.pid        → ID do processo atual
```

---

## 3. Como iniciar

A forma recomendada é usar um `.bat`.

Exemplo:

```bat
@echo off
title SubNexus
cd /d "%~dp0"
py interface_local.py
pause
```

Esse método é preferível nesta fase porque facilita correções e evita recompilar `.exe` a cada ajuste.

---

## 4. Tela principal

A interface possui:

- faixa superior com a identidade **SubNexus / Accenture Business**;
- cabeçalho com o nome funcional: **Automação de Legendas CMS**;
- área para adicionar Content IDs;
- painel de progresso geral;
- botões de fila;
- modo de execução;
- lista/fila de conteúdos.

---

## 5. Adicionar Content IDs

No campo **Códigos de conteúdo**, cole um ou mais IDs, um por linha:

```text
6a28ba9c76958a0008032dbb
6a28bfd57cd22e0008a284e9
6a28c4ecfbccff00084be250
```

Também é possível colar IDs separados por vírgula ou ponto e vírgula. A interface identifica os conteúdos e evita duplicados.

Depois clique em:

```text
Adicionar à fila
```

---

## 6. Modos de execução

### 6.1 Apenas gerar arquivos

Use quando quiser gerar a legenda editada sem fazer upload automático.

O sistema:

1. processa o Content ID;
2. baixa/localiza a legenda;
3. edita o `.vtt`;
4. valida a estrutura;
5. salva o arquivo final em `saida/`;
6. não envia ao CMS.

### 6.2 Gerar e enviar ao CMS

Use quando quiser executar o fluxo completo.

O sistema:

1. processa o Content ID;
2. baixa/localiza a legenda;
3. edita o `.vtt`;
4. valida a estrutura;
5. salva o arquivo final;
6. envia a legenda editada ao CMS.

---

## 7. Processar a fila

Cada conteúdo na fila possui botões próprios:

```text
Processar
Remover
```

Também existem botões gerais:

```text
Processar fila inteira
Remover concluídos
```

### Recomendações

- Use **Processar** para testar item por item.
- Use **Processar fila inteira** quando o fluxo já estiver validado.
- Use **Remover concluídos** para limpar a fila depois do processamento.

---

## 8. Status e progresso

A interface acompanha o andamento pelo arquivo:

```text
logs/cms_fluxo_status.csv
```

Estados principais:

| Status | Significado |
|---|---|
| Pendente | Aguardando processamento |
| Baixando | Legenda sendo baixada/localizada |
| Editando | Arquivo sendo processado |
| Validando | Estrutura VTT sendo verificada |
| Arquivo gerado | Arquivo final salvo em `saida/` |
| Enviado | Legenda enviada ao CMS |
| Erro | Falha no fluxo |

Progresso aproximado:

| Progresso | Etapa |
|---:|---|
| 0% | Aguardando |
| 30% | Download/localização |
| 55% | Edição |
| 70% | Validação |
| 100% | Finalizado ou erro registrado |

---

## 9. Saídas geradas

Arquivos finais:

```text
saida/
```

Relatórios:

```text
relatorios/
```

Logs:

```text
logs/
```

Os relatórios podem indicar:

- quantidade de alterações;
- quantidade de cues divididos;
- linhas acima do limite;
- blocos acima do limite;
- tags restantes;
- sobreposições;
- caracteres suspeitos;
- status final.

---

## 10. Regras técnicas do editor de legenda

O script `vtt_auto_editor.py` aplica uma edição mecânica e controlada em arquivos `.vtt`.

Regras principais:

- não usa IA;
- não usa API externa para reescrita;
- não substitui palavras automaticamente;
- remove `<i>` e `</i>`;
- converte `<br>`, `<br/>` e `<br />` em quebra interna;
- não trata `</br>` como erro;
- preserva reticências `...`;
- limita cada linha a **33 caracteres**;
- limita cada cue a **2 linhas**;
- divide cues com mais de **66 caracteres**, quando necessário;
- não separa palavras;
- evita quebra antes de vírgula, ponto ou pontuação;
- permite quebra em **“ e ”** apenas quando o “e” é conjunção isolada;
- preserva falas de diálogo marcadas com `-`;
- distribui internamente o tempo quando divide um cue;
- evita sobreposição entre novos cues;
- gera relatório JSON e TXT;
- detecta caracteres suspeitos sem alterar automaticamente.

---

## 11. Parâmetros principais do `vtt_auto_editor.py`

### Fluxo CMS

```bash
py vtt_auto_editor.py --cms-flow --content-file content_ids_interface.txt
```

Executa o fluxo CMS usando os Content IDs informados no arquivo.

### Arquivo de Content IDs

```bash
--content-file content_ids_interface.txt
```

Define o arquivo com os IDs que serão processados.

Formato:

```text
content_id_1
content_id_2
content_id_3
```

### Sem upload automático

```bash
--no-upload
```

Processa e gera os arquivos, mas não envia ao CMS.

Exemplo:

```bash
py vtt_auto_editor.py --cms-flow --content-file content_ids_interface.txt --no-upload
```

Esse é o modo usado pela interface quando está selecionado:

```text
Apenas gerar arquivos
```

### Modo de monitoramento

```bash
--watch
```

Monitora a pasta de entrada e processa novos arquivos automaticamente.

Para o SubNexus atual, a recomendação é usar a **fila manual da interface**, não o monitoramento automático.

---

## 12. Configuração via `config.json`

O script pode ler configurações pelo arquivo:

```text
config.json
```

Campos principais:

| Campo | Função | Padrão |
|---|---|---|
| `fps` | FPS usado no cálculo de timecode | `30` |
| `max_chars_per_line` | Máximo de caracteres por linha | `33` |
| `max_lines_per_cue` | Máximo de linhas por cue | `2` |
| `max_chars_per_cue` | Máximo de caracteres por cue | `66` |
| `input_folder` | Pasta de entrada | `entrada` |
| `output_folder` | Pasta de saída | `saida` |
| `reports_folder` | Pasta de relatórios | `relatorios` |
| `reviewed_folder` | Pasta de revisados | `Revisados` |
| `show_popup` | Exibe pop-up ao finalizar | `true` |
| `open_after_process` | Abre o arquivo após processar | `true` |
| `move_to_reviewed_after_confirmation` | Move para Revisados após confirmação | `true` |
| `watch_interval_seconds` | Intervalo do modo watch | `3` |
| `state_file` | Arquivo de controle | `.vtt_processados.json` |
| `subtitle_edit_path` | Caminho opcional do Subtitle Edit | vazio |

Exemplo:

```json
{
  "fps": 30,
  "max_chars_per_line": 33,
  "max_lines_per_cue": 2,
  "max_chars_per_cue": 66,
  "input_folder": "entrada",
  "output_folder": "saida",
  "reports_folder": "relatorios",
  "reviewed_folder": "Revisados",
  "show_popup": true,
  "open_after_process": true,
  "move_to_reviewed_after_confirmation": true,
  "watch_interval_seconds": 3,
  "process_existing_on_start": false,
  "state_file": ".vtt_processados.json",
  "subtitle_edit_path": ""
}
```

---

## 13. Problemas comuns

### O app abre em modo demonstração

Causa provável:

```text
vtt_auto_editor.py
```

não está na mesma pasta da interface.

### O status não atualiza

Verificar se o arquivo abaixo está sendo criado/atualizado:

```text
logs/cms_fluxo_status.csv
```

### O upload não acontece

Verificar:

- se o modo está em **Gerar e enviar ao CMS**;
- se o script não foi chamado com `--no-upload`;
- se o CMS está acessível;
- se o login está válido;
- se o botão de upload foi encontrado;
- se há erro em `logs/interface_execucao.log`.

### O arquivo final não aparece

Verificar:

```text
saida/
relatorios/
logs/interface_execucao.log
```

---

## 14. Boas práticas

- Não abrir várias instâncias ao mesmo tempo.
- Usar **Apenas gerar arquivos** quando houver dúvida.
- Processar poucos conteúdos no primeiro teste.
- Conferir relatórios quando houver erro.
- Evitar limpar logs durante uma execução.
- Manter backup da versão funcional.
- Confirmar o modo antes de clicar em **Processar fila inteira**.

---

## 15. Estrutura recomendada

```text
SubNexus/
│
├── interface_local.py
├── vtt_auto_editor.py
├── Iniciar_SubNexus.bat
├── config.json
│
├── entrada/
├── saida/
├── relatorios/
├── logs/
└── Revisados/
```

---

## 16. Resumo operacional rápido

1. Abrir `Iniciar_SubNexus.bat`.
2. Colar os Content IDs.
3. Clicar em **Adicionar à fila**.
4. Escolher:
   - **Apenas gerar arquivos**; ou
   - **Gerar e enviar ao CMS**.
5. Clicar em **Processar** ou **Processar fila inteira**.
6. Acompanhar a barra de progresso.
7. Conferir os arquivos em `saida/`.
8. Consultar relatórios em `relatorios/` quando necessário.


---

## Atualização: idioma, conteúdo sem legenda e revisão individual

### Conteúdo sem legenda

Quando o CMS não exibir o botão **DOWNLOAD SUBTITLE**, o sistema registra o item como **Sem legenda**. Esse status indica que o conteúdo provavelmente é dublado e não possui legenda disponível para edição.

### Abrir no Subtitle Edit

No modo **Apenas gerar arquivos**, o arquivo editado será aberto no Subtitle Edit somente quando o usuário clicar em **Processar** em um card individual. O processamento de **fila inteira** nunca abre os arquivos automaticamente, para evitar travamento do computador.

### Idioma da legenda

A interface possui o seletor **Idioma da legenda**:

- Português → `--language pt-br` → upload CMS em `Portuguese`
- Espanhol → `--language es` → upload CMS em `Spanish`

O idioma vale para a fila inteira. Com itens na fila, o seletor fica bloqueado.

### Novos parâmetros

```bash
--language pt-br
--language es
--open-edited-file
```

Exemplo individual sem upload e abrindo para revisão:

```bash
py vtt_auto_editor.py --cms-flow --content-file content_ids_interface.txt --language es --no-upload --open-edited-file
```
