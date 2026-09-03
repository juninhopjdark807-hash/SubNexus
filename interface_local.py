#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubNexus — Interface local (Tkinter)

Substitui a interface Streamlit: app de desktop em Python puro
(SOMENTE biblioteca padrão — zero dependências de pip).

Recursos equivalentes à interface anterior:
- Fila de Content IDs (persistida em logs/fila_interface.json, mesmo formato).
- Barra de progresso por item + progresso geral (lidos de logs/cms_fluxo_status.csv).
- Botões por item: Processar/Reprocessar, Upload (arquivo já gerado), Remover,
  abrir Relatório e abrir .vtt final.
- Ações rápidas: Change Project, confirmar instância CMS, abrir pastas,
  Parar fluxo, Limpar execução, Limpar fila.
- Auto-refresh configurável (2/3/5/10s).
- Modo demonstração quando o vtt_auto_editor.py não existe.

Uso:
    py interface_local.py
"""

from __future__ import annotations

import csv
import math
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "logs" / "interface_execucao.log"
STATUS_CSV = BASE_DIR / "logs" / "cms_fluxo_status.csv"
TIMING_CSV = BASE_DIR / "logs" / "cms_fluxo_tempos.csv"
RUN_LOG = BASE_DIR / "logs" / "interface_execucao.log"
PID_FILE = BASE_DIR / "logs" / "processo_atual.pid"
STOP_FILE = BASE_DIR / "logs" / "parar_fluxo.flag"
QUEUE_FILE = BASE_DIR / "logs" / "fila_interface.json"
CMS_PROFILE_DIR = BASE_DIR / "perfil_navegador_cms"
CMS_PROFILE_LOCK = CMS_PROFILE_DIR / "lockfile"
CMS_INSTANCE_FILE = BASE_DIR / "logs" / "cms_instance_state.json"
FAVICON_FILE = BASE_DIR / "subnexus_favicon.png"
LOGO_FILE = BASE_DIR / "subnexus_logo.png"
EDITOR_SCRIPT = BASE_DIR / "vtt_auto_editor.py"
CONTENT_FILE = BASE_DIR / "content_ids_interface.txt"

LANGUAGE_OPTIONS = {
    "Português": "pt-br",
    "Espanhol": "es",
}
CMS_INSTANCE_FOR_LANGUAGE = {
    "pt-br": "Portuguese",
    "es": "SSLA",
}

PASTAS = {
    "Originais": BASE_DIR / "entrada",
    "Finais": BASE_DIR / "saida",
    "Relatórios": BASE_DIR / "relatorios",
    "Logs": BASE_DIR / "logs",
    "Revisados": BASE_DIR / "Revisados",
}

# ============================================================
# Lógica (independe de Tkinter — testável sem display)
# ============================================================


def ensure_dirs() -> None:
    for folder in [BASE_DIR / "logs", BASE_DIR / "entrada", BASE_DIR / "saida",
                   BASE_DIR / "relatorios", BASE_DIR / "Revisados"]:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def ids_from_text(t: str) -> list:
    out = []
    for line in str(t).replace(",", "\n").replace(";", "\n").splitlines():
        x = line.strip()
        if x and x not in out:
            out.append(x)
    return out


def saved_ids() -> list:
    if not CONTENT_FILE.exists():
        return []
    return [
        x.strip()
        for x in CONTENT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if x.strip()
    ]


def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def save_queue(ids: list) -> list:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    unique = []
    for cid in ids:
        cid = str(cid).strip()
        if cid and cid not in unique:
            unique.append(cid)
    QUEUE_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    return unique


# ------------------------------------------------------------ status CSV


def read_status_csv(cache: dict | None = None) -> list:
    """
    Lê logs/cms_fluxo_status.csv (mesmo formato do editor; ; como separador).
    Retorna lista de dicts na ordem do arquivo. Cache por mtime+size.
    Sem pandas: módulo csv da biblioteca padrão.
    """
    cache = cache if cache is not None else _UI_CACHE
    if not STATUS_CSV.exists():
        return []

    try:
        stat = STATUS_CSV.stat()
        sig = (stat.st_mtime, stat.st_size)
        hit = cache.get("_status_csv")
        if hit and hit.get("sig") == sig:
            return hit.get("rows", [])
    except Exception:
        sig = None

    old_fields = [
        "datetime", "content_id", "status", "original_file", "processed_temp_file",
        "final_upload_file", "report_file", "error",
    ]
    new_fields = old_fields[:2] + ["content_title"] + old_fields[2:]

    rows: list = []
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        try:
            with STATUS_CSV.open("r", encoding=enc, newline="") as f:
                reader = csv.reader(f, delimiter=";")
                for values in reader:
                    if not values:
                        continue
                    if values[0].strip().lower() == "datetime":
                        continue
                    if len(values) >= 9:
                        fields = new_fields
                    elif len(values) == 8:
                        fields = old_fields
                    else:
                        continue
                    rows.append({
                        field: (values[i] if i < len(values) else "")
                        for i, field in enumerate(fields)
                    })
            break
        except (UnicodeDecodeError, UnicodeError):
            rows = []
            continue
        except Exception:
            rows = []
            continue

    if sig is not None:
        cache["_status_csv"] = {"sig": sig, "rows": rows}
    return rows


def progress_from_status(s: str) -> int:
    u = str(s or "").upper()
    if "SEM_LEGENDA" in u or "SEM LEGENDA" in u:
        return 100
    if "ERRO CMS" in u or "ERRO_CMS" in u:
        return 100
    if "ERRO" in u:
        return 100
    if "ENVIADO" in u or u == "OK":
        return 100
    if "ARQUIVO GERADO" in u or "EDITADO_SEM_UPLOAD" in u or "GERADO" in u:
        return 80
    if "ENVIANDO" in u:
        return 90
    if "VALID" in u:
        return 70
    if "EDIT" in u or "PROCESS" in u:
        return 55
    if "BAIX" in u or "DOWNLOAD" in u:
        return 30
    if "AGUARDANDO LOGIN" in u:
        return 10
    if "INICIANDO" in u:
        return 5
    return 0


def stage_from_status(s: str, p: int) -> str:
    u = str(s or "").upper()
    if "SEM_LEGENDA" in u or "SEM LEGENDA" in u:
        return "Sem legenda"
    if "ERRO CMS" in u or "ERRO_CMS" in u:
        return "Erro CMS"
    if "ERRO" in u:
        return "Erro"
    if "ENVIADO" in u or u == "OK":
        return "Enviado"
    if "ARQUIVO GERADO" in u or "EDITADO_SEM_UPLOAD" in u or "GERADO" in u:
        return "Arquivo gerado"
    if "ENVIANDO" in u:
        return "Enviando"
    if "VALID" in u:
        return "Validando"
    if "EDIT" in u or "PROCESS" in u:
        return "Editando"
    if "BAIX" in u or "DOWNLOAD" in u:
        return "Baixando"
    if "AGUARDANDO LOGIN" in u:
        return "Aguardando login"
    if "INICIANDO" in u:
        return "Iniciando"
    if p >= 100:
        return "Concluído"
    if p > 0:
        return "Processando"
    return "Pendente"


FINAL_SUCCESS_STATUSES = {"enviado"}
FINAL_NEUTRAL_STATUSES = {"sem legenda"}
FINAL_ERROR_STATUSES = {"erro", "erro cms"}
RUNNING_STATUSES = {
    "iniciando", "aguardando login", "aguardando cms carregar conteúdo",
    "baixando", "editando", "validando", "enviando", "processando",
}


def norm_status(value) -> str:
    return str(value or "").strip().lower()


def is_final_success_status(status) -> bool:
    return norm_status(status) in FINAL_SUCCESS_STATUSES


def is_final_neutral_status(status) -> bool:
    return norm_status(status) in FINAL_NEUTRAL_STATUSES


def is_final_error_status(status) -> bool:
    return norm_status(status) in FINAL_ERROR_STATUSES


def is_running_status(status) -> bool:
    s = norm_status(status)
    return s in RUNNING_STATUSES or ("andamento" in s)


def is_pending_status(status) -> bool:
    return norm_status(status) in {"", "pendente", "aguardando"}


def chip_class(status) -> str:
    s = norm_status(status)
    if s in FINAL_SUCCESS_STATUSES:
        return "ok"
    if s in {"arquivo gerado", "gerado"} or s in FINAL_NEUTRAL_STATUSES:
        return "wait"
    if s in FINAL_ERROR_STATUSES:
        return "err"
    if s in RUNNING_STATUSES:
        return "run"
    return "wait"


def bar_color(status) -> str:
    s = norm_status(status)
    if s in FINAL_SUCCESS_STATUSES:
        return C_GREEN
    if s in {"arquivo gerado", "gerado"} or s in FINAL_NEUTRAL_STATUSES:
        return C_YELLOW
    if s in FINAL_ERROR_STATUSES:
        return C_RED
    if s in RUNNING_STATUSES:
        return C_BLUE2
    return "#334155"


# ------------------------------------------------------------ pastas (índice cacheado)

_UI_CACHE: dict = {}


def _vtt_index(cache: dict | None = None) -> dict:
    """
    Índice nome->caminho dos .vtt por pasta (entrada/saida), cacheado por mtime.
    (Mesma otimização aplicada na interface Streamlit.)
    """
    cache = cache if cache is not None else _UI_CACHE

    def scan(key: str, dirpath: Path) -> dict:
        try:
            st_ = dirpath.stat()
            sig = (st_.st_mtime, dirpath.name)
        except Exception:
            sig = None
        cached = cache.get(f"_vtt_index_{key}")
        if cached is not None and cached.get("sig") == sig:
            return cached.get("names", {})
        names = {}
        try:
            for path in dirpath.glob("*.vtt"):
                if path.is_file():
                    names[path.name] = path
        except Exception:
            pass
        if sig is not None:
            cache[f"_vtt_index_{key}"] = {"sig": sig, "names": names}
        return names

    return {
        "entrada": scan("entrada", BASE_DIR / "entrada"),
        "saida": scan("saida", BASE_DIR / "saida"),
    }


def _match_by_cid(names: dict, cid: str):
    """Correspondência exata primeiro; fallback por substring (nomes do CMS)."""
    exact = f"{cid}.vtt"
    if exact in names:
        return names[exact]
    for name, path in names.items():
        if cid in name:
            return path
    return None


def file_status(ids, cache: dict | None = None) -> dict:
    cache = cache if cache is not None else _UI_CACHE
    idx = _vtt_index(cache)
    saida_names = idx["saida"]
    entrada_names = idx["entrada"]
    d = {}
    for cid in ids:
        cid = str(cid).strip()
        out_match = _match_by_cid(saida_names, cid)
        in_match = _match_by_cid(entrada_names, cid)
        if out_match is not None:
            status, progress, msg = "Arquivo gerado", 80, "Arquivo pronto na pasta de saida."
        elif in_match is not None:
            status, progress, msg = "Baixando", 35, "Original localizado. Aguardando arquivo final."
        else:
            status, progress, msg = "Pendente", 0, "Aguardando processamento."
        d[cid] = {
            "content_id": cid, "content_title": "",
            "status": status, "progress": progress, "message": msg,
        }
    return d


def real_items_status(ids, cache: dict, overrides: dict) -> list:
    base = file_status(ids, cache)
    last_row_dt: dict = {}

    for row in read_status_csv(cache):
        cid = str(row.get("content_id", "")).strip()
        if cid not in base:
            continue
        raw = str(row.get("status", "")).strip()
        err = str(row.get("error", "")).strip()
        title = str(row.get("content_title", "")).strip()
        if title and title.lower() != "nan":
            base[cid]["content_title"] = title
        if raw:
            p = progress_from_status(raw)
            stg = stage_from_status(raw, p)
            msg = err if err and err.lower() != "nan" else stg
            base[cid].update({"status": stg, "progress": p, "message": msg})

            rf = str(row.get("report_file", "")).strip()
            if rf and rf.lower() != "nan":
                base[cid]["report_file"] = rf

            try:
                last_row_dt[cid] = datetime.strptime(
                    str(row.get("datetime", "")).strip(), "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                pass

    for cid, override in list(overrides.items()):
        if cid not in base:
            continue
        current = base[cid]
        current_status = norm_status(current.get("status"))
        override_status = norm_status(override.get("status"))
        override_message = str(override.get("message", "")).lower()

        stale_process_exit_error = (
            override_status == "erro"
            and "processo encerrado antes de registrar status final" in override_message
            and (
                current_status in {"arquivo gerado", "gerado", "enviado"}
                or is_final_neutral_status(current_status)
                or is_final_error_status(current_status)
            )
        )
        if stale_process_exit_error:
            overrides.pop(cid, None)
            continue

        # Override obsoleto perde para o CSV quando a linha final do CSV é mais
        # recente e já tem status final (evita erro antigo mascarar sucesso novo).
        csv_dt = last_row_dt.get(cid)
        override_ts = override.get("updated_at") or 0
        if (
            csv_dt is not None
            and override_ts
            and csv_dt.timestamp() > override_ts
            and (
                is_final_success_status(current.get("status"))
                or is_final_neutral_status(current.get("status"))
                or is_final_error_status(current.get("status"))
            )
        ):
            overrides.pop(cid, None)
            continue

        current_progress = int(current.get("progress", 0) or 0)
        override_progress = int(override.get("progress", 0) or 0)
        if override_progress >= current_progress:
            current.update({
                "status": override.get("status", current.get("status")),
                "progress": override_progress,
                "message": override.get("message", current.get("message")),
            })

    return list(base.values())


def demo_items(ids, started: bool, start_ts: float) -> list:
    if not started:
        return [
            {"content_id": cid, "content_title": "", "status": "Pendente",
             "progress": 0, "message": "Aguardando processamento."}
            for cid in ids
        ]
    elapsed = int(time.time() - start_ts)
    stages = [
        (0, "Pendente", 0, "Aguardando processamento."),
        (2, "Baixando", 20, "Baixando legenda do CMS."),
        (4, "Editando", 50, "Aplicando regras técnicas."),
        (6, "Validando", 70, "Validando estrutura VTT."),
        (8, "Arquivo gerado", 80, "Arquivo pronto na pasta de saída."),
    ]
    items = []
    for i, cid in enumerate(ids):
        local_elapsed = max(0, elapsed - i * 2)
        chosen = stages[0]
        for stage in stages:
            if local_elapsed >= stage[0]:
                chosen = stage
        items.append({
            "content_id": cid, "content_title": "",
            "status": chosen[1], "progress": chosen[2], "message": chosen[3],
        })
    return items


def get_items(ids, cache: dict, overrides: dict, demo_mode: bool, demo_started: bool, demo_start_ts: float) -> list:
    if demo_mode:
        return demo_items(ids, demo_started, demo_start_ts)
    return real_items_status(ids, cache, overrides)


def summary(items) -> tuple:
    total = len(items)
    concl = sum(1 for x in items if norm_status(x.get("status")) == "enviado")
    sem_legenda = sum(1 for x in items if is_final_neutral_status(x.get("status")))
    erros = sum(1 for x in items if is_final_error_status(x.get("status")))
    gerados = sum(1 for x in items if norm_status(x.get("status")) in {"arquivo gerado", "gerado"})
    andam = sum(1 for x in items if is_running_status(x.get("status"))) + gerados
    pend = max(0, total - concl - sem_legenda - erros - andam)
    geral = int(((concl + sem_legenda + erros) / total) * 100) if total else 0
    return total, concl, andam, pend, erros, geral, sem_legenda


def sorted_queue_items(items) -> list:
    def order(item):
        status = str(item.get("status", "")).lower()
        progress = int(item.get("progress", 0) or 0)
        is_error = "erro" in status
        is_done = progress >= 100 and not is_error
        is_running = 0 < progress < 100
        if is_running:
            return 0
        if not is_done and not is_error:
            return 1
        if is_error:
            return 2
        return 3
    return sorted(items, key=order)


def processable_queue_ids(queue_ids, items) -> list:
    by_id = {str(item.get("content_id", "")).strip(): item for item in items}
    targets = []
    for cid in queue_ids:
        item = by_id.get(str(cid).strip())
        if not item:
            targets.append(cid)
            continue
        progress = int(item.get("progress", 0) or 0)
        if progress == 0 and is_pending_status(item.get("status")):
            targets.append(cid)
    return targets


def display_button_label(item, cid: str, running_ids: set) -> str:
    status = norm_status(item.get("status"))
    progress = int(item.get("progress", 0) or 0)
    if status == "enviado":
        return "Reprocessar"
    if status in {"arquivo gerado", "gerado"}:
        return "Regerar"
    if is_final_neutral_status(status) or is_final_error_status(status) or progress >= 100:
        return "Reprocessar"
    if cid in running_ids or is_running_status(status):
        return "⏳ Processando..."
    return "Processar"


# ------------------------------------------------------------ processo / fluxo


def is_pid_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        if pid <= 0:
            return False
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                timeout=5,
            )
            return str(pid) in result.stdout
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    except Exception:
        return False


def start_flow(content_ids, no_upload, language="pt-br", open_edited_file=False,
               upload_existing_file=False):
    """
    Inicia o vtt_auto_editor.py como subprocesso (mesmo contrato da Streamlit):
    grava content_ids_interface.txt, apaga flag de parada, registra PID e log.
    """
    ensure_dirs()
    content_ids = [str(x).strip() for x in content_ids if str(x).strip()]
    if not content_ids:
        return False, "Nenhum Content ID informado."

    if _cms_manual_browser_open_raw():
        return (
            False,
            "Feche a janela aberta pelo Change Project antes de processar. "
            "O Chrome mantém o perfil do CMS bloqueado enquanto está aberto.",
        )

    try:
        STOP_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    CONTENT_FILE.write_text("\n".join(content_ids), encoding="utf-8")

    cmd = [
        sys.executable or "py",
        str(EDITOR_SCRIPT),
        "--cms-flow",
        "--content-file",
        str(CONTENT_FILE),
        "--language",
        language,
    ]
    if no_upload:
        cmd.append("--no-upload")
    if open_edited_file:
        cmd.append("--open-edited-file")
    if upload_existing_file:
        cmd.append("--upload-existing-file")

    try:
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write("\n\n=== SubNexus start_flow (interface local) ===\n")
            log.write("CMD: " + " ".join(cmd) + "\n")
            process = subprocess.Popen(
                cmd, cwd=str(BASE_DIR), stdout=log, stderr=log, shell=False,
            )
        PID_FILE.write_text(str(process.pid), encoding="utf-8")
        return True, f"Processamento iniciado para {len(content_ids)} conteúdo(s)."
    except Exception as exc:
        return False, f"Falha ao iniciar processamento: {exc}"


def request_stop_flow() -> bool:
    ensure_dirs()
    try:
        STOP_FILE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        return True
    except Exception:
        return False


def open_cms_manual_session():
    ensure_dirs()
    cmd = [sys.executable or "py", str(EDITOR_SCRIPT), "--open-cms-home"]
    try:
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write("\n\n=== SubNexus open_cms_manual_session (interface local) ===\n")
            log.write("CMD: " + " ".join(cmd) + "\n")
            subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=log, stderr=log, shell=False)
        return True, "CMS aberto no navegador. Faça login/troque a instância manualmente."
    except Exception as exc:
        return False, f"Falha ao abrir o CMS: {exc}"


def clean_exec():
    """
    Renomeia arquivos de execução para *_backup_<timestamp>.
    Retorna None se houver processo ativo (bloqueio), lista de nomes movidos
    ou lista vazia se não havia nada.
    """
    if is_pid_running():
        return None
    moved = []
    for p in [STATUS_CSV, TIMING_CSV, RUN_LOG, PID_FILE, STOP_FILE, CONTENT_FILE]:
        if p.exists():
            b = p.with_name(f"{p.stem}_backup_{datetime.now():%Y%m%d_%H%M%S}{p.suffix}")
            try:
                p.rename(b)
                moved.append(b.name)
            except Exception:
                pass
    return moved


# ------------------------------------------------------------ navegador / instância CMS


def expected_cms_instance(language: str) -> str:
    return CMS_INSTANCE_FOR_LANGUAGE.get(language, "Portuguese")


def read_cms_instance_state() -> dict:
    try:
        if CMS_INSTANCE_FILE.exists():
            data = json.loads(CMS_INSTANCE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def write_cms_instance_state(instance: str, language: str) -> None:
    ensure_dirs()
    data = {
        "instance": instance,
        "language": language,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    CMS_INSTANCE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cms_manual_browser_open_raw() -> bool:
    if not CMS_PROFILE_LOCK.exists():
        return False
    try:
        import subprocess as _sp
        cmd = [
            "powershell", "-NoProfile", "-Command",
            ("Get-CimInstance Win32_Process | "
             "Where-Object { ($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') -and "
             "$_.CommandLine -like '*perfil_navegador_cms*' } | "
             "Select-Object -First 1 -ExpandProperty ProcessId"),
        ]
        result = _sp.run(cmd, capture_output=True, text=True, timeout=4, shell=False)
        if result.returncode != 0:
            running = None
        else:
            running = bool(result.stdout.strip())
        if running is not None:
            return running
    except Exception:
        running = None
    try:
        return (time.time() - CMS_PROFILE_LOCK.stat().st_mtime) < 15
    except Exception:
        return True


def open_folder(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception:
        return False


def open_path(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


# ============================================================
# GUI (Tkinter)
# ============================================================

try:
    import tkinter as tk
    from tkinter import ttk
    from tkinter import font as tkfont
    TK_AVAILABLE = True
    TK_IMPORT_ERROR = ""
except Exception as _tk_exc:  # pragma: no cover
    TK_AVAILABLE = False
    TK_IMPORT_ERROR = str(_tk_exc)

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
F_MONO = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"

# ------------------------------------------------------------ paleta
C_BG      = "#0A0E18"   # fundo da janela
C_CARD    = "#111726"   # cartões
C_CARD2   = "#171F33"   # cartões elevados / inputs / linhas da fila
C_CARD3   = "#1D2740"   # hover
C_LINE    = "#242E49"   # divisores sutis
C_TRACK   = "#202942"   # trilhas de progresso
C_TEXT    = "#EEF2FA"
C_MUTED   = "#9AA5BF"
C_FAINT   = "#5F6B87"
C_ACCENT  = "#4E7DFF"   # azul primário
C_ACCENT2 = "#6E9BFF"   # primário (hover)
C_ACCENT3 = "#3B66D9"   # primário (pressionado)
C_CYAN    = "#3ED1E4"
C_GREEN   = "#34D399"
C_YELLOW  = "#FBBF24"
C_RED     = "#F87171"
C_BLUE2   = "#5B8CFF"

# ------------------------------------------------------------ tipografia
F_BRAND   = (FONT, 22, "bold")
F_TITLE   = (FONT, 11, "bold")
F_BODY    = (FONT, 10)
F_SMALL   = (FONT, 9)
F_TINY    = (FONT, 8)
F_METRIC  = (FONT, 17, "bold")
F_SECTION = (FONT, 8, "bold")
F_MONO_ID = (F_MONO, 10, "bold")

CHIP_STYLES = {
    "ok":   ("#12291E", "#7EE2A8", C_GREEN),
    "wait": ("#2E2712", "#FDE68A", C_YELLOW),
    "err":  ("#33151B", "#FCA5A5", C_RED),
    "run":  ("#12203A", "#93C5FD", C_BLUE2),
}

# ============================================================
# Gráficos: formas arredondadas e gradientes (fotos geradas)
# ============================================================


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _blend(h1, h2, t):
    """Mistura duas cores hex; t em 0..1 (0 = h1, 1 = h2)."""
    a, b = _hex_to_rgb(h1), _hex_to_rgb(h2)
    return _rgb_to_hex((a[0] + (b[0] - a[0]) * t,
                        a[1] + (b[1] - a[1]) * t,
                        a[2] + (b[2] - a[2]) * t))


_IMG_CACHE: dict = {}


def _corner_pixels(w, h, r):
    """Pixels da borda arredondada dos 4 cantos, com cobertura anti-alias.

    Retorna lista de (x, y, coverage) apenas para pixels com coverage < 1.
    """
    key = ("corners", w, h, r)
    got = _IMG_CACHE.get(key)
    if got is not None:
        return got
    r = min(r, w // 2, h // 2)
    out = []
    for cx, cy, ox, oy in ((r - 0.5, r - 0.5, 0, 0),
                           (w - r - 0.5, r - 0.5, w - r, 0),
                           (r - 0.5, h - r - 0.5, 0, h - r),
                           (w - r - 0.5, h - r - 0.5, w - r, h - r)):
        for dx in range(r):
            for dy in range(r):
                d = ((dx - (r - 0.5)) ** 2 + (dy - (r - 0.5)) ** 2) ** 0.5
                cov = max(0.0, min(1.0, r - d + 0.5))
                if cov < 1.0:
                    out.append((ox + dx, oy + dy, cov))
    _IMG_CACHE[key] = out
    return out


def _rounded_photo(w, h, r, fill, outside):
    """Retângulo arredondado (PhotoImage) com cantos anti-aliasados.

    Os pixels fora do raio ficam transparentes e revelam a cor `outside`
    (que deve ser o fundo do canvas onde a imagem é exibida).
    """
    key = ("round", w, h, r, fill, outside)
    got = _IMG_CACHE.get(key)
    if got is not None:
        return got
    img = tk.PhotoImage(width=w, height=h)
    r = min(r, w // 2, h // 2)
    img.put(fill, to=(r, 0, w - r, h))
    img.put(fill, to=(0, r, w, h - r))
    for x, y, cov in _corner_pixels(w, h, r):
        if cov <= 0.02:
            img.put("", to=(x, y))
        else:
            img.put(_blend(outside, fill, cov), to=(x, y))
    _IMG_CACHE[key] = img
    return img


def _gradient_photo_h(w, h, r, c1, c2, outside):
    """Faixa com gradiente horizontal e cantos arredondados (PhotoImage)."""
    key = ("grad", w, h, r, c1, c2, outside)
    got = _IMG_CACHE.get(key)
    if got is not None:
        return got
    img = tk.PhotoImage(width=w, height=h)
    r = min(r, w // 2, h // 2)
    denom = max(1, w - 1)
    for x in range(w):
        img.put(_blend(c1, c2, x / denom), to=(x, 0, x, h))
    for px, py, cov in _corner_pixels(w, h, r):
        if cov <= 0.02:
            img.put("", to=(px, py))
        else:
            col = _blend(c1, c2, px / denom)
            img.put(_blend(outside, col, cov), to=(px, py))
    _IMG_CACHE[key] = img
    return img


def _rounded_points(x, y, w, h, r, steps=8):
    """Pontos (x0,y0,...) de um retângulo arredondado p/ create_polygon."""
    r = min(r, w // 2, h // 2)
    arcs = ((x + r, y + r, 180), (x + w - r, y + r, 270),
            (x + w - r, y + h - r, 0), (x + r, y + h - r, 90))
    pts = []
    for cx, cy, start in arcs:
        for i in range(steps + 1):
            a = math.radians(start + 90.0 * i / steps)
            pts.append(cx + r * math.cos(a))
            pts.append(cy + r * math.sin(a))
    return pts

class _BrowserWatcher(threading.Thread):
    """Checa (a cada 5s, em 2º plano) se o Chrome do Change Project está aberto."""

    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                value = _cms_manual_browser_open_raw()
            except Exception:
                value = False
            self.app.browser_open_value = value
            self.app.browser_open_ts = time.time()
            self._stop.wait(5)

    def stop(self):
        self._stop.set()


if TK_AVAILABLE:

    class RoundCard(tk.Canvas):
        """Cartão arredondado (fundo por imagem) com frame interno.

        self.inner recebe os widgets; o frame é enquadrado dentro do cartão
        para os cantos arredondados ficarem visíveis.
        """

        def __init__(self, parent, parent_bg, fill, radius=16, width=None,
                     fixed_height=None, inset=10, card_list=None):
            super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0,
                             width=width or 12, height=fixed_height or 12)
            self._fill = fill
            self._parent_bg = parent_bg
            self._radius = radius
            self._inset = inset
            self._fixed_h = fixed_height
            self._img = None
            self._last_w = 0
            self._last_h = 0
            self._job = None
            self.inner = tk.Frame(self, bg=fill)
            self._win_item = self.create_window(inset, inset, window=self.inner,
                                                anchor="nw")
            self.bind("<Configure>", self._on_configure)
            if card_list is not None:
                card_list.append(self)

        def _on_configure(self, _event):
            w = self.winfo_width()
            h = self._fixed_h or self.winfo_height()
            if w == self._last_w and h == self._last_h:
                return
            self._last_w, self._last_h = w, h
            if self._job is not None:
                try:
                    self.after_cancel(self._job)
                except Exception:
                    pass
            self._job = self.after(50, self._redraw_now)

        def _redraw_now(self):
            self._job = None
            w = self.winfo_width()
            h = self._fixed_h or self.winfo_height()
            if w < self._inset * 2 + 12 or h < self._inset * 2 + 12:
                return
            r = min(self._radius, w // 2, h // 2)
            self._img = _rounded_photo(w, h, r, self._fill, self._parent_bg)
            self.delete("all")
            self.create_image(0, 0, anchor="nw", image=self._img)
            self.create_window(self._inset, self._inset, window=self.inner,
                               anchor="nw", width=w - 2 * self._inset,
                               height=h - 2 * self._inset)

        def _finalize_height(self):
            """Fixa a altura do cartão pela altura natural do conteúdo."""
            self.inner.update_idletasks()
            self._fixed_h = self.inner.winfo_reqheight() + 2 * self._inset
            self.configure(height=self._fixed_h)
            self._redraw_now()

    _BTN_VARIANTS = {
        "default": (C_CARD2, C_CARD3, C_CARD3, C_TEXT),
        "cyan": (C_CARD2, C_CARD3, C_CARD3, C_CYAN),
        "danger": ("#2A141C", "#3A1B26", "#3A1B26", "#FCA5A5"),
        "ghost": (None, C_CARD2, C_CARD3, C_MUTED),
    }

    class RoundButton(tk.Canvas):
        """Botão em pill desenhado em canvas (hover/press, sem bordas duras).

        Compatível com o uso antigo: configure(command=...),
        config(state="disabled"/"normal"), config(text=...).
        """

        def __init__(self, parent, text, command=None, variant="default",
                     height=32, radius=None, font=None, bg=None,
                     stretch=False, state="normal"):
            self._command = command
            self._variant = variant
            self._stretch = stretch
            self._state = state if state in ("normal", "disabled") else "normal"
            self._text = str(text)
            self._font = font if font is not None else (FONT, 9, "bold")
            self._height = height
            self._radius = radius if radius is not None else height // 2
            self._bg = bg if bg is not None else C_CARD
            self._hover = False
            self._press = False
            self._img = None
            bold = len(self._font) > 2 and self._font[2] == "bold"
            self._fnt = tkfont.Font(family=self._font[0], size=self._font[1],
                                    weight="bold" if bold else "normal")
            w = self._fnt.measure(self._text) + 30
            super().__init__(parent, width=max(w, 56), height=height,
                             bg=self._bg, highlightthickness=0, bd=0,
                             cursor="hand2")
            self.bind("<Button-1>", self._on_click)
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
            self.bind("<ButtonPress-1>", self._on_press)
            self.bind("<ButtonRelease-1>", self._on_release)
            if stretch:
                self.bind("<Configure>", lambda _e: self._draw())
            if self._state == "disabled":
                tk.Canvas.configure(self, cursor="arrow")
            self._draw()

        # -- estados --
        def _on_enter(self, _e):
            if self._state == "normal":
                self._hover = True
                self._draw()

        def _on_leave(self, _e):
            self._hover = False
            self._press = False
            self._draw()

        def _on_press(self, _e):
            if self._state == "normal":
                self._press = True
                self._draw()

        def _on_release(self, _e):
            if self._state == "normal":
                self._press = False
                self._draw()

        def _on_click(self, _e):
            if self._state == "normal" and callable(self._command):
                self._command()

        def _draw(self):
            w = self.winfo_width()
            if w < 4:
                w = int(self.cget("width"))
            h = self._height
            if w < self._radius * 2 + 12:
                return
            self.delete("all")
            if self._variant == "primary":
                if self._state == "disabled":
                    self.create_polygon(
                        _rounded_points(0, 0, w, h, self._radius),
                        fill=self._bg, outline="")
                    fg = C_FAINT
                else:
                    g = {(False, False): (C_ACCENT, "#38BDF8"),
                         (True, False): (C_ACCENT2, "#5EC8F8"),
                         (False, True): (C_ACCENT3, "#2F9FD8")}
                    g1, g2 = g[(self._press, self._hover)]
                    self._img = _gradient_photo_h(w, h, self._radius, g1, g2,
                                                  self._bg)
                    self.create_image(0, 0, anchor="nw", image=self._img)
                    fg = "white"
            else:
                fill, hover, pressed, fg = _BTN_VARIANTS[self._variant]
                if self._state == "disabled":
                    fill = self._bg
                    fg = C_FAINT
                elif self._press:
                    fill = pressed
                elif self._hover:
                    fill = hover
                if fill is None:  # ghost: mescla com o fundo
                    fill = self._bg
                self.create_polygon(_rounded_points(0, 0, w, h, self._radius),
                                    fill=fill, outline="")
            self.create_text(w / 2, h / 2 + 1, text=self._text, fill=fg,
                             font=self._font)

        def config(self, **kw):
            if "command" in kw:
                self._command = kw["command"]
            if "state" in kw:
                self._state = (kw["state"]
                               if kw["state"] in ("normal", "disabled")
                               else "normal")
                tk.Canvas.configure(self, cursor="hand2"
                                    if self._state == "normal" else "arrow")
            if "text" in kw:
                self._text = str(kw["text"])
                if not self._stretch:
                    tk.Canvas.configure(self, width=max(
                        self._fnt.measure(self._text) + 30, 56))
                    # redesenha apos o grid alocar a nova largura
                    self.after_idle(self._draw)
            self._draw()
            return None

        configure = config

    class _RoundCheck(tk.Canvas):
        """Checkbox arredondado (desenhado em canvas)."""

        def __init__(self, parent, variable, command=None, size=18, bg=C_CARD):
            super().__init__(parent, width=size, height=size, bg=bg,
                             highlightthickness=0, bd=0, cursor="hand2")
            self.var = variable
            self.command = command
            self._size = size
            self.bind("<Button-1>", self._on_click)
            self._draw()

        def _on_click(self, _e):
            self.var.set(not self.var.get())
            if callable(self.command):
                self.command()
            self._draw()

        def _draw(self):
            s = self._size
            self.delete("all")
            if self.var.get():
                self.create_polygon(_rounded_points(1, 1, s - 2, s - 2, 6),
                                    fill=C_ACCENT, outline="")
                self.create_line(s * 0.30, s * 0.52, s * 0.45, s * 0.66,
                                 s * 0.72, s * 0.34, fill="white", width=2)
            else:
                self.create_polygon(_rounded_points(1, 1, s - 2, s - 2, 6),
                                    fill="", outline="#3A476B", width=2)

    class _QueueRow(tk.Canvas):
        """Linha da fila: cartão arredondado com faixa de status, checkbox,
        id + título, barra de progresso, chip e botões."""

        H = 64

        def __init__(self, parent, app, item, flow_active):
            super().__init__(parent, height=self.H, bg=C_CARD,
                             highlightthickness=0, bd=0)
            self.app = app
            self.item = item
            self.flow_active = flow_active
            self._img = None
            self._last_w = 0
            self._f_small = tkfont.Font(family=FONT, size=9)
            self._f_tiny = tkfont.Font(family=FONT, size=8)
            self._f_mono = tkfont.Font(family=F_MONO, size=10, weight="bold")
            self._build_chip(item)
            self._build_buttons(item)
            self.bind("<Configure>", lambda _e: self._relayout())

        # -- sub-visualizações --
        def _build_chip(self, item):
            status = str(item.get("status") or "")
            kind = chip_class(status)
            bg, fg, _ = CHIP_STYLES[kind]
            f = tkfont.Font(family=FONT, size=8, weight="bold")
            w = max(40, f.measure(status) + 24)
            self._chip = tk.Canvas(self, width=w, height=22, bg=C_CARD2,
                                   highlightthickness=0, bd=0)
            self._chip_img = _rounded_photo(w, 22, 11, bg, C_CARD2)
            self._chip.create_image(0, 0, anchor="nw", image=self._chip_img)
            self._chip.create_text(w / 2, 11, text=status, fill=fg,
                                   font=(FONT, 8, "bold"))

        def _build_buttons(self, item):
            cid = str(item.get("content_id", "")).strip()
            status = item.get("status")
            progress = int(item.get("progress", 0) or 0)
            is_final = (is_final_success_status(status)
                        or is_final_neutral_status(status)
                        or is_final_error_status(status)
                        or progress >= 100)
            item_running = (cid in self.app.running_content_ids
                            or is_running_status(status))
            disable_item = (not is_final) and (self.flow_active or item_running)

            label = display_button_label(item, cid,
                                         self.app.running_content_ids)
            b = RoundButton(self, label, height=26, bg=C_CARD2,
                            variant="primary" if not is_final else "default",
                            command=lambda _cid=cid:
                                self.app._on_item_process(_cid))
            if disable_item:
                b.config(state="disabled")
            self._btns = [b]

            is_generated = (progress >= 80
                            and norm_status(status)
                            in {"arquivo gerado", "gerado"})
            can_upload = is_generated and not is_final_success_status(status)
            b = RoundButton(self, "Upload", height=26, bg=C_CARD2,
                            variant="primary" if can_upload else "default",
                            command=lambda _cid=cid:
                                self.app._on_item_upload(_cid))
            if not can_upload or self.flow_active:
                b.config(state="disabled")
            self._btns.append(b)

            b = RoundButton(self, "Remover", height=26, bg=C_CARD2,
                            variant="danger",
                            command=lambda _cid=cid:
                                self.app._on_item_remove(_cid))
            if self.flow_active and not is_final:
                b.config(state="disabled")
            self._btns.append(b)

            report_path = str(item.get("report_file") or "").strip()
            if report_path and Path(report_path).exists():
                b = RoundButton(self, "Rel.", height=26, bg=C_CARD2,
                                variant="ghost",
                                command=lambda: (
                                    open_path(
                                        Path(report_path).with_suffix(".txt"))
                                    or open_path(Path(report_path))))
                if self.flow_active:
                    b.config(state="disabled")
                self._btns.append(b)
            final_vtt = BASE_DIR / "saida" / f"{cid}.vtt"
            if final_vtt.exists():
                b = RoundButton(self, ".vtt", height=26, bg=C_CARD2,
                                variant="ghost",
                                command=lambda: open_path(final_vtt))
                if self.flow_active:
                    b.config(state="disabled")
                self._btns.append(b)

        # -- layout --
        def _relayout(self):
            w = self.winfo_width()
            if w < 320 or w == self._last_w:
                return
            self._last_w = w
            h = self.H
            self.delete("all")
            self._img = _rounded_photo(w, h, 12, C_CARD2, C_CARD)
            self.create_image(0, 0, anchor="nw", image=self._img)

            item = self.item
            cid = str(item.get("content_id", "")).strip()
            title = str(item.get("content_title") or "").strip()
            status = item.get("status")
            message = str(item.get("message", ""))
            progress = int(item.get("progress", 0) or 0)
            color = bar_color(status)

            # botões (à direita)
            gap = 6
            total = sum(b.winfo_reqwidth() for b in self._btns) + \
                gap * (len(self._btns) - 1)
            bx = w - 14 - total
            for b in self._btns:
                bw = b.winfo_reqwidth()
                self.create_window(bx, (h - 26) // 2, window=b, anchor="nw")
                bx += bw + gap

            # chip + modo/idioma
            mode_w = 96
            chip_w = self._chip.winfo_reqwidth()
            chip_x = bx - 14 - mode_w - 12 - chip_w
            self.create_window(chip_x, (h - 22) // 2, window=self._chip,
                               anchor="nw")
            mx = chip_x - 18
            is_final = (is_final_success_status(status)
                        or is_final_neutral_status(status)
                        or is_final_error_status(status)
                        or progress >= 100)
            item_running = (cid in self.app.running_content_ids
                            or is_running_status(status))
            if item_running and not is_final:
                self.create_text(mx, 22, anchor="e", text="Processando…",
                                 fill=C_BLUE2, font=(FONT, 8, "bold"))
            elif self.flow_active and not is_final:
                self.create_text(mx, 22, anchor="e", text="Fila em execução",
                                 fill=C_BLUE2, font=(FONT, 8, "bold"))
            else:
                idioma = ("Espanhol" if self.app._selected_language() == "es"
                          else "Português")
                self.create_text(mx, 20, anchor="e", text=idioma,
                                 fill=C_MUTED, font=self._f_tiny)
                self.create_text(mx, 36, anchor="e", text="sem envio",
                                 fill=C_FAINT, font=self._f_tiny)

            # coluna 1: id, título, barra, mensagem
            x = 56
            col1_w = max(180, chip_x - 20 - x)
            self.create_text(x, 19, anchor="w", text=cid, fill=C_CYAN,
                             font=self._f_mono)
            id_w = self._f_mono.measure(cid)
            if title and title.lower() != "nan":
                avail = col1_w - id_w - 10
                t = title
                while self._f_small.measure(t) > avail and len(t) > 4:
                    t = t[:-1]
                if t != title:
                    t = t.rstrip() + "…"
                self.create_text(x + id_w + 10, 19, anchor="w", text=t,
                                 fill=C_MUTED, font=self._f_small)
            self._paint_bar(x, 33, col1_w, progress, color)
            m = message
            while self._f_tiny.measure(m) > col1_w and len(m) > 4:
                m = m[:-1]
            if m != message:
                m = m.rstrip() + "…"
            self.create_text(x, 50, anchor="w", text=m, fill=C_FAINT,
                             font=self._f_tiny)

            # faixa de destaque (cor do status) + checkbox
            self.create_polygon(_rounded_points(10, 12, 4, h - 24, 2),
                                fill=color, outline="")
            checked = cid in self.app.selected
            s = 18
            cx, cy = 34, h / 2
            if checked:
                self.create_polygon(
                    _rounded_points(cx - s / 2, cy - s / 2, s, s, 6),
                    fill=C_ACCENT, outline="")
                self.create_line(cx - 4.5, cy + 0.5, cx - 1.5, cy + 3.5,
                                 cx + 4.5, cy - 3.5, fill="white", width=2)
            else:
                self.create_polygon(
                    _rounded_points(cx - s / 2, cy - s / 2, s, s, 6),
                    fill="", outline="#3A476B", width=2)
            if not self.flow_active:
                self.bind("<Button-1>", self._on_check)

        def _paint_bar(self, x, y, w, progress, color):
            h = 6
            r = h // 2
            self.create_polygon(_rounded_points(x, y, w, h, r),
                                fill=C_TRACK, outline="")
            p = max(0, min(100, int(progress)))
            if p > 0:
                fw = min(w, max(h, int(w * p / 100)))
                self.create_polygon(_rounded_points(x, y, fw, h, r),
                                    fill=color, outline="")

        def _on_check(self, _e):
            if self.flow_active:
                return
            cid = str(self.item.get("content_id", "")).strip()
            if cid in self.app.selected:
                self.app.selected.discard(cid)
            else:
                self.app.selected.add(cid)
            self.app.refresh()

class SubNexusApp:
    def __init__(self):
        ensure_dirs()

        self.root = tk.Tk()
        self.root.title("SubNexus")
        self.root.configure(bg=C_BG)
        self.root.geometry("1320x820")
        self.root.minsize(1120, 680)
        if FAVICON_FILE.exists():
            try:
                self._icon = tk.PhotoImage(file=str(FAVICON_FILE))
                self.root.iconphoto(True, self._icon)
            except Exception:
                self._icon = None

        # ------------------------------------------------ estado
        self.queue_ids: list = load_queue()
        self.selected: set = set()
        self.overrides: dict = {}
        self.running_content_ids: set = set()
        self.demo_mode = not EDITOR_SCRIPT.exists()
        self.demo_started = False
        self.demo_start_ts = time.time()
        self.browser_open_value = False
        self.browser_open_ts = 0.0
        self._last_signature: str = ""

        self.auto_var = tk.BooleanVar(value=True)
        self.interval_var = tk.StringVar(value="3")
        self.language_var = tk.StringVar(value="Português")

        self._browser_watcher = _BrowserWatcher(self)
        self._browser_watcher.start()

        self._setup_styles()
        self._build_layout()
        self.refresh()
        self._schedule_tick()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------ estilos

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.root.option_add("*TCombobox*Listbox.background", C_CARD2)
        self.root.option_add("*TCombobox*Listbox.foreground", C_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", C_CARD3)
        self.root.option_add("*TCombobox*Listbox.selectForeground", C_TEXT)
        style.configure("Sub.TCombobox", fieldbackground=C_CARD2,
                        background=C_CARD3, foreground=C_TEXT,
                        arrowcolor=C_MUTED, bordercolor=C_LINE,
                        lightcolor=C_CARD2, darkcolor=C_CARD2,
                        insertcolor=C_TEXT, relief="flat", padding=(8, 5),
                        font=F_SMALL, selectbackground=C_CARD3,
                        selectforeground=C_TEXT)
        style.map("Sub.TCombobox",
                  fieldbackground=[("disabled", C_CARD)],
                  foreground=[("disabled", C_FAINT)])
        style.configure("Sub.Vertical.TScrollbar", background=C_CARD3,
                        troughcolor=C_CARD, bordercolor=C_CARD,
                        arrowcolor=C_FAINT, lightcolor=C_CARD3,
                        darkcolor=C_CARD3, relief="flat", arrowsize=10)
        style.map("Sub.Vertical.TScrollbar",
                  background=[("active", C_CARD3)])

    # ------------------------------------------------ layout

    def _build_layout(self):
        self._cards = []
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._build_brand_band()
        self._build_body()
        self._build_statusbar()
        self.root.update_idletasks()
        for c in self._cards:
            c._redraw_now()
        self._on_accent_line()

    def _build_brand_band(self):
        band = RoundCard(self.root, C_BG, C_CARD, radius=18, fixed_height=96,
                         card_list=self._cards)
        band.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        inner = band.inner
        inner.columnconfigure(1, weight=1)
        inner.rowconfigure(1, weight=1)

        if LOGO_FILE.exists():
            try:
                img = tk.PhotoImage(file=str(LOGO_FILE))
                self._logo = img
                # reduz para até ~56px de altura mantendo a proporção
                if img.height() > 56:
                    factor = max(2, int(round(img.height() / 56)))
                    img = img.subsample(factor, factor)
                tk.Label(inner, image=img, bg=C_CARD).grid(
                    row=0, column=0, rowspan=2, sticky="w", padx=(8, 20))
            except Exception:
                self._logo = None
        else:
            self._logo = None

        word = tk.Frame(inner, bg=C_CARD)
        word.grid(row=0, column=1, sticky="w")
        tk.Label(word, text="Sub", bg=C_CARD, fg=C_TEXT,
                 font=F_BRAND).pack(side="left")
        tk.Label(word, text="Nexus", bg=C_CARD, fg=C_CYAN,
                 font=F_BRAND).pack(side="left", padx=(1, 0))
        tk.Label(inner, text="Accenture Business  •  Automação de Legendas CMS",
                 bg=C_CARD, fg=C_MUTED, font=F_SMALL).grid(
            row=1, column=1, sticky="w")

        if self.demo_mode:
            self._make_demo_pill(inner)

        self._accent_line = tk.Canvas(inner, height=2, bg=C_CARD,
                                      highlightthickness=0)
        self._accent_line.grid(row=2, column=0, columnspan=3, sticky="ew",
                               pady=(8, 0))
        self._accent_line.bind("<Configure>", self._on_accent_line)

    def _on_accent_line(self, _event=None):
        w = self._accent_line.winfo_width()
        if w < 12:
            return
        self._accent_line.delete("all")
        img = _gradient_photo_h(w, 2, 1, C_ACCENT, C_CYAN, C_CARD)
        self._accent_line._img = img
        self._accent_line.create_image(0, 0, anchor="nw", image=img)

    def _make_demo_pill(self, parent):
        text = "Modo demonstração (sem vtt_auto_editor.py)"
        f = tkfont.Font(family=FONT, size=8, weight="bold")
        w = f.measure(text) + 26
        pill = tk.Canvas(parent, width=w, height=24, bg=C_CARD,
                         highlightthickness=0, bd=0)
        pill._img = _rounded_photo(w, 24, 12, "#33270F", C_CARD)
        pill.create_image(0, 0, anchor="nw", image=pill._img)
        pill.create_text(w / 2, 12, text=text, fill="#FDE68A", font=F_TINY)
        pill.grid(row=0, column=2, sticky="e", padx=(0, 8))
        return pill

    def _build_body(self):
        body = tk.Frame(self.root, bg=C_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        side = RoundCard(body, C_BG, C_CARD, radius=18, width=248,
                         card_list=self._cards)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self._build_sidebar(side.inner)

        main = tk.Frame(body, bg=C_BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        self._build_main(main)

    def _build_sidebar(self, side):
        side.configure(bg=C_CARD)
        side.columnconfigure(0, weight=1)

        def section(row, text):
            tk.Label(side, text=text.upper(), bg=C_CARD, fg=C_FAINT,
                     font=F_SECTION, anchor="w").grid(
                row=row, column=0, sticky="ew", padx=18, pady=(16, 6))

        section(0, "Ações rápidas")
        self.btn_change_project = RoundButton(
            side, "Change Project", command=self._on_change_project,
            variant="cyan", height=34, stretch=True, bg=C_CARD)
        self.btn_change_project.grid(row=1, column=0, sticky="ew",
                                     padx=16, pady=(0, 8))
        self.btn_confirm_instance = RoundButton(
            side, "Confirmar instância atual",
            command=self._on_confirm_instance, variant="default", height=34,
            stretch=True, bg=C_CARD)
        self.btn_confirm_instance.grid(row=2, column=0, sticky="ew",
                                       padx=16, pady=(0, 10))
        self.lbl_instance = tk.Label(side, text="", bg=C_CARD, fg=C_MUTED,
                                     font=F_SMALL, anchor="w")
        self.lbl_instance.grid(row=3, column=0, sticky="ew", padx=18,
                               pady=(2, 2))
        self.lbl_instance_warn = tk.Label(
            side, text="", bg=C_CARD, fg="#FDE68A", font=F_TINY,
            wraplength=196, justify="left", anchor="w")
        self.lbl_instance_warn.grid(row=4, column=0, sticky="ew", padx=18)
        self.lbl_browser = tk.Label(side, text="", bg=C_CARD, fg="#93C5FD",
                                    font=F_TINY, wraplength=196,
                                    justify="left", anchor="w")
        self.lbl_browser.grid(row=5, column=0, sticky="ew", padx=18)
        self._divider(side, 6)

        r = 7
        section(r, "Pastas")
        r += 1
        folder_rows = [
            ("Abrir pasta de saída", "Finais"),
            ("Abrir originais", "Originais"),
            ("Abrir relatórios", "Relatórios"),
            ("Abrir tempos", "TEMPOS"),
        ]
        for label, key in folder_rows:
            b = RoundButton(side, label,
                            command=lambda k=key: self._on_open_folder(k),
                            variant="default", height=30, stretch=True,
                            bg=C_CARD)
            b.grid(row=r, column=0, sticky="ew", padx=16, pady=3)
            r += 1
        self._divider(side, r)
        r += 1

        section(r, "Atualização")
        r += 1
        auto_row = tk.Frame(side, bg=C_CARD)
        auto_row.grid(row=r, column=0, sticky="ew", padx=16, pady=(2, 8))
        self.chk_auto = _RoundCheck(auto_row, variable=self.auto_var)
        self.chk_auto.pack(side="left")
        tk.Label(auto_row, text="Atualizar automaticamente", bg=C_CARD,
                 fg=C_TEXT, font=F_SMALL).pack(side="left", padx=(8, 0))
        r += 1
        row_interval = tk.Frame(side, bg=C_CARD)
        row_interval.grid(row=r, column=0, sticky="ew", padx=16, pady=(0, 8))
        tk.Label(row_interval, text="Intervalo (s):", bg=C_CARD, fg=C_MUTED,
                 font=F_SMALL).pack(side="left")
        self.cmb_interval = ttk.Combobox(
            row_interval, textvariable=self.interval_var,
            values=["2", "3", "5", "10"], state="readonly", width=4,
            style="Sub.TCombobox")
        self.cmb_interval.pack(side="left", padx=(8, 0))
        r += 1
        self.btn_refresh_now = RoundButton(
            side, "Atualizar agora",
            command=lambda: (self.refresh(), self._flash("Atualizado.")),
            variant="default", height=32, stretch=True, bg=C_CARD)
        self.btn_refresh_now.grid(row=r, column=0, sticky="ew",
                                  padx=16, pady=(2, 6))
        r += 1
        self.btn_stop = RoundButton(side, "Parar fluxo",
                                    command=self._on_stop_flow,
                                    variant="danger", height=32,
                                    stretch=True, bg=C_CARD)
        self.btn_stop.grid(row=r, column=0, sticky="ew", padx=16, pady=(0, 2))
        r += 1
        self._divider(side, r)
        r += 1

        section(r, "Limpeza")
        r += 1
        self.btn_clean_exec = RoundButton(
            side, "Limpar execução atual", command=self._on_clean_exec,
            variant="default", height=32, stretch=True, bg=C_CARD)
        self.btn_clean_exec.grid(row=r, column=0, sticky="ew", padx=16,
                                 pady=3)
        r += 1
        self.btn_clear_queue = RoundButton(
            side, "Limpar fila", command=self._on_clear_queue,
            variant="ghost", height=32, stretch=True, bg=C_CARD)
        self.btn_clear_queue.grid(row=r, column=0, sticky="ew", padx=16,
                                  pady=(3, 14))

    def _divider(self, parent, row):
        tk.Frame(parent, bg=C_LINE, height=1).grid(
            row=row, column=0, sticky="ew", padx=18, pady=12)

    def _build_main(self, main):
        # ---------- modo + idioma ----------
        top = tk.Frame(main, bg=C_BG)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=5)
        top.columnconfigure(1, weight=7)

        mode_card = RoundCard(top, C_BG, C_CARD, radius=16,
                              card_list=self._cards)
        mode_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        mi = mode_card.inner
        mi.columnconfigure(0, weight=1)
        tk.Label(mi, text="MODO DE EXECUÇÃO", bg=C_CARD, fg=C_FAINT,
                 font=F_SECTION, anchor="w").grid(row=0, column=0,
                                                  sticky="ew", pady=(0, 8))
        mode_row = tk.Frame(mi, bg=C_CARD)
        mode_row.grid(row=1, column=0, sticky="ew")
        self._seg_manual = RoundButton(mode_row, "Manual", variant="primary",
                                       height=30, bg=C_CARD)
        self._seg_manual.grid(row=0, column=0, sticky="w", padx=(2, 6))
        self._seg_auto = RoundButton(mode_row, "Automático", variant="ghost",
                                     height=30, state="disabled", bg=C_CARD)
        self._seg_auto.grid(row=0, column=1, sticky="w")

        lang_card = RoundCard(top, C_BG, C_CARD, radius=16,
                              card_list=self._cards)
        lang_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        li = lang_card.inner
        li.columnconfigure(0, weight=1)
        tk.Label(li, text="IDIOMA DA LEGENDA", bg=C_CARD, fg=C_FAINT,
                 font=F_SECTION, anchor="w").grid(row=0, column=0,
                                                  sticky="ew", pady=(0, 8))
        self.cmb_language = ttk.Combobox(li, textvariable=self.language_var,
                                         values=list(LANGUAGE_OPTIONS.keys()),
                                         state="readonly", width=14,
                                         style="Sub.TCombobox")
        self.cmb_language.grid(row=1, column=0, sticky="w")
        self.cmb_language.bind("<<ComboboxSelected>>", self._on_language_change)
        self.lbl_lang_locked = tk.Label(li, text="", bg=C_CARD, fg=C_FAINT,
                                        font=F_TINY)
        self.lbl_lang_locked.grid(row=2, column=0, sticky="w", pady=(6, 2))

        mode_card.inner.update_idletasks()
        lang_card.inner.update_idletasks()
        h = max(mode_card.inner.winfo_reqheight(),
                lang_card.inner.winfo_reqheight()) + 2 * mode_card._inset
        for c in (mode_card, lang_card):
            c._fixed_h = h
            c.configure(height=h)

        # ---------- adicionar à fila + progresso geral ----------
        mid = tk.Frame(main, bg=C_BG)
        mid.grid(row=1, column=0, sticky="ew")
        mid.columnconfigure(0, weight=11)
        mid.columnconfigure(1, weight=9)

        add_card = RoundCard(mid, C_BG, C_CARD, radius=16,
                             card_list=self._cards)
        add_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ai = add_card.inner
        ai.columnconfigure(0, weight=1)
        tk.Label(ai, text="ADICIONAR À FILA", bg=C_CARD, fg=C_FAINT,
                 font=F_SECTION, anchor="w").grid(row=0, column=0,
                                                  sticky="ew", pady=(0, 8))
        well = RoundCard(ai, C_CARD, C_CARD2, radius=14, inset=8,
                         card_list=self._cards)
        well.grid(row=1, column=0, sticky="ew")
        wi = well.inner
        wi.columnconfigure(0, weight=1)
        self.txt_ids = tk.Text(wi, height=7, bg=C_CARD2, fg=C_TEXT,
                               insertbackground=C_ACCENT, relief="flat",
                               font=F_SMALL, wrap="none", bd=0,
                               highlightthickness=0, padx=10, pady=8,
                               selectbackground="#3358C4",
                               selectforeground="white")
        self.txt_ids.grid(row=0, column=0, sticky="nsew")
        self.txt_ids.insert(
            "1.0", "Cole um ou mais Content IDs (um por linha, ou com vírgula).")
        self.txt_ids.tag_config("placeholder", foreground=C_FAINT)
        self.txt_ids.bind("<Key>", self._on_ids_key)
        self.txt_ids.bind("<KeyRelease>", self._on_ids_edit)
        self.txt_ids.bind("<FocusIn>", self._on_ids_focus_in)
        self.txt_ids.bind("<FocusOut>", self._on_ids_focus_out)
        self.txt_ids.tag_add("placeholder", "1.0", "end")
        well._finalize_height()
        self.lbl_detected = tk.Label(ai, text="0 conteúdo(s) detectado(s)",
                                     bg=C_CARD, fg=C_FAINT, font=F_TINY)
        self.lbl_detected.grid(row=2, column=0, sticky="w", pady=(8, 8))
        self.btn_add = RoundButton(ai, "Adicionar à fila",
                                   command=self._on_add_to_queue,
                                   variant="primary", height=36, bg=C_CARD)
        self.btn_add.grid(row=3, column=0, sticky="w", pady=(0, 2))
        add_card._finalize_height()

        prog_card = RoundCard(mid, C_BG, C_CARD, radius=16,
                              card_list=self._cards)
        prog_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        pi = prog_card.inner
        pi.columnconfigure(0, weight=1)
        pi.rowconfigure(3, weight=1)
        tk.Label(pi, text="PROGRESSO GERAL DA FILA", bg=C_CARD, fg=C_FAINT,
                 font=F_SECTION, anchor="w").grid(row=0, column=0,
                                                  sticky="ew", pady=(0, 10))
        self.canvas_overall = tk.Canvas(pi, height=12, bg=C_CARD,
                                        highlightthickness=0)
        self.canvas_overall.grid(row=1, column=0, sticky="ew")
        self.lbl_overall = tk.Label(pi, text="", bg=C_CARD, fg=C_MUTED,
                                    font=F_TINY, anchor="w")
        self.lbl_overall.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        metrics = tk.Frame(pi, bg=C_CARD)
        metrics.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        for i in range(4):
            metrics.columnconfigure(2 * i, weight=1)
            if i < 3:
                metrics.columnconfigure(2 * i + 1, weight=0)
        self.metric_labels = {}
        for i, (name, key) in enumerate([("Total", "total"),
                                         ("Concluídos", "concl"),
                                         ("Pendentes", "pend"),
                                         ("Erros", "erros")]):
            cell = tk.Frame(metrics, bg=C_CARD)
            cell.grid(row=0, column=2 * i, sticky="nsew",
                      padx=(12 if i else 4, 12))
            self.metric_labels[key] = tk.Label(cell, text="0", bg=C_CARD,
                                               fg=C_TEXT, font=F_METRIC)
            self.metric_labels[key].pack(anchor="w", pady=(2, 0))
            tk.Label(cell, text=name.upper(), bg=C_CARD, fg=C_FAINT,
                     font=F_SECTION).pack(anchor="w")
            if i < 3:
                tk.Frame(metrics, bg=C_LINE, width=1, height=34).grid(
                    row=0, column=2 * i + 1, sticky="ns", pady=6)

        # ---------- ações da fila ----------
        actions = tk.Frame(main, bg=C_BG)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        actions.columnconfigure(1, weight=1)
        self.btn_process = RoundButton(actions, "Processar fila inteira",
                                       command=self._on_process,
                                       variant="primary", height=38, bg=C_BG)
        self.btn_process.grid(row=0, column=0, sticky="w", padx=(2, 8))
        self.btn_remove = RoundButton(actions, "Remover concluídos",
                                      command=self._on_remove,
                                      variant="ghost", height=38, bg=C_BG)
        self.btn_remove.grid(row=0, column=2, sticky="e", padx=(8, 6))
        self.btn_clear_queue_main = RoundButton(actions, "Limpar fila",
                                                command=self._on_clear_queue,
                                                variant="ghost", height=38,
                                                bg=C_BG)
        self.btn_clear_queue_main.grid(row=0, column=3, sticky="e")

        # ---------- lista da fila (scrollable) ----------
        list_card = RoundCard(main, C_BG, C_CARD, radius=18,
                              card_list=self._cards)
        list_card.grid(row=3, column=0, sticky="nsew")
        lci = list_card.inner
        lci.columnconfigure(0, weight=1)
        lci.rowconfigure(1, weight=1)
        head = tk.Frame(lci, bg=C_CARD)
        head.grid(row=0, column=0, sticky="ew", pady=(2, 10))
        tk.Label(head, text="Fila de conteúdos", bg=C_CARD, fg=C_TEXT,
                 font=F_TITLE).pack(side="left")
        self.lbl_selected_info = tk.Label(head, text="", bg=C_CARD,
                                          fg=C_FAINT, font=F_TINY)
        self.lbl_selected_info.pack(side="left", padx=(12, 0))
        self.canvas_queue = tk.Canvas(lci, bg=C_CARD, highlightthickness=0)
        self.scroll_queue = ttk.Scrollbar(lci, orient="vertical",
                                          command=self.canvas_queue.yview,
                                          style="Sub.Vertical.TScrollbar")
        self.canvas_queue.configure(yscrollcommand=self.scroll_queue.set)
        self.canvas_queue.grid(row=1, column=0, sticky="nsew")
        self.scroll_queue.grid(row=1, column=1, sticky="ns")
        self.queue_frame = tk.Frame(self.canvas_queue, bg=C_CARD)
        self._queue_canvas_item = self.canvas_queue.create_window(
            (0, 0), window=self.queue_frame, anchor="nw")
        self.canvas_queue.bind("<Configure>", self._on_queue_configure)
        self.queue_frame.bind("<Configure>", self._on_queue_frame_configure)
        self.canvas_queue.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas_queue.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas_queue.bind_all("<Button-5>", self._on_mousewheel_linux)
        self._create_queue_placeholder()

    # ------------------------------------------------ eventos

    def _on_close(self):
        try:
            self._browser_watcher.stop()
        except Exception:
            pass
        self.root.destroy()

    def _schedule_tick(self):
        try:
            interval = max(1, int(float(self.interval_var.get())))
        except Exception:
            interval = 3
        self._tick_job = self.root.after(interval * 1000, self._tick)

    def _tick(self):
        if self.auto_var.get():
            self.refresh()
        self._schedule_tick()

    def _on_mousewheel(self, event):
        self.canvas_queue.yview_scroll(int(-event.delta / 120 or -event.delta), "units")

    def _on_mousewheel_linux(self, event):
        delta = -1 if event.num == 4 else 1
        self.canvas_queue.yview_scroll(delta, "units")

    def _on_queue_configure(self, event):
        self.canvas_queue.itemconfigure(self._queue_canvas_item, width=event.width)

    def _on_queue_frame_configure(self, event):
        self.canvas_queue.configure(scrollregion=self.canvas_queue.bbox("all") or (0, 0, 0, 0))

    def _on_ids_edit(self, _event=None):
        self._update_detected_count()

    def _on_ids_key(self, _event):
        # Remove o texto de exemplo antes que a tecla seja inserida.
        if self.txt_ids.tag_ranges("placeholder"):
            self.txt_ids.delete("1.0", "end")

    def _on_ids_focus_in(self, _event=None):
        if self.txt_ids.get("1.0", "end").strip() == "":
            return
        if self.txt_ids.tag_ranges("placeholder"):
            self.txt_ids.delete("1.0", "end")

    def _on_ids_focus_out(self, _event=None):
        if self.txt_ids.get("1.0", "end").strip() == "":
            self.txt_ids.insert("1.0", "Cole um ou mais Content IDs (um por linha, ou com vírgula).")
            self.txt_ids.tag_add("placeholder", "1.0", "end")

    def _ids_text(self) -> str:
        if self.txt_ids.tag_ranges("placeholder"):
            return ""
        return self.txt_ids.get("1.0", "end").strip()

    def _update_detected_count(self):
        n = len(ids_from_text(self._ids_text()))
        self.lbl_detected.config(text=f"{n} conteúdo(s) detectado(s)")

    def _on_language_change(self, _event=None):
        if self.queue_ids:
            self.cmb_language.set("Português" if self._selected_language() == "pt-br"
                                  else "Espanhol")
            self._flash("Idioma bloqueado enquanto há fila. Limpe a fila para alterar.")
        else:
            self._flash(f"Idioma: {self.language_var.get()}")

    def _selected_language(self) -> str:
        return LANGUAGE_OPTIONS.get(self.language_var.get(), "pt-br")

    # ------------------------------------------------ ações da fila

    def _on_add_to_queue(self):
        detected = ids_from_text(self._ids_text())
        added = 0
        for cid in detected:
            if cid not in self.queue_ids:
                self.queue_ids.append(cid)
                added += 1
        save_queue(self.queue_ids)
        if added:
            self._flash(f"{added} conteúdo(s) adicionado(s) à fila.")
            self.txt_ids.delete("1.0", "end")
            self.txt_ids.insert("1.0", "Cole um ou mais Content IDs (um por linha, ou com vírgula).")
            self.txt_ids.tag_add("placeholder", "1.0", "end")
        else:
            self._flash("Nenhum conteúdo novo para adicionar.")
        self._update_detected_count()
        self.refresh()

    def _on_process(self):
        items = self._current_items()
        processable = set(processable_queue_ids(self.queue_ids, items))
        if self.selected:
            targets = [cid for cid in self.queue_ids if cid in self.selected and cid in processable]
            label = "selecionados"
        else:
            targets = [cid for cid in self.queue_ids if cid in processable]
            label = "fila"
        if not targets:
            self._flash("Nada para processar (tudo já tem status).")
            return
        self._start_flow_bg(targets, upload_existing=False, label=label)

    def _on_remove(self):
        if self.selected:
            remaining = [cid for cid in self.queue_ids if cid not in self.selected]
            removed = len(self.queue_ids) - len(remaining)
        else:
            items = self._current_items()
            by_id = {str(i.get("content_id", "")).strip(): i for i in items}
            remaining = []
            for cid in self.queue_ids:
                item = by_id.get(cid, {})
                progress = int(item.get("progress", 0) or 0)
                status = str(item.get("status", "")).lower()
                if progress < 100 or "erro" in status:
                    remaining.append(cid)
            removed = len(self.queue_ids) - len(remaining)
        self.queue_ids = remaining
        self.selected = {cid for cid in self.selected if cid in remaining}
        save_queue(self.queue_ids)
        self._flash(f"{removed} conteúdo(s) removido(s) da fila.")
        self.refresh()

    def _on_clear_queue(self):
        self.queue_ids = []
        self.selected = set()
        save_queue([])
        self._flash("Fila limpa.")
        self.refresh()

    def _start_flow_bg(self, content_ids, upload_existing, label):
        language = self._selected_language()
        no_upload = True
        for cid in content_ids:
            self.overrides[cid] = {
                "content_id": cid, "status": "Iniciando", "progress": 5,
                "message": "Abrindo navegador e iniciando processamento...",
                "updated_at": time.time(),
            }
        self.running_content_ids.update(content_ids)
        self.refresh()

        def worker():
            ok, msg = start_flow(
                content_ids, no_upload, language=language,
                open_edited_file=False, upload_existing_file=upload_existing,
            )
            self.root.after(0, lambda: self._start_flow_done(content_ids, ok, msg, label))

        threading.Thread(target=worker, daemon=True).start()

    def _start_flow_done(self, content_ids, ok, msg, label):
        if ok:
            self._flash(f"{msg} ({label})")
        else:
            for cid in content_ids:
                self.overrides[cid] = {
                    "content_id": cid, "status": "Erro", "progress": 100,
                    "message": f"Falha ao iniciar: {msg}", "updated_at": time.time(),
                }
            self.running_content_ids -= set(content_ids)
            self._flash(msg)
        self.refresh()

    # ------------------------------------------------ ações do item

    def _on_item_process(self, cid):
        self._start_flow_bg([cid], upload_existing=False, label="item")

    def _on_item_upload(self, cid):
        self._start_flow_bg([cid], upload_existing=True, label="upload")

    def _on_item_remove(self, cid):
        self.queue_ids = [x for x in self.queue_ids if x != cid]
        self.selected.discard(cid)
        save_queue(self.queue_ids)
        self.refresh()

    # ------------------------------------------------ ações rápidas

    def _on_change_project(self):
        def worker():
            ok, msg = open_cms_manual_session()
            self.root.after(0, lambda: self._flash(msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_confirm_instance(self):
        lang = self._selected_language()
        instance = expected_cms_instance(lang)
        write_cms_instance_state(instance, lang)
        self._flash(f"Instância confirmada: {instance} ({lang}).")
        self.refresh()

    def _on_open_folder(self, key):
        if key == "TEMPOS":
            if open_path(TIMING_CSV):
                self._flash("Abrindo arquivo de tempos.")
            else:
                self._flash("O arquivo de tempos será criado no próximo processamento.")
            return
        if open_folder(PASTAS[key]):
            self._flash(f"Pasta aberta: {PASTAS[key].name}")

    def _on_stop_flow(self):
        if request_stop_flow():
            self._flash("Parada solicitada. O item atual pode terminar; os próximos não serão iniciados.")
        else:
            self._flash("Não foi possível solicitar a parada.")

    def _on_clean_exec(self):
        if is_pid_running():
            self._flash("Há um processamento em andamento. Encerre o fluxo antes de limpar.")
            return
        moved = clean_exec()
        if moved:
            self.overrides = {}
            self.running_content_ids = set()
            self._flash(f"Execução limpa ({len(moved)} arquivo(s) arquivado(s)).")
        else:
            self._flash("Nada para limpar.")
        self.refresh()

    # ------------------------------------------------ refresh / render

    def _flash(self, message):
        self.lbl_status.config(text=message, fg=C_TEXT)
        try:
            self.root.after(6000, lambda: self.lbl_status.config(
                text="Pronto." if self.lbl_status.cget("text") == message
                else "",
                fg=C_MUTED))
        except Exception:
            pass

    def _current_items(self):
        items = get_items(
            self.queue_ids, _UI_CACHE, self.overrides,
            self.demo_mode, self.demo_started, self.demo_start_ts,
        )
        items = sorted_queue_items(items)

        # Sincroniza estado: processo morreu sem registrar status final.
        if self.running_content_ids:
            by_id = {str(i.get("content_id", "")).strip(): i for i in items}
            process_alive = is_pid_running()
            for cid in list(self.running_content_ids):
                item = by_id.get(cid)
                if item is None:
                    continue
                status = item.get("status")
                final = (
                    is_final_success_status(status) or is_final_neutral_status(status)
                    or is_final_error_status(status)
                    or int(item.get("progress", 0) or 0) >= 100
                )
                if final:
                    self.running_content_ids.discard(cid)
                elif not process_alive and is_running_status(status):
                    self.overrides[cid] = {
                        "content_id": cid, "status": "Erro", "progress": 100,
                        "message": "Processo encerrado antes de registrar status final. Tente novamente.",
                        "updated_at": time.time(),
                    }
                    self.running_content_ids.discard(cid)
        if not self.running_content_ids:
            _UI_CACHE.pop("_status_csv", None)

        items = sorted_queue_items(get_items(
            self.queue_ids, _UI_CACHE, self.overrides,
            self.demo_mode, self.demo_started, self.demo_start_ts,
        ))
        return items

    def refresh(self):
        try:
            items = self._current_items()
        except Exception as exc:  # nunca derrubar a janela por erro de render
            self._flash(f"Erro ao atualizar: {exc}")
            return

        signature = json.dumps(
            [
                (i.get("content_id"), i.get("status"), i.get("progress"),
                 i.get("message"), i.get("content_title"), i.get("report_file", ""))
                for i in items
            ] + [sorted(self.queue_ids), sorted(self.selected),
                 sorted(self.running_content_ids),
                 bool(self.browser_open_value),
                 read_cms_instance_state().get("instance", "")],
            ensure_ascii=False, sort_keys=True,
        )

        self._update_sidebar(items)
        self._update_overall(items)
        self._update_actions(items)
        self._update_language_lock()

        if signature != self._last_signature:
            self._render_queue(items)
            self._last_signature = signature

    def _update_sidebar(self, items):
        state = read_cms_instance_state()
        confirmed = state.get("instance") or "Não confirmado"
        lang = self._selected_language()
        expected = expected_cms_instance(lang)
        self.lbl_instance.config(text=f"CMS instance: {confirmed}")

        if confirmed not in ("", "Não confirmado") and confirmed != expected:
            self.lbl_instance_warn.config(
                text=f"Idioma selecionado espera {expected}. Confirme a troca no CMS antes de processar.")
        else:
            self.lbl_instance_warn.config(text="")

        fresh = (time.time() - self.browser_open_ts) < 6
        if fresh and self.browser_open_value:
            self.lbl_browser.config(text="Janela do Change Project aberta. Feche o Chrome antes de processar a fila.")
        else:
            self.lbl_browser.config(text="")

    def _update_overall(self, items):
        total, concl, andam, pend, erros, geral, sem_legenda = summary(items)
        self.metric_labels["total"].config(text=str(total))
        self._metric_concl = concl
        self.metric_labels["concl"].config(text=str(concl))
        self.metric_labels["pend"].config(text=str(pend))
        self.metric_labels["erros"].config(text=str(erros))
        self.lbl_overall.config(
            text=(f"{geral}% - {concl} concluído(s), {andam} em andamento, "
                  f"{pend} pendente(s), {erros} erro(s)"))
        color = C_BLUE2 if erros == 0 else C_YELLOW
        self._draw_bar(self.canvas_overall, geral, color)

    def _update_actions(self, items):
        flow_active = bool(self.running_content_ids) or is_pid_running()
        self.btn_process.config(state="disabled" if flow_active else "normal")
        self.btn_remove.config(state="disabled" if (flow_active or not self.queue_ids) else "normal")
        self.btn_clear_queue.config(state="disabled" if (flow_active or not self.queue_ids) else "normal")
        self.btn_clear_queue_main.config(state="disabled" if (flow_active or not self.queue_ids) else "normal")
        self.btn_stop.config(state="disabled" if flow_active else "normal")

        items_by_id = {str(i.get("content_id", "")).strip(): i for i in items}
        processable = set(processable_queue_ids(self.queue_ids, items))
        if self.selected:
            self.btn_process.config(text="Processar selecionados" + (" (processando...)" if flow_active else ""))
        else:
            self.btn_process.config(text="Processar fila inteira" + (" (processando...)" if flow_active else ""))
        self._flow_active = flow_active
        self._items_by_id = items_by_id
        self._processable = processable

    def _update_language_lock(self):
        if self.queue_ids:
            self.cmb_language.config(state="disabled")
            self.lbl_lang_locked.config(text="Bloqueado durante a fila atual.")
        else:
            self.cmb_language.config(state="readonly")
            self.lbl_lang_locked.config(text="")

    def _draw_bar(self, canvas, percent, color):
        canvas.delete("all")
        w = max(24, canvas.winfo_width())
        h = 12
        r = h // 2
        canvas.create_polygon(_rounded_points(0, 0, w, h, r),
                              fill=C_TRACK, outline="")
        p = max(0, min(100, int(percent)))
        if p > 0:
            fw = min(w, max(h, int(w * p / 100)))
            canvas.create_polygon(_rounded_points(0, 0, fw, h, r),
                                  fill=color, outline="")

    def _create_queue_placeholder(self) -> None:
        """Cria (ou recria) o aviso exibido quando a fila está vazia.

        O _render_queue destrói todos os filhos de queue_frame a cada
        atualização; repackar o placeholder antigo (já destruído) causava
        'TclError: bad window path name' ao abrir com fila vazia ou ao
        limpar a fila.
        """
        self.queue_placeholder = tk.Label(
            self.queue_frame,
            text="Adicione Content IDs à fila para iniciar o processamento.",
            bg=C_CARD, fg=C_FAINT, font=F_BODY)
        self.queue_placeholder.pack(pady=24)

    def _render_queue(self, items):
        for child in self.queue_frame.winfo_children():
            child.destroy()

        if not self.queue_ids:
            self._create_queue_placeholder()
            self.lbl_selected_info.config(text="")
            return
        self.lbl_selected_info.config(
            text=(f"{len(self.selected)} conteúdo(s) selecionado(s)."
                  if self.selected else ""))

        flow_active = getattr(self, "_flow_active", False)
        for item in items:
            row = _QueueRow(self.queue_frame, self, item, flow_active)
            row.pack(fill="x", padx=8, pady=5)
        self.queue_frame.update_idletasks()
        for child in self.queue_frame.winfo_children():
            if isinstance(child, _QueueRow):
                child._relayout()

    def _build_statusbar(self):
        bar = RoundCard(self.root, C_BG, C_CARD, radius=14, fixed_height=38,
                        card_list=self._cards)
        bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        bi = bar.inner
        bi.columnconfigure(0, weight=1)
        self.lbl_status = tk.Label(bi, text="Pronto.", bg=C_CARD, fg=C_MUTED,
                                   font=F_SMALL, anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="ew")
        self.lbl_version = tk.Label(bi,
                                    text="SubNexus • interface local (Tkinter)",
                                    bg=C_CARD, fg=C_FAINT, font=F_TINY,
                                    anchor="e")
        self.lbl_version.grid(row=0, column=1, sticky="e")

def main():
    if not TK_AVAILABLE:
        print("ERRO: Tkinter não está disponível neste Python.")
        print(f"Detalhe: {TK_IMPORT_ERROR}")
        print("No Windows, instale o Python com a opção tcl/tk (padrão do instalador oficial).")
        sys.exit(1)

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = SubNexusApp()
    app.root.mainloop()


def _mostrar_erro_fatal() -> None:
    """Mostra o erro em uma janela própria se o app cair antes de abrir a UI.

    Garante que a falha nunca seja silenciosa (ex.: .py executado sem
    console). O detalhe completo continua no console do Iniciar_SubNexus.bat.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "SubNexus - Erro ao iniciar",
            "O SubNexus não conseguiu iniciar.\n\n"
            "Execute Iniciar_SubNexus.bat para ver o erro completo.",
        )
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        print("\nDica: execute Iniciar_SubNexus.bat para ver esta mensagem.")
        _mostrar_erro_fatal()
        sys.exit(1)
