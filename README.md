# SubNexus — Benchmark Manual do CMS

Ferramentas para medir o processo manual de tratamento de legendas no CMS antes da comparação com a automação do SubNexus.

O fluxo medido é:

```text
Identificar Content ID → pesquisar no CMS → Editar → Download → Subtitle Edit
→ voltar ao CMS → Editar → selecionar arquivo/idioma → Upload
→ Play → selecionar player → QC → Validate Media → Approve → Validate
```

## Implementação recomendada

O benchmark operacional usa:

- Google Chrome real com o perfil `perfil_navegador_cms`;
- extensão Manifest V3 estritamente passiva;
- coletor Python local em `127.0.0.1`;
- API de downloads e navegação do Chrome;
- respostas de rede correlacionadas às ações;
- eventos de foreground do Windows;
- confirmação física e monitoramento do arquivo VTT;
- log bruto append-only e CSV derivado.

Ele **não usa Playwright, Selenium, CDP, OCR ou polling da árvore UI Automation** e não sintetiza cliques, altera o DOM, controla abas ou muda o destino dos downloads.

## Instalação única

No Windows, execute:

```text
Instalar_Benchmark_Passivo.bat
```

Na página `chrome://extensions`:

1. ative **Modo do desenvolvedor**;
2. clique em **Carregar sem compactação**;
3. selecione a pasta `benchmark_extension`;
4. confirme que a extensão do benchmark está ativa;
5. feche completamente o Chrome.

## Executar uma medição

Execute:

```text
Iniciar_Benchmark_Passivo.bat
```

Quando aparecer `BENCHMARK PASSIVO PRONTO`:

1. vá para a planilha;
2. pressione **Ctrl+Alt+F8** para iniciar sem mudar de janela;
3. realize o processo normalmente;
4. aguarde o encerramento automático após o `Validate` final;
5. use **Ctrl+Alt+F9** apenas como contingência.

Para identificar o operador com código pseudonimizado:

```bash
py benchmark_cms_passivo.py --operator-id OP07
```

Para várias tentativas na mesma sessão:

```bash
py benchmark_cms_passivo.py --keep-running --operator-id OP07
```

## Resultados

Os artefatos operacionais são gravados em:

```text
logs/benchmark_passivo/session_<id>.jsonl
logs/benchmark_passivo/benchmark_passivo.csv
```

O JSONL contém os eventos brutos e evidências sanitizadas. O CSV contém:

- tempo total;
- offsets de cada evento;
- durações derivadas das etapas;
- tempo ativo no Subtitle Edit;
- razão e confiança do encerramento;
- `quality_valid=yes/no`;
- flags para eventos ausentes, fora de ordem, perdidos ou correlacionados heuristicamente.

Para a coleta corporativa, refine os endpoints no piloto e configure:

```json
{
  "trial": {
    "allow_generic_mutating_request": false
  }
}
```

## Estrutura

```text
benchmark_cms_passivo.py                launcher do coletor
benchmark_passivo/                      servidor, correlação e observação Windows
benchmark_extension/                    extensão passiva do Chrome
benchmark_passivo_config.json           configuração operacional
Instalar_Benchmark_Passivo.bat          instalação única
Iniciar_Benchmark_Passivo.bat           execução normal
tests/test_benchmark_passivo.py         testes automatizados
docs/BENCHMARK_PASSIVO_USO.md           manual detalhado
docs/ANALISE_BENCHMARK_CMS.md           análise crítica da arquitetura anterior
benchmark_cms.py                         protótipo legado baseado em UI Automation
```

`benchmark_cms.py` foi mantido apenas como referência histórica/diagnóstica. Seus eventos heurísticos não devem ser usados em documentação corporativa.

## Testes

```bash
python -m unittest discover -s tests -v
```

Também é possível validar a sintaxe da extensão com Node.js:

```bash
node --check benchmark_extension/service_worker.js
node --check benchmark_extension/cms_observer.js
node --check benchmark_extension/media_observer.js
```

## Documentação

Consulte primeiro:

- `docs/BENCHMARK_PASSIVO_USO.md` — instalação, operação e troubleshooting;
- `docs/ANALISE_BENCHMARK_CMS.md` — limitações da implementação UIA anterior e justificativa arquitetural.
