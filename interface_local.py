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
    TK_AVAILABLE = True
    TK_IMPORT_ERROR = ""
except Exception as _tk_exc:  # pragma: no cover
    TK_AVAILABLE = False
    TK_IMPORT_ERROR = str(_tk_exc)

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

C_BG = "#060A12"
C_PANEL = "#0B111D"
C_PANEL2 = "#0D1421"
C_TRACK = "#2B3A55"
C_STROKE = "#24304A"
C_TEXT = "#F8FAFC"
C_MUTED = "#A8B0BF"
C_MUTED2 = "#6B7280"
C_BLUE = "#2563EB"
C_BLUE2 = "#3B82F6"
C_CYAN = "#22D3EE"
C_GREEN = "#22C55E"
C_YELLOW = "#EAB308"
C_RED = "#EF4444"
C_BTN = "#16213A"
C_BTN_HOVER = "#1F2C49"
C_BTN_TEXT = "#DDE7F7"
C_BTN_OFF = "#131B2C"
C_BTN_OFF_TEXT = "#5B6B84"

CHIP_STYLES = {
    "ok":   ("#0F2E1D", "#86EFAC", "#22C55E"),
    "wait": ("#2E2A0F", "#FDE68A", "#EAB308"),
    "err":  ("#33121A", "#FCA5A5", "#EF4444"),
    "run":  ("#0F2138", "#93C5FD", "#3B82F6"),
}


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

        style.configure("Sub.TFrame", background=C_BG)
        style.configure("TLabel", background=C_BG, foreground=C_TEXT, font=(FONT, 10))
        style.configure("Muted.TLabel", background=C_BG, foreground=C_MUTED, font=(FONT, 9))
        style.configure("Title.TLabel", background=C_BG, foreground=C_TEXT,
                        font=(FONT, 12, "bold"))
        style.configure("Sub.TCheckbutton", background=C_BG, foreground="#DDE7F7",
                        focuscolor=C_BG, font=(FONT, 9))
        style.map("Sub.TCheckbutton", background=[("active", C_BG)])

        style.configure("Sub.TButton", background=C_BTN, foreground=C_BTN_TEXT,
                        font=(FONT, 9, "bold"), padding=(10, 6), borderwidth=1,
                        relief="flat", focuscolor=C_BTN, lightcolor=C_BTN, darkcolor=C_BTN)
        style.map("Sub.TButton",
                  background=[("disabled", C_BTN_OFF), ("active", C_BTN_HOVER)],
                  foreground=[("disabled", C_BTN_OFF_TEXT)])

        style.configure("Primary.TButton", background=C_BLUE, foreground="white",
                        font=(FONT, 9, "bold"), padding=(10, 6), borderwidth=1,
                        relief="flat", focuscolor=C_BLUE, lightcolor=C_BLUE, darkcolor=C_BLUE)
        style.map("Primary.TButton",
                  background=[("disabled", "#1E3A8A"), ("active", "#3B82F6")],
                  foreground=[("disabled", "#93A5C8")])

        style.configure("Accent.TButton", background="#0E7490", foreground="white",
                        font=(FONT, 9, "bold"), padding=(10, 6), borderwidth=1,
                        relief="flat", focuscolor="#0E7490", lightcolor="#0E7490", darkcolor="#0E7490")
        style.map("Accent.TButton",
                  background=[("disabled", "#155E75"), ("active", "#0891B2")],
                  foreground=[("disabled", "#A5C8D8")])

        style.configure("Danger.TButton", background="#3F1D24", foreground="#FCA5A5",
                        font=(FONT, 9, "bold"), padding=(10, 6), borderwidth=1,
                        relief="flat", focuscolor="#3F1D24", lightcolor="#3F1D24", darkcolor="#3F1D24")
        style.map("Danger.TButton",
                  background=[("disabled", C_BTN_OFF), ("active", "#55242E")],
                  foreground=[("disabled", C_BTN_OFF_TEXT)])

        style.configure("Sub.TCombobox", fieldbackground=C_PANEL2, background=C_BTN,
                        foreground=C_TEXT, arrowcolor=C_MUTED, lightcolor=C_PANEL2,
                        darkcolor=C_PANEL2, bordercolor=C_STROKE, relief="flat",
                        selectbackground=C_PANEL2, selectforeground=C_TEXT,
                        padding=(6, 4), font=(FONT, 9))

        style.configure("Sub.Vertical.TScrollbar", background=C_BTN, troughcolor=C_BG,
                        bordercolor=C_BG, arrowcolor=C_MUTED, relief="flat")
        style.map("Sub.Vertical.TScrollbar",
                  background=[("active", C_BTN_HOVER)])

    # ------------------------------------------------ layout

    def _build_layout(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_brand_band()
        self._build_body()
        self._build_statusbar()

    def _build_brand_band(self):
        band = tk.Frame(self.root, bg="#050A16", highlightbackground=C_BLUE,
                        highlightthickness=1, height=112)
        band.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        band.grid_propagate(False)

        inner = tk.Frame(band, bg="#050A16")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        row = tk.Frame(inner, bg="#050A16")
        row.pack()

        if LOGO_FILE.exists():
            try:
                img = tk.PhotoImage(file=str(LOGO_FILE))
                self._logo = img
                # reduz para ~150px de largura mantendo a proporção
                if img.width() > 150:
                    factor = max(2, int(round(img.width() / 150)))
                    img = img.subsample(factor, factor)
                tk.Label(row, image=img, bg="#050A16").pack(side="left", padx=(0, 18))
            except Exception:
                self._logo = None

        word = tk.Frame(row, bg="#050A16")
        word.pack(side="left")
        tk.Label(word, text="Sub", bg="#050A16", fg=C_TEXT,
                 font=(FONT, 34, "bold")).pack(side="left")
        tk.Label(word, text="Nexus", bg="#050A16", fg=C_CYAN,
                 font=(FONT, 34, "bold")).pack(side="left", padx=(1, 0))

        tk.Label(inner, text="Accenture Business  •  Automação de Legendas CMS",
                 bg="#050A16", fg=C_MUTED, font=(FONT, 10)).pack(anchor="w", pady=(4, 0))

        if self.demo_mode:
            demo = tk.Frame(band, bg="#2E2A0F", highlightbackground=C_YELLOW,
                            highlightthickness=1)
            demo.place(relx=1.0, rely=0.5, anchor="e", x=-16)
            tk.Label(demo, text="Modo demonstração (vtt_auto_editor.py não encontrado)",
                     bg="#2E2A0F", fg="#FDE68A", font=(FONT, 9, "bold"),
                     padx=10, pady=6).pack()

    def _build_body(self):
        body = tk.Frame(self.root, bg=C_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # ---------------- sidebar (esquerda)
        side = tk.Frame(body, bg=C_PANEL, highlightbackground=C_STROKE,
                        highlightthickness=1, width=252)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        side.grid_propagate(False)
        self._build_sidebar(side)

        # ---------------- conteúdo principal
        main = tk.Frame(body, bg=C_BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        self._build_main(main)

    def _build_sidebar(self, side):
        side.rowconfigure(100, weight=1)

        tk.Label(side, text="Ações rápidas", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 12, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(14, 10))

        self.btn_change_project = ttk.Button(
            side, text="Change Project", style="Accent.TButton")
        self.btn_change_project.configure(command=self._on_change_project)
        self.btn_change_project.grid(row=1, column=0, sticky="ew", padx=12, pady=3)

        self.btn_confirm_instance = ttk.Button(
            side, text="Confirmar instância atual", style="Sub.TButton")
        self.btn_confirm_instance.configure(command=self._on_confirm_instance)
        self.btn_confirm_instance.grid(row=2, column=0, sticky="ew", padx=12, pady=3)

        self.lbl_instance = tk.Label(side, bg=C_PANEL, fg=C_MUTED, font=(FONT, 9))
        self.lbl_instance.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 2))

        self.lbl_instance_warn = tk.Label(
            side, bg=C_PANEL, fg="#FDE68A", font=(FONT, 8), wraplength=220, justify="left")
        self.lbl_instance_warn.grid(row=4, column=0, sticky="ew", padx=12)

        self.lbl_browser = tk.Label(side, bg=C_PANEL, fg="#93C5FD", font=(FONT, 8),
                                    wraplength=220, justify="left")
        self.lbl_browser.grid(row=5, column=0, sticky="ew", padx=12)

        self._divider(side, 6)

        folder_rows = [
            ("Abrir pasta de saída", "Finais"),
            ("Abrir originais", "Originais"),
            ("Abrir relatórios", "Relatórios"),
            ("Abrir tempos", "TEMPOS"),
        ]
        r = 7
        for label, key in folder_rows:
            btn = ttk.Button(side, text=label, style="Sub.TButton")
            btn.configure(command=lambda k=key: self._on_open_folder(k))
            btn.grid(row=r, column=0, sticky="ew", padx=12, pady=2)
            r += 1

        self._divider(side, r)
        r += 1

        self.chk_auto = ttk.Checkbutton(side, text="Atualizar automaticamente",
                                        variable=self.auto_var, style="Sub.TCheckbutton")
        self.chk_auto.grid(row=r, column=0, sticky="w", padx=12, pady=(2, 4))
        r += 1

        row_interval = tk.Frame(side, bg=C_PANEL)
        row_interval.grid(row=r, column=0, sticky="ew", padx=12)
        tk.Label(row_interval, text="Intervalo (s):", bg=C_PANEL, fg=C_MUTED,
                 font=(FONT, 9)).pack(side="left")
        self.cmb_interval = ttk.Combobox(
            row_interval, textvariable=self.interval_var, values=["2", "3", "5", "10"],
            state="readonly", width=4, style="Sub.TCombobox")
        self.cmb_interval.pack(side="left", padx=(6, 0))
        r += 1

        self.btn_refresh_now = ttk.Button(side, text="Atualizar agora", style="Sub.TButton")
        self.btn_refresh_now.configure(command=lambda: (self.refresh(), self._flash("Atualizado.")))
        self.btn_refresh_now.grid(row=r, column=0, sticky="ew", padx=12, pady=(6, 2))
        r += 1

        self.btn_stop = ttk.Button(side, text="Parar fluxo", style="Danger.TButton")
        self.btn_stop.configure(command=self._on_stop_flow)
        self.btn_stop.grid(row=r, column=0, sticky="ew", padx=12, pady=2)
        r += 1

        self._divider(side, r)
        r += 1

        self.btn_clean_exec = ttk.Button(side, text="Limpar execução atual", style="Sub.TButton")
        self.btn_clean_exec.configure(command=self._on_clean_exec)
        self.btn_clean_exec.grid(row=r, column=0, sticky="ew", padx=12, pady=2)
        r += 1

        self.btn_clear_queue = ttk.Button(side, text="Limpar fila", style="Sub.TButton")
        self.btn_clear_queue.configure(command=self._on_clear_queue)
        self.btn_clear_queue.grid(row=r, column=0, sticky="ew", padx=12, pady=2)

    def _divider(self, parent, row):
        tk.Frame(parent, bg=C_STROKE, height=1).grid(
            row=row, column=0, sticky="ew", padx=12, pady=10)

    def _build_main(self, main):
        # ---------- modo + idioma
        top = tk.Frame(main, bg=C_BG)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        mode_box = tk.Frame(top, bg=C_PANEL, highlightbackground=C_STROKE,
                            highlightthickness=1)
        mode_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        tk.Label(mode_box, text="Modo de execução", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 11, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        mode_row = tk.Frame(mode_box, bg=C_PANEL)
        mode_row.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))
        self._mode_dot(mode_row, "Manual", active=True)
        self._mode_dot(mode_row, "Automático", active=False, disabled=True)

        lang_box = tk.Frame(top, bg=C_PANEL, highlightbackground=C_STROKE,
                            highlightthickness=1)
        lang_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 10))
        tk.Label(lang_box, text="Idioma da legenda", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 11, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        self.cmb_language = ttk.Combobox(
            lang_box, textvariable=self.language_var,
            values=list(LANGUAGE_OPTIONS.keys()), state="readonly", width=14,
            style="Sub.TCombobox")
        self.cmb_language.grid(row=1, column=0, sticky="w", padx=12)
        self.cmb_language.bind("<<ComboboxSelected>>", self._on_language_change)
        self.lbl_lang_locked = tk.Label(lang_box, text="", bg=C_PANEL, fg=C_MUTED2,
                                        font=(FONT, 8))
        self.lbl_lang_locked.grid(row=2, column=0, sticky="w", padx=12, pady=(4, 10))

        # ---------- adicionar à fila + progresso geral
        mid = tk.Frame(main, bg=C_BG)
        mid.grid(row=1, column=0, sticky="ew")
        mid.columnconfigure(0, weight=11)
        mid.columnconfigure(1, weight=9)

        add_box = tk.Frame(mid, bg=C_PANEL, highlightbackground=C_STROKE,
                           highlightthickness=1)
        add_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        add_box.columnconfigure(0, weight=1)
        tk.Label(add_box, text="Adicionar à fila", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 11, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        self.txt_ids = tk.Text(
            add_box, height=7, bg=C_PANEL2, fg=C_TEXT, insertbackground=C_TEXT,
            relief="flat", font=(FONT, 9), wrap="none",
            highlightbackground=C_STROKE, highlightthickness=1, bd=0)
        self.txt_ids.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        self.txt_ids.insert("1.0", "Cole um ou mais Content IDs (um por linha, ou com vírgula).")
        self.txt_ids.tag_config("placeholder", foreground=C_MUTED2)
        self.txt_ids.bind("<Key>", self._on_ids_key)
        self.txt_ids.bind("<KeyRelease>", self._on_ids_edit)
        self.txt_ids.bind("<FocusIn>", self._on_ids_focus_in)
        self.txt_ids.bind("<FocusOut>", self._on_ids_focus_out)
        self.txt_ids.tag_add("placeholder", "1.0", "end")
        self.lbl_detected = tk.Label(add_box, text="0 conteúdo(s) detectado(s)",
                                     bg=C_PANEL, fg=C_MUTED, font=(FONT, 8))
        self.lbl_detected.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 6))
        btn_add = ttk.Button(add_box, text="Adicionar à fila", style="Primary.TButton")
        btn_add.configure(command=self._on_add_to_queue)
        btn_add.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))

        prog_box = tk.Frame(mid, bg=C_PANEL, highlightbackground=C_STROKE,
                            highlightthickness=1)
        prog_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        prog_box.columnconfigure(0, weight=1)
        tk.Label(prog_box, text="Progresso geral da fila", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 11, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))
        self.canvas_overall = tk.Canvas(prog_box, height=10, bg=C_PANEL, highlightthickness=0)
        self.canvas_overall.grid(row=1, column=0, sticky="ew", padx=12)
        self.lbl_overall = tk.Label(prog_box, bg=C_PANEL, fg=C_MUTED, font=(FONT, 8))
        self.lbl_overall.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 8))

        metrics = tk.Frame(prog_box, bg=C_PANEL)
        metrics.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 12))
        for i in range(4):
            metrics.columnconfigure(i, weight=1)
        self.metric_labels = {}
        for i, (name, key) in enumerate([("Total", "total"), ("Concluídos", "concl"),
                                         ("Pendentes", "pend"), ("Erros", "erros")]):
            cell = tk.Frame(metrics, bg=C_PANEL2, highlightbackground=C_STROKE,
                            highlightthickness=1)
            cell.grid(row=0, column=i, sticky="nsew", padx=3, pady=3)
            tk.Label(cell, text=name.upper(), bg=C_PANEL2, fg=C_MUTED2,
                     font=(FONT, 7, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
            self.metric_labels[key] = tk.Label(cell, text="0", bg=C_PANEL2, fg=C_TEXT,
                                               font=(FONT, 16, "bold"))
            self.metric_labels[key].pack(anchor="w", padx=8, pady=(0, 6))

        # ---------- ações da fila
        actions = tk.Frame(main, bg=C_BG)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        actions.columnconfigure(1, weight=1)
        self.btn_process = ttk.Button(actions, text="Processar fila inteira",
                                      style="Primary.TButton")
        self.btn_process.configure(command=self._on_process)
        self.btn_process.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.btn_remove = ttk.Button(actions, text="Remover concluídos", style="Sub.TButton")
        self.btn_remove.configure(command=self._on_remove)
        self.btn_remove.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.btn_clear_queue_main = ttk.Button(actions, text="Limpar fila", style="Sub.TButton")
        self.btn_clear_queue_main.configure(command=self._on_clear_queue)
        self.btn_clear_queue_main.grid(row=0, column=2, sticky="w")

        # ---------- lista da fila (scrollable)
        list_box = tk.Frame(main, bg=C_PANEL, highlightbackground=C_STROKE,
                            highlightthickness=1)
        list_box.grid(row=3, column=0, sticky="nsew")
        list_box.columnconfigure(0, weight=1)
        list_box.rowconfigure(1, weight=1)

        head = tk.Frame(list_box, bg=C_PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        tk.Label(head, text="Fila de conteúdos", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 11, "bold")).pack(side="left")
        self.lbl_selected_info = tk.Label(head, text="", bg=C_PANEL, fg=C_MUTED2,
                                          font=(FONT, 8))
        self.lbl_selected_info.pack(side="left", padx=(12, 0))

        self.canvas_queue = tk.Canvas(list_box, bg=C_PANEL, highlightthickness=0)
        self.scroll_queue = ttk.Scrollbar(list_box, orient="vertical",
                                          command=self.canvas_queue.yview,
                                          style="Sub.Vertical.TScrollbar")
        self.canvas_queue.configure(yscrollcommand=self.scroll_queue.set)
        self.canvas_queue.grid(row=1, column=0, sticky="nsew")
        self.scroll_queue.grid(row=1, column=1, sticky="ns")

        self.queue_frame = tk.Frame(self.canvas_queue, bg=C_PANEL)
        self._queue_canvas_item = self.canvas_queue.create_window(
            (0, 0), window=self.queue_frame, anchor="nw")

        self.canvas_queue.bind("<Configure>", self._on_queue_configure)
        self.queue_frame.bind("<Configure>", self._on_queue_frame_configure)

        self.canvas_queue.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas_queue.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas_queue.bind_all("<Button-5>", self._on_mousewheel_linux)

        self._create_queue_placeholder()

    def _mode_dot(self, parent, label, active, disabled=False):
        f = tk.Frame(parent, bg=C_PANEL)
        f.pack(side="left", padx=(0, 18))
        dot_color = C_RED if active else C_PANEL2
        dot_border = "#FF5263" if active else "#3A4A6B"
        dot = tk.Canvas(f, width=16, height=16, bg=C_PANEL, highlightthickness=0)
        dot.pack(side="left", padx=(0, 6))
        dot.create_oval(1, 1, 15, 15, fill=dot_color, outline=dot_border)
        if active:
            dot.create_oval(6, 6, 10, 10, fill="white", outline="")
        tk.Label(f, text=label, bg=C_PANEL,
                 fg=C_TEXT if not disabled else C_MUTED2,
                 font=(FONT, 10, "bold" if active else "normal")).pack(side="left")

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
        self.lbl_status.config(text=message)
        try:
            self.root.after(6000, lambda: self.lbl_status.config(
                text="Pronto." if self.lbl_status.cget("text") == message else ""))
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
        w = max(10, canvas.winfo_width())
        canvas.create_rectangle(0, 0, w, 10, fill=C_TRACK, outline="")
        fill_w = int(w * max(0, min(100, int(percent))) / 100)
        if fill_w > 0:
            canvas.create_rectangle(0, 0, max(fill_w, 8), 10, fill=color, outline="")

    def _create_queue_placeholder(self) -> None:
        """Cria (ou recria) o aviso exibido quando a fila está vazia.

        O _render_queue destrói todos os filhos de queue_frame a cada
        atualização; repackar o placeholder antigo (já destruído) causava
        'TclError: bad window path name' ao abrir com fila vazia ou ao
        limpar a fila.
        """
        self.queue_placeholder = tk.Label(
            self.queue_frame, text="Adicione Content IDs à fila para iniciar o processamento.",
            bg=C_PANEL, fg=C_MUTED, font=(FONT, 9))
        self.queue_placeholder.pack(pady=24)

    def _render_queue(self, items):
        for child in self.queue_frame.winfo_children():
            child.destroy()

        if not self.queue_ids:
            self._create_queue_placeholder()
            self.lbl_selected_info.config(text="")
            return
        self.lbl_selected_info.config(
            text=f"{len(self.selected)} conteúdo(s) selecionado(s)." if self.selected else "")

        flow_active = getattr(self, "_flow_active", False)
        for item in items:
            self._render_queue_row(item, flow_active)

    def _render_queue_row(self, item, flow_active):
        cid = str(item.get("content_id", "")).strip()
        title = str(item.get("content_title") or "").strip()
        status = item.get("status")
        message = str(item.get("message", ""))
        progress = int(item.get("progress", 0) or 0)

        is_final = (
            is_final_success_status(status) or is_final_neutral_status(status)
            or is_final_error_status(status) or progress >= 100
        )
        item_running = cid in self.running_content_ids or is_running_status(status)
        disable_item = (not is_final) and (flow_active or item_running)

        row = tk.Frame(self.queue_frame, bg=C_PANEL2, highlightbackground=C_STROKE,
                       highlightthickness=1)
        row.pack(fill="x", padx=10, pady=4)
        row.columnconfigure(1, weight=1)

        # checkbox
        sel_var = tk.BooleanVar(value=cid in self.selected)
        chk = ttk.Checkbutton(row, style="Sub.TCheckbutton", variable=sel_var,
                              state="disabled" if flow_active else "normal")

        def on_toggle(checked=sel_var, _cid=cid):
            if checked.get():
                self.selected.add(_cid)
            else:
                self.selected.discard(_cid)
            self.refresh()
        chk.configure(command=lambda: on_toggle())
        chk.grid(row=0, column=0, rowspan=2, padx=(10, 6), pady=8)

        # id + título
        idf = tk.Frame(row, bg=C_PANEL2)
        idf.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        tk.Label(idf, text=cid, bg=C_PANEL2, fg=C_CYAN,
                 font=("Consolas", 10, "bold")).pack(side="left")
        if title and title.lower() != "nan":
            tk.Label(idf, text=f"  —  {title}", bg=C_PANEL2, fg=C_MUTED,
                     font=(FONT, 8)).pack(side="left")

        # barra + mensagem
        barf = tk.Frame(row, bg=C_PANEL2)
        barf.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(4, 8))
        barf.columnconfigure(0, weight=1)
        bar_canvas = tk.Canvas(barf, height=8, bg=C_PANEL2, highlightthickness=0)
        bar_canvas.grid(row=0, column=0, sticky="ew")
        tk.Label(barf, text=f"{progress}% - {message}", bg=C_PANEL2, fg=C_MUTED2,
                 font=(FONT, 8)).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self._draw_bar(bar_canvas, progress, bar_color(status))
        # desenha de novo com a largura real depois do layout
        row.update_idletasks()
        self._draw_bar(bar_canvas, progress, bar_color(status))

        # chip
        chip_kind = chip_class(status)
        bg, fg, bd = CHIP_STYLES[chip_kind]
        chipf = tk.Frame(row, bg=bg, highlightbackground=bd, highlightthickness=1)
        chipf.grid(row=0, column=2, rowspan=2, padx=(0, 8), pady=8)
        tk.Label(chipf, text=str(status), bg=bg, fg=fg,
                 font=(FONT, 8, "bold")).pack(padx=8, pady=3)

        # modo / idioma
        modef = tk.Frame(row, bg=C_PANEL2)
        modef.grid(row=0, column=3, rowspan=2, padx=(0, 8), pady=8)
        idioma = "Espanhol" if self._selected_language() == "es" else "Português"
        modo = "sem envio"
        if item_running and not is_final:
            tk.Label(modef, text="⏳ Processando", bg=C_PANEL2, fg="#93C5FD",
                     font=(FONT, 8, "bold")).pack(anchor="e")
        elif flow_active and not is_final:
            tk.Label(modef, text="Fila em execução", bg=C_PANEL2, fg="#93C5FD",
                     font=(FONT, 8, "bold")).pack(anchor="e")
        else:
            tk.Label(modef, text=idioma, bg=C_PANEL2, fg=C_MUTED2,
                     font=(FONT, 8)).pack(anchor="e")
            tk.Label(modef, text=modo, bg=C_PANEL2, fg=C_MUTED2,
                     font=(FONT, 8)).pack(anchor="e")

        # botões
        btns = tk.Frame(row, bg=C_PANEL2)
        btns.grid(row=0, column=4, rowspan=2, padx=(0, 10), pady=8)

        label = display_button_label(item, cid, self.running_content_ids)
        b_process = ttk.Button(btns, text=label, width=13,
                               style="Primary.TButton" if not is_final else "Sub.TButton")
        b_process.configure(command=lambda _cid=cid: self._on_item_process(_cid))
        b_process.pack(side="left", padx=(0, 4))
        if disable_item:
            b_process.config(state="disabled")

        # upload (arquivo já gerado, sem envio automático)
        is_generated = progress >= 80 and norm_status(status) in {"arquivo gerado", "gerado"}
        can_upload = is_generated and not is_final_success_status(status)
        b_upload = ttk.Button(btns, text="Upload", width=9,
                              style="Primary.TButton" if can_upload else "Sub.TButton")
        b_upload.configure(command=lambda _cid=cid: self._on_item_upload(_cid))
        b_upload.pack(side="left", padx=(0, 4))
        if not can_upload or flow_active:
            b_upload.config(state="disabled")

        b_remove = ttk.Button(btns, text="Remover", width=9, style="Sub.TButton")
        b_remove.configure(command=lambda _cid=cid: self._on_item_remove(_cid))
        b_remove.pack(side="left", padx=(0, 4))
        if flow_active and not is_final:
            b_remove.config(state="disabled")

        # abrir relatório
        report_path = str(item.get("report_file") or "").strip()
        has_report = bool(report_path) and Path(report_path).exists()
        final_vtt = BASE_DIR / "saida" / f"{cid}.vtt"
        has_vtt = final_vtt.exists()
        if has_report:
            b_rel = ttk.Button(btns, text="📄 Rel.", width=7, style="Sub.TButton")
            b_rel.configure(command=lambda: (
                open_path(Path(report_path).with_suffix(".txt"))
                or open_path(Path(report_path))))
            b_rel.pack(side="left", padx=(0, 4))
            if flow_active:
                b_rel.config(state="disabled")
        if has_vtt:
            b_vtt = ttk.Button(btns, text="▶ .vtt", width=7, style="Sub.TButton")
            b_vtt.configure(command=lambda: open_path(final_vtt))
            b_vtt.pack(side="left", padx=(0, 4))
            if flow_active:
                b_vtt.config(state="disabled")

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C_PANEL, highlightbackground=C_STROKE,
                       highlightthickness=1)
        bar.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        bar.columnconfigure(0, weight=1)
        self.lbl_status = tk.Label(bar, text="Pronto.", bg=C_PANEL, fg=C_MUTED,
                                   font=(FONT, 9), anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="ew", padx=12, pady=5)
        self.lbl_version = tk.Label(bar, text="SubNexus • interface local (Tkinter)",
                                    bg=C_PANEL, fg=C_MUTED2, font=(FONT, 8), anchor="e")
        self.lbl_version.grid(row=0, column=1, sticky="e", padx=12)


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
