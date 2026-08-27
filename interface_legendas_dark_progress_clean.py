# interface_legendas_dark_progress_clean.py
# -*- coding: utf-8 -*-
# Interface escura limpa com barras de progresso e sistema de fila.
# Funciona em modo real se existir vtt_auto_editor.py.
# Funciona em modo demonstração se não existir vtt_auto_editor.py.

from pathlib import Path
from datetime import datetime
import base64
import csv
import subprocess
import os
import sys
import time
import html
import json
import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
# Arquivos de log e controle (sem duplicatas)
STATUS_CSV = BASE_DIR / "logs" / "cms_fluxo_status.csv"
TIMING_CSV = BASE_DIR / "logs" / "cms_fluxo_tempos.csv"
LOG_FILE = BASE_DIR / "logs" / "interface_execucao.log"
RUN_LOG = LOG_FILE  # alias mantido para compatibilidade
STATUS_FILE = STATUS_CSV  # alias mantido para compatibilidade
FAVICON_FILE = BASE_DIR / "subnexus_favicon.png"
LOGO_FILE = BASE_DIR / "subnexus_logo.png"
EDITOR_SCRIPT = BASE_DIR / "vtt_auto_editor.py"
CONTENT_FILE = BASE_DIR / "content_ids_interface.txt"
LANGUAGE_OPTIONS = {
    "Português": "pt-br",
    "Espanhol": "es",
}
LANGUAGE_LABELS = {
    "pt-br": "Português",
    "es": "Espanhol",
}
PID_FILE = BASE_DIR / "logs" / "processo_atual.pid"
STOP_FILE = BASE_DIR / "logs" / "parar_fluxo.flag"
QUEUE_FILE = BASE_DIR / "logs" / "fila_interface.json"
CMS_PROFILE_DIR = BASE_DIR / "perfil_navegador_cms"
CMS_PROFILE_LOCK = CMS_PROFILE_DIR / "lockfile"
CMS_INSTANCE_FILE = BASE_DIR / "logs" / "cms_instance_state.json"

PASTAS = {
    "Originais": BASE_DIR / "entrada",
    "Finais": BASE_DIR / "saida",
    "Relatórios": BASE_DIR / "relatorios",
    "Logs": BASE_DIR / "logs",
    "Revisados": BASE_DIR / "Revisados",
}


def md(text: str):
    st.markdown(text, unsafe_allow_html=True)


def image_data_uri(path: Path) -> str:
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except Exception:
        return ""


def css():
    md("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {background: transparent !important;}

:root {
    --bg: #060A12;
    --panel: rgba(11, 17, 29, .82);
    --panel-soft: rgba(13, 20, 33, .66);
    --stroke: rgba(148, 163, 184, .14);
    --text: #F8FAFC;
    --muted: #A8B0BF;
    --muted2: #6B7280;
    --blue: #2563EB;
    --cyan: #38BDF8;
    --purple: #6366F1;
    --green: #22C55E;
    --yellow: #EAB308;
    --red: #EF4444;
}

.stApp {
    background:
        radial-gradient(circle at 100% 0%, rgba(37,99,235,.10), transparent 28%),
        linear-gradient(180deg, #060A12 0%, #070B13 48%, #05070D 100%);
    color: var(--text);
}

section[data-testid="stSidebar"] {
    background: #080D16;
    border-right: 1px solid rgba(148,163,184,.11);
}



.block-container {
    max-width: 1500px;
    padding-top: .9rem;
    padding-left: 2rem;
    padding-right: 2rem;
    padding-bottom: 2rem;
}

h1, h2, h3, p, span, label, div {
    color: var(--text) !important;
}

h2, h3 { letter-spacing: -.035em; }

h3 {
    font-size: 20px !important;
    margin-top: 0 !important;
    margin-bottom: .62rem !important;
}

textarea, input {
    background: rgba(8, 13, 23, .78) !important;
    color: var(--text) !important;
    border: 1px solid rgba(148,163,184,.17) !important;
    border-radius: 8px !important;
    box-shadow: none !important;
}

textarea:focus, input:focus {
    border-color: rgba(59,130,246,.56) !important;
    box-shadow: 0 0 0 1px rgba(59,130,246,.15) !important;
}

div[data-testid="stSelectbox"] * {
    caret-color: transparent !important;
    cursor: pointer !important;
    user-select: none !important;
}

div[data-testid="stSelectbox"] [role="combobox"] {
    caret-color: transparent !important;
    cursor: pointer !important;
    outline: none !important;
    background: rgba(8, 13, 23, .78) !important;
    border: 1px solid rgba(148,163,184,.17) !important;
    border-radius: 8px !important;
}

div[data-testid="stSelectbox"] div[data-baseweb="select"] input,
div[data-testid="stSelectbox"] [role="combobox"] input {
    caret-color: transparent !important;
    color: transparent !important;
    text-shadow: none !important;
    cursor: pointer !important;
    user-select: none !important;
}

div[data-testid="stSelectbox"] div[data-baseweb="select"] input::selection,
div[data-testid="stSelectbox"] [role="combobox"] input::selection {
    background: transparent !important;
    color: transparent !important;
}

div[data-testid="stSelectbox"] [aria-disabled="true"],
div[data-testid="stSelectbox"] [aria-disabled="true"] * {
    cursor: not-allowed !important;
}

div[data-testid="stRadio"] label {
    color: #DDE7F7 !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
    gap: 1rem;
}

div[data-testid="stButton"] button {
    min-height: 42px;
    background: rgba(15, 23, 42, .92);
    color: #DDE7F7 !important;
    border: 1px solid rgba(148,163,184,.22);
    border-radius: 8px;
    padding: .50rem .86rem;
    font-weight: 760;
    box-shadow: none;
}

div[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg, #2563EB, #1D4ED8);
    color: white !important;
    border: 1px solid rgba(147,197,253,.28);
    box-shadow: 0 10px 22px rgba(37,99,235,.16);
}

div[data-testid="stButton"] button:hover {
    border-color: rgba(125,211,252,.42);
    box-shadow: 0 8px 20px rgba(15,23,42,.22);
}

div[data-testid="stButton"] button:disabled {
    background: rgba(51,65,85,.36) !important;
    color: rgba(226,232,240,.42) !important;
    box-shadow: none;
}

div[class*="st-key-change_project"] button {
    background: linear-gradient(135deg, rgba(14,165,233,.96), rgba(124,58,237,.96)) !important;
    border: 1px solid rgba(125,211,252,.48) !important;
    box-shadow: 0 12px 26px rgba(14,165,233,.18) !important;
    color: #FFFFFF !important;
}

.project-state {
    color: #A8B0BF !important;
    font-size: 12px;
    margin: -2px 0 12px 1px;
}

.project-state strong {
    color: #E2E8F0 !important;
}

[data-testid="stHorizontalBlock"] { gap: 1.25rem; }

/* Faixa feita em código: sem imagem, sem fundo preto, sem borda preta */
.brand-band {
    width: 100%;
    min-height: 146px;
    border-radius: 11px;
    border: 1px solid rgba(59,130,246,.78);
    background:
        radial-gradient(circle at 93% 45%, rgba(107,33,168,.28), transparent 28%),
        linear-gradient(95deg, rgba(4,10,24,.98) 0%, rgba(5,10,22,.96) 54%, rgba(22,9,42,.96) 100%);
    display:flex;
    align-items:center;
    padding: 22px 72px;
    margin-bottom: 22px;
    position:relative;
    overflow:hidden;
    box-shadow:
        0 18px 42px rgba(0,0,0,.24),
        inset 0 1px 0 rgba(255,255,255,.05);
}

.brand-band::before {
    content:"";
    position:absolute;
    inset:0;
    border-radius:11px;
    pointer-events:none;
    background:
        linear-gradient(90deg, rgba(14,165,233,.18), transparent 18%, transparent 62%, rgba(126,34,206,.30)),
        linear-gradient(135deg, transparent 0 69%, rgba(59,130,246,.18) 69.2%, transparent 70.5%),
        linear-gradient(135deg, transparent 0 78%, rgba(126,34,206,.22) 78.2%, transparent 79.5%);
    opacity:.72;
}

.brand-band::after {
    content:"";
    position:absolute;
    right:34px;
    top:50%;
    width:5px;
    height:5px;
    border-radius:999px;
    background:#7C3AED;
    box-shadow:
        -270px -13px 0 rgba(79,70,229,.58),
        -30px 13px 0 rgba(124,58,237,.72);
    opacity:.92;
}

.brand-lockup {
    position:relative;
    z-index:2;
    display:flex;
    align-items:center;
    justify-content:center;
    height:100%;
}

.brand-main {
    display:flex;
    align-items:center;
    gap:20px;
}

.brand-icon {
    width:154px;
    height:104px;
    flex:0 0 auto;
    object-fit: contain;
    display:block;
    filter: drop-shadow(0 0 10px rgba(59,130,246,.16));
}

.brand-copy {
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:flex-start;
    transform: translateY(2px);
}

.brand-word {
    font-size: 50px;
    font-weight: 850;
    letter-spacing: -.045em;
    line-height: 1;
    text-shadow: 0 10px 26px rgba(0,0,0,.28);
}

.brand-word .sub {
    color:#F8FAFC !important;
}

.brand-word .nexus {
    background: linear-gradient(90deg, #22D3EE 0%, #3B82F6 48%, #8B5CF6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.brand-business {
    margin-top: 0px;
    margin-left: 0;
    color: #CBD5E1 !important;
    font-size: 16px;
    font-weight: 560;
    letter-spacing: .02em;
    opacity: .86;
}

/* Cabeçalho compacto, estilo H1/H2/H3 */
.app-header {
    padding: 0;
    margin: 0 0 18px 0;
    background: transparent;
    border: 0;
    box-shadow: none;
}

.app-kicker {
    color: #22D3EE !important;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: .30em;
    text-transform: uppercase;
    margin-bottom: 10px;
}

.app-title {
    font-size: 30px;
    font-weight: 930;
    letter-spacing: -.055em;
    line-height: 1.02;
}

.app-subtitle, .small, .status-text {
    font-size: 13px;
    color: #B7BBC7 !important;
}

.app-subtitle {
    margin-top: 10px;
}

.top-panel {
    min-height: 0;
    display:flex;
    flex-direction:column;
    justify-content:flex-start;
}

.metric-card {
    background: rgba(12,19,34,.68);
    border: 1px solid rgba(148,163,184,.12);
    border-radius: 8px;
    padding: 13px 14px;
    min-height: 88px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.022);
}

.metric-label {
    color: #A1A1AA !important;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .10em;
}

.metric-value {
    font-size: 27px;
    font-weight: 930;
    color: #F8FAFC !important;
    margin-top: 14px;
}

.progress-wrap {
    width: 100%;
    height: 10px;
    background: rgba(51,65,85,.74);
    border-radius: 999px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    border-radius: 999px;
    transition: width .35s ease;
}

.cid {
    font-family: Consolas, monospace;
    font-size: 13px;
    font-weight: 850;
    overflow-wrap: anywhere;
}

.cid-line {
    overflow-wrap: anywhere;
}

.content-title {
    color: #CBD5E1 !important;
    font-size: 12px;
    font-weight: 650;
    overflow-wrap: anywhere;
}

.chip {
    display:inline-flex;
    align-items:center;
    justify-content:center;
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 850;
    white-space: nowrap;
}

.ok { background: rgba(34,197,94,.13); color: #86EFAC !important; border: 1px solid rgba(34,197,94,.34); }
.run { background: rgba(59,130,246,.13); color: #93C5FD !important; border: 1px solid rgba(59,130,246,.34); }
.wait { background: rgba(234,179,8,.12); color: #FDE68A !important; border: 1px solid rgba(234,179,8,.34); }
.err { background: rgba(239,68,68,.13); color: #FCA5A5 !important; border: 1px solid rgba(239,68,68,.34); }

div[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid rgba(148,163,184,.12) !important;
    border-radius: 8px !important;
    background: rgba(12,19,34,.62) !important;
    padding: 0 !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.018) !important;
    margin-bottom: 10px !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 10px 12px !important;
}

.queue-progress { margin-top: 7px; }

.queue-message {
    color: #A1A1AA !important;
    font-size: 11px;
    margin-top: 5px;
}

div[class*="st-key-selecionar_"] {
    min-width: 24px !important;
}

div[class*="st-key-selecionar_"] label[data-baseweb="checkbox"] {
    width: 22px !important;
    min-width: 22px !important;
    overflow: hidden !important;
}

.queue-mode {
    color: #8A94A6 !important;
    font-size: 11px;
    text-align:right;
    line-height:1.35;
}

.mode-lock {
    display:flex;
    gap:16px;
    align-items:center;
    margin-top:8px;
}

.mode-option {
    display:inline-flex;
    align-items:center;
    gap:8px;
    color:#E2E8F0 !important;
    font-size:14px;
    font-weight:760;
}

.mode-dot {
    width:16px;
    height:16px;
    border-radius:999px;
    border:1px solid rgba(148,163,184,.32);
    background:rgba(15,23,42,.92);
    display:inline-flex;
    align-items:center;
    justify-content:center;
}

.mode-option.active .mode-dot {
    border-color:#FF5263;
    background:#FF5263;
}

.mode-option.active .mode-dot::after {
    content:"";
    width:5px;
    height:5px;
    border-radius:999px;
    background:#FFFFFF;
}

.mode-option.disabled {
    color:rgba(226,232,240,.42) !important;
    cursor:not-allowed;
}

.demo {
    background: rgba(234,179,8,.10);
    border: 1px solid rgba(234,179,8,.35);
    border-radius: 8px;
    padding: 12px;
    color: #FDE68A !important;
    margin-bottom: 16px;
}


/* Spinner e redução de piscada visual */
@keyframes spinSubNexus {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

.loading-dot {
    display:inline-block;
    width: 13px;
    height: 13px;
    border: 2px solid rgba(255,255,255,.35);
    border-top-color: #FFFFFF;
    border-radius: 999px;
    animation: spinSubNexus .75s linear infinite;
    vertical-align: -2px;
    margin-right: 7px;
}

.loading-inline {
    display:inline-flex;
    align-items:center;
    justify-content:center;
    color:#BAE6FD !important;
    font-size:12px;
    font-weight:700;
    gap:6px;
}

div[data-testid="stButton"] button[kind="secondary"]:disabled,
div[data-testid="stButton"] button:disabled {
    cursor: wait;
}

@media (max-width: 1150px) {
    .block-container {
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }
    .brand-band {
        min-height: 116px;
        padding: 16px 24px;
    }
    .brand-word {
        font-size: 32px;
    }
    .brand-icon {
        width:122px;
        height:82px;
    }
    .brand-business {
        font-size:14px;
    }
}
</style>
""")


def ensure_dirs():
    """Garante a existência das pastas usadas pela interface e pelo fluxo."""
    for folder in [
        BASE_DIR / "logs",
        BASE_DIR / "entrada",
        BASE_DIR / "saida",
        BASE_DIR / "relatorios",
        BASE_DIR / "Revisados",
    ]:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def mkdirs():
    """Atalho mantido para compatibilidade. Delega para ensure_dirs."""
    ensure_dirs()


def ids_from_text(t):
    """Extrai Content IDs de texto livre, removendo duplicatas e mantendo ordem."""
    seen: set = set()
    out = []
    for line in t.replace(",", "\n").replace(";", "\n").splitlines():
        x = line.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def saved_ids():
    if not CONTENT_FILE.exists():
        return []
    return [
        x.strip()
        for x in CONTENT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if x.strip()
    ]


def load_queue():
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def save_queue(ids):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    seen: set = set()
    unique = []
    for raw in ids:
        cid = str(raw).strip()
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(cid)
    QUEUE_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    st.session_state.queue_ids = unique
    selected = set(st.session_state.get("selected_content_ids", []))
    st.session_state.selected_content_ids = [cid for cid in unique if cid in selected]


def mark_item(content_id: str, status: str, progress: int, message: str = ""):
    """Atualiza um item da fila local para feedback visual imediato na interface."""
    try:
        cid = str(content_id).strip()
        if not cid:
            return False

        overrides = st.session_state.setdefault("item_overrides", {})
        overrides[cid] = {
            "content_id": cid,
            "status": status,
            "progress": int(progress),
            "message": message,
            "updated_at": time.time(),
        }

        return True
    except Exception:
        return False


def init_state():
    if "queue_ids" not in st.session_state:
        st.session_state.queue_ids = load_queue()
    if "last_ids" not in st.session_state:
        st.session_state.last_ids = saved_ids()
    if "demo_started" not in st.session_state:
        st.session_state.demo_started = False
    if "demo_start_time" not in st.session_state:
        st.session_state.demo_start_time = time.time()
    if "item_overrides" not in st.session_state:
        st.session_state.item_overrides = {}
    if "selected_content_ids" not in st.session_state:
        st.session_state.selected_content_ids = []


def add_to_queue(ids):
    queue = list(st.session_state.get("queue_ids", []))
    added = 0
    for cid in ids:
        if cid not in queue:
            queue.append(cid)
            added += 1
    save_queue(queue)
    return added


def remove_from_queue(cid):
    queue = [x for x in st.session_state.get("queue_ids", []) if x != cid]
    save_queue(queue)


def clear_queue():
    save_queue([])


def selected_ids_in_queue(queue_ids):
    selected = set(st.session_state.get("selected_content_ids", []))
    return [cid for cid in queue_ids if cid in selected]


def set_item_selected(content_id: str, selected: bool):
    cid = str(content_id).strip()
    current = list(st.session_state.get("selected_content_ids", []))
    if selected and cid not in current:
        current.append(cid)
    if not selected:
        current = [x for x in current if x != cid]
    queue = list(st.session_state.get("queue_ids", []))
    st.session_state.selected_content_ids = [x for x in current if x in queue]


def cmd(no_upload, language="pt-br", open_edited_file=False):
    c = ["py", str(EDITOR_SCRIPT), "--cms-flow", "--content-file", str(CONTENT_FILE), "--language", language]
    if no_upload:
        c.append("--no-upload")
    if open_edited_file:
        c.append("--open-edited-file")
    return c


def expected_cms_instance(language: str) -> str:
    return "SSLA" if language == "es" else "Portuguese"


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


def cms_profile_has_running_browser():
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { ($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') -and "
                "$_.CommandLine -like '*perfil_navegador_cms*' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId"
            ),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=4, shell=False)
        if result.returncode != 0:
            return None
        return bool(result.stdout.strip())
    except Exception:
        return None


def cms_manual_browser_open() -> bool:
    if not CMS_PROFILE_LOCK.exists():
        return False
    running = cms_profile_has_running_browser()
    if running is not None:
        return running
    try:
        return (time.time() - CMS_PROFILE_LOCK.stat().st_mtime) < 15
    except Exception:
        return True


def start_flow(content_ids, no_upload, language="pt-br", open_edited_file=False, upload_existing_file=False):
    ensure_dirs()
    content_ids = [str(x).strip() for x in content_ids if str(x).strip()]
    if not content_ids:
        return False, "Nenhum Content ID informado."

    if cms_manual_browser_open():
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
        "py",
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
            log.write("\n\n=== SubNexus start_flow ===\n")
            log.write("CMD: " + " ".join(cmd) + "\n")
            process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=log,
                stderr=log,
                shell=False,
            )
            PID_FILE.write_text(str(process.pid), encoding="utf-8")

        return True, f"Processamento iniciado para {len(content_ids)} conteúdo(s)."
    except Exception as exc:
        return False, f"Falha ao iniciar processamento: {exc}"


def request_stop_flow():
    ensure_dirs()
    try:
        STOP_FILE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        return True
    except Exception:
        return False


def open_cms_manual_session():
    ensure_dirs()
    cmd = ["py", str(EDITOR_SCRIPT), "--open-cms-home"]
    try:
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write("\n\n=== SubNexus open_cms_manual_session ===\n")
            log.write("CMD: " + " ".join(cmd) + "\n")
            subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=log,
                stderr=log,
                shell=False,
            )
        return True, "CMS aberto no navegador. Faça login/troque a instância manualmente."
    except Exception as exc:
        return False, f"Falha ao abrir o CMS: {exc}"


def read_status_csv():
    if not STATUS_CSV.exists():
        return pd.DataFrame()

    try:
        stat = STATUS_CSV.stat()
        cache = st.session_state.get("_status_csv_cache")
        if cache and cache.get("mtime") == stat.st_mtime and cache.get("size") == stat.st_size:
            return cache.get("df", pd.DataFrame())
    except Exception:
        stat = None

    rows = []
    old_fields = [
        "datetime",
        "content_id",
        "status",
        "original_file",
        "processed_temp_file",
        "final_upload_file",
        "report_file",
        "error",
    ]
    new_fields = [
        "datetime",
        "content_id",
        "content_title",
        "status",
        "original_file",
        "processed_temp_file",
        "final_upload_file",
        "report_file",
        "error",
    ]

    for enc in ["utf-8-sig", "utf-8", "latin1"]:
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
                    row = {field: values[i] if i < len(values) else "" for i, field in enumerate(fields)}
                    rows.append(row)
            break
        except UnicodeDecodeError:
            rows = []
            continue
        except Exception:
            rows = []
            continue

    if rows:
        df = pd.DataFrame(rows)
        if stat is not None:
            st.session_state["_status_csv_cache"] = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "df": df,
            }
        return df

    return pd.DataFrame()


def progress_from_status(s):
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


def stage_from_status(s, p):
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


def demo_items(ids):
    if not st.session_state.get("demo_started"):
        return [
            {
                "content_id": cid,
                "content_title": "",
                "status": "Pendente",
                "progress": 0,
                "message": "Aguardando processamento.",
            }
            for cid in ids
        ]

    elapsed = int(time.time() - st.session_state.get("demo_start_time", time.time()))

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

        status, progress, msg = chosen[1], chosen[2], chosen[3]

        items.append(
            {
                "content_id": cid,
                "content_title": "",
                "status": status,
                "progress": progress,
                "message": msg,
            }
        )

    return items


def _latest_vtt_by_content_id(ids):
    """
    Retorna o arquivo .vtt mais recente em saida/ para cada Content ID.

    Complexidade O(F + I×len(name)) onde F = arquivos na pasta, I = IDs desejados.
    Evita chamar stat() múltiplas vezes para o mesmo arquivo.
    """
    ids = [str(cid).strip() for cid in ids if str(cid).strip()]
    wanted = set(ids)
    latest: dict = {}
    latest_mtime: dict = {}

    output_dir = BASE_DIR / "saida"
    if not output_dir.exists():
        return latest

    for path in output_dir.glob("*.vtt"):
        name = path.name
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        for cid in wanted:
            if cid in name:
                if cid not in latest_mtime or mtime > latest_mtime[cid]:
                    latest[cid] = path
                    latest_mtime[cid] = mtime

    return latest


def _input_ids_seen(ids):
    """
    Retorna o conjunto de Content IDs que possuem arquivo na pasta entrada/.

    Complexidade O(F × I) onde F = arquivos na pasta, I = IDs desejados.
    Para pastas grandes, o gargalo é o OS; a estrutura Python é eficiente.
    """
    ids = [str(cid).strip() for cid in ids if str(cid).strip()]
    wanted = set(ids)
    seen: set = set()

    input_dir = BASE_DIR / "entrada"
    if not input_dir.exists():
        return seen

    for path in input_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name
        for cid in wanted:
            if cid in name:
                seen.add(cid)

    return seen


def file_status(ids):
    """
    Determina o status de cada item da fila baseado apenas no sistema de arquivos.

    Usa helpers pré-indexados (_latest_vtt_by_content_id e _input_ids_seen)
    para evitar múltiplos globs por item. Para IDs não cobertos pelos helpers
    (o que não deve ocorrer em operação normal), retorna Pendente por segurança.
    """
    d = {}
    latest_outputs = _latest_vtt_by_content_id(ids)
    seen_inputs = _input_ids_seen(ids)

    for cid in ids:
        if cid in latest_outputs:
            d[cid] = {
                "content_id": cid,
                "content_title": "",
                "status": "Arquivo gerado",
                "progress": 80,
                "message": "Arquivo pronto na pasta de saída.",
            }
        elif cid in seen_inputs:
            d[cid] = {
                "content_id": cid,
                "content_title": "",
                "status": "Baixando",
                "progress": 35,
                "message": "Original localizado. Aguardando arquivo final.",
            }
        else:
            d[cid] = {
                "content_id": cid,
                "content_title": "",
                "status": "Pendente",
                "progress": 0,
                "message": "Aguardando processamento.",
            }

    return d


def real_items_status(ids):
    base = file_status(ids)
    df = read_status_csv()

    if not df.empty and "content_id" in df.columns:
        # Agrupa por content_id e pega a última ocorrência de cada um,
        # evitando iterar linha a linha com iterrows() (lento em DataFrames grandes).
        has_error = "error" in df.columns
        has_title = "content_title" in df.columns

        df_indexed = df.copy()
        df_indexed["_cid"] = df_indexed["content_id"].astype(str).str.strip()
        # Mantém apenas o registro mais recente de cada content_id
        df_last = df_indexed.drop_duplicates(subset="_cid", keep="last")

        for _, row in df_last.iterrows():
            cid = str(row.get("_cid", "")).strip()
            if cid not in base:
                continue

            raw = str(row.get("status", "")).strip()
            err = str(row.get("error", "")).strip() if has_error else ""
            title = str(row.get("content_title", "")).strip() if has_title else ""
            if title and title.lower() != "nan":
                base[cid]["content_title"] = title

            if raw:
                p = progress_from_status(raw)
                stg = stage_from_status(raw, p)
                msg = err if err and err.lower() != "nan" else stg
                base[cid].update({"status": stg, "progress": p, "message": msg})

    overrides = st.session_state.get("item_overrides", {})
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

        current_progress = int(current.get("progress", 0) or 0)
        override_progress = int(override.get("progress", 0) or 0)
        if override_progress >= current_progress:
            current.update({
                "status": override.get("status", current.get("status")),
                "progress": override_progress,
                "message": override.get("message", current.get("message")),
            })

    return list(base.values())


def get_items(ids):
    if not EDITOR_SCRIPT.exists():
        return demo_items(ids)
    return real_items_status(ids)


def bar(percent, color):
    percent = max(0, min(100, int(percent)))
    return f"""
<div class="progress-wrap">
    <div class="progress-fill" style="width:{percent}%;background:{color};"></div>
</div>
"""


def chip_class(item):
    status = norm_status(item.get("status"))
    if status in FINAL_SUCCESS_STATUSES:
        return "ok"
    if status in {"arquivo gerado", "gerado"}:
        return "wait"
    if status in FINAL_NEUTRAL_STATUSES:
        return "wait"
    if status in FINAL_ERROR_STATUSES:
        return "err"
    if status in RUNNING_STATUSES:
        return "run"
    return "wait"


def color(item):
    status = norm_status(item.get("status"))
    if status in FINAL_SUCCESS_STATUSES:
        return "#22C55E"
    if status in {"arquivo gerado", "gerado"}:
        return "#EAB308"
    if status in FINAL_NEUTRAL_STATUSES:
        return "#EAB308"
    if status in FINAL_ERROR_STATUSES:
        return "#EF4444"
    if status in RUNNING_STATUSES:
        return "#3B82F6"
    return "#334155"


def metric(label, value):
    return f"""
<div class="metric-card">
    <div class="metric-label">{label}</div>
    <div class="metric-value">{value}</div>
</div>
"""


def summary(items):
    total = len(items)
    concl = sum(1 for x in items if norm_status(x.get("status")) == "enviado")
    sem_legenda = sum(1 for x in items if is_final_neutral_status(x.get("status")))
    erros = sum(1 for x in items if is_final_error_status(x.get("status")))
    gerados = sum(1 for x in items if norm_status(x.get("status")) in {"arquivo gerado", "gerado"})
    andam = sum(1 for x in items if is_running_status(x.get("status"))) + gerados
    pend = max(0, total - concl - sem_legenda - erros - andam)
    geral = int(((concl + sem_legenda + erros) / total) * 100) if total else 0
    return total, concl, andam, pend, erros, geral, sem_legenda


def _open_with_os(target: str) -> None:
    """Abre arquivo ou pasta com o programa padrão do sistema operacional."""
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def open_folder(p):
    p.mkdir(parents=True, exist_ok=True)
    _open_with_os(str(p))


def open_path(path: Path):
    if path.exists():
        _open_with_os(str(path))
        return True
    return False


def clean_exec():
    """
    Move arquivos de controle da execução atual para backups datados.
    Retorna a lista de arquivos que foram movidos com sucesso.
    """
    moved = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for p in [STATUS_CSV, TIMING_CSV, RUN_LOG, PID_FILE, STOP_FILE, CONTENT_FILE]:
        if p.exists():
            try:
                b = p.with_name(f"{p.stem}_backup_{stamp}{p.suffix}")
                p.rename(b)
                moved.append(b.name)
            except OSError:
                pass  # arquivo em uso ou sem permissão — ignora sem travar

    st.session_state.demo_started = False
    st.session_state.last_ids = []
    return moved


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_pid_running() -> bool:
    """Verifica se o processo de PID registrado ainda está ativo."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        if pid <= 0:
            return False

        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                creationflags=_CREATE_NO_WINDOW,
            )
            return str(pid) in result.stdout

        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def item_is_running(item) -> bool:
    status = str(item.get("status", "")).lower()
    progress = int(item.get("progress", 0) or 0)
    if "erro" in status:
        return False
    return 0 < progress < 100


def button_label(base: str, loading: bool) -> str:
    return f"⏳ {base}..." if loading else base


FINAL_SUCCESS_STATUSES = {"enviado"}
FINAL_NEUTRAL_STATUSES = {"sem legenda"}
FINAL_ERROR_STATUSES = {"erro", "erro cms"}
RUNNING_STATUSES = {
    "iniciando",
    "aguardando login",
    "aguardando cms carregar conteúdo",
    "baixando",
    "editando",
    "validando",
    "enviando",
    "processando",
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


def processable_queue_ids(queue_ids, items):
    by_id = {str(item.get("content_id", "")).strip(): item for item in items}
    targets = []
    for cid in queue_ids:
        item = by_id.get(str(cid).strip())
        if not item:
            targets.append(cid)
            continue

        progress = int(item.get("progress", 0) or 0)
        status = item.get("status")
        if progress == 0 and is_pending_status(status):
            targets.append(cid)
    return targets


def should_disable_item(item, cid) -> bool:
    status = item.get("status")
    progress = int(item.get("progress", 0) or 0)

    if (
        is_final_success_status(status)
        or is_final_neutral_status(status)
        or is_final_error_status(status)
        or progress >= 100
    ):
        return False

    if is_queue_loading():
        return True

    if is_item_loading(cid):
        return True

    return is_running_status(status)


def display_button_label(item, cid) -> str:
    status = norm_status(item.get("status"))
    progress = int(item.get("progress", 0) or 0)

    if status == "enviado":
        return "Reprocessar"
    if status in {"arquivo gerado", "gerado"}:
        return "Regerar"
    if is_final_neutral_status(status) or is_final_error_status(status) or progress >= 100:
        return "Reprocessar"
    if is_item_loading(cid) or is_running_status(status):
        return "⏳ Processando..."
    return "Processar"


def init_loading_state():
    st.session_state.setdefault("running_scope", None)       # None | "item" | "queue"
    st.session_state.setdefault("running_content_id", None)  # Content ID em execução individual
    st.session_state.setdefault("last_action_started", None)


def clear_loading_state():
    st.session_state["running_scope"] = None
    st.session_state["running_content_id"] = None
    st.session_state["last_action_started"] = None


def set_item_loading(content_id: str):
    st.session_state["running_scope"] = "item"
    st.session_state["running_content_id"] = content_id
    st.session_state["last_action_started"] = "item"


def set_queue_loading():
    st.session_state["running_scope"] = "queue"
    st.session_state["running_content_id"] = None
    st.session_state["last_action_started"] = "queue"


def is_queue_loading() -> bool:
    return st.session_state.get("running_scope") == "queue"


def is_item_loading(content_id: str) -> bool:
    return (
        st.session_state.get("running_scope") == "item"
        and st.session_state.get("running_content_id") == content_id
    )


def is_any_visual_loading() -> bool:
    return st.session_state.get("running_scope") in ("item", "queue")




def render_header():
    logo_src = image_data_uri(LOGO_FILE)
    md(f"""
<div class="brand-band">
    <div class="brand-lockup">
        <div class="brand-main">
            <img class="brand-icon" src="{logo_src}" alt="SubNexus"/>
            <div class="brand-copy">
                <div class="brand-word"><span class="sub">Sub</span><span class="nexus">Nexus</span></div>
                <div class="brand-business">Accenture Business</div>
            </div>
        </div>
    </div>
</div>

""")




def display_progress_value(item) -> int:
    status = norm_status(item.get("status"))
    progress = int(item.get("progress", 0) or 0)
    if status in {"arquivo gerado", "gerado"}:
        return min(progress, 80)
    return progress


def is_generated_file_ready(item) -> bool:
    status = norm_status(item.get("status"))
    progress = int(item.get("progress", 0) or 0)
    return progress >= 80 and status in {"arquivo gerado", "gerado"}


def upload_button_enabled(item, no_upload: bool) -> bool:
    return bool(no_upload) and is_generated_file_ready(item)


def render_queue_item(item, no_upload, language):
    cid = item["content_id"]
    title = str(item.get("content_title") or "").strip()
    status = item.get("status")
    message = str(item.get("message", ""))
    modo = "sem envio" if no_upload else "com envio"
    idioma_label = "Espanhol" if language == "es" else "Português"

    queue_loading = is_queue_loading()
    shown_progress = display_progress_value(item)

    is_uploaded = norm_status(status) == "enviado"
    is_neutral_final = is_final_neutral_status(status)
    is_error_final = is_final_error_status(status)
    is_generated = is_generated_file_ready(item)
    is_final = is_uploaded or is_neutral_final or is_error_final

    this_loading = (not is_final and not is_generated) and (is_item_loading(cid) or is_running_status(status))
    disable_this = (not is_final and not is_generated) and should_disable_item(item, cid)

    can_upload = upload_button_enabled(item, no_upload)
    upload_disabled = (not can_upload) or queue_loading or this_loading

    with st.container(border=True):
        c0, c1, c2, c3, c4 = st.columns([.45, 5.15, 1.1, 1.15, 2.9], vertical_alignment="center")

        with c0:
            selected = cid in set(st.session_state.get("selected_content_ids", []))
            checked = st.checkbox(
                "Selecionar",
                value=selected,
                key=f"selecionar_{cid}",
                label_visibility="collapsed",
                disabled=queue_loading,
            )
            if checked != selected:
                set_item_selected(cid, checked)
                st.rerun()

        with c1:
            if title and title.lower() != "nan":
                md(
                    f'<div class="cid-line"><span class="cid">{html.escape(cid)}</span>'
                    f'<span class="content-title"> — {html.escape(title)}</span></div>'
                )
            else:
                md(f'<div class="cid">{html.escape(cid)}</div>')
            md(f'<div class="queue-progress">{bar(shown_progress, color(item))}</div>')
            md(f'<div class="queue-message">{shown_progress}% - {html.escape(message)}</div>')

        with c2:
            md(f'<span class="chip {chip_class(item)}">{html.escape(item["status"])}</span>')

        with c3:
            if this_loading:
                md('<div class="loading-inline"><span class="loading-dot"></span>Processando</div>')
            elif queue_loading and not is_final:
                md('<div class="loading-inline"><span class="loading-dot"></span>Fila</div>')
            else:
                md(f'<div class="queue-mode">{html.escape(idioma_label)}<br>{html.escape(modo)}</div>')

        with c4:
            b1, b2, b3 = st.columns([1.5, 1, 1], gap="small")

            with b1:
                label = display_button_label(item, cid)
                if st.button(label, key=f"processar_{cid}", type="primary", use_container_width=True, disabled=disable_this):
                    mark_item(cid, "Iniciando", 5, "Abrindo navegador e iniciando processamento...")
                    set_item_loading(cid)
                    ok, msg = start_flow(
                        [cid],
                        no_upload,
                        language=language,
                        open_edited_file=(no_upload is True),
                    )
                    if ok:
                        st.toast(msg, icon="▶️")
                    else:
                        clear_loading_state()
                        mark_item(cid, "Erro", 100, f"Falha ao iniciar processamento: {msg}")
                        st.error(msg)
                    st.rerun()

            with b2:
                upload_button_type = "primary" if can_upload and not upload_disabled else "secondary"
                if st.button("Upload", key=f"upload_{cid}", type=upload_button_type, use_container_width=True, disabled=upload_disabled):
                    mark_item(cid, "Enviando", 90, "Enviando arquivo já gerado em saida/...")
                    set_item_loading(cid)
                    ok, msg = start_flow(
                        [cid],
                        False,
                        language=language,
                        open_edited_file=False,
                        upload_existing_file=True,
                    )
                    if ok:
                        st.toast("Upload iniciado.", icon="⬆️")
                    else:
                        clear_loading_state()
                        mark_item(cid, "Erro", 100, f"Falha ao iniciar upload: {msg}")
                        st.error(msg)
                    st.rerun()

            with b3:
                if st.button("Remover", key=f"remover_{cid}", use_container_width=True, disabled=(queue_loading and not is_final)):
                    remove_from_queue(cid)
                    st.rerun()


def sorted_queue_items(items):
    """
    Ordena itens da fila por prioridade visual:
    0 - Em andamento (progresso entre 1% e 99%)
    1 - Pendentes / sem progresso
    2 - Erros
    3 - Concluídos (incluindo sem legenda)

    Usa as funções helper de status para consistência com o restante da interface.
    """
    def order(item):
        status = item.get("status")
        progress = int(item.get("progress", 0) or 0)
        if is_running_status(status) or (0 < progress < 100):
            return 0
        if is_final_error_status(status):
            return 2
        if is_final_success_status(status) or is_final_neutral_status(status) or progress >= 100:
            return 3
        return 1  # pendente

    return sorted(items, key=order)


def sync_loading_state_with_queue(items):
    """Limpa o estado visual de loading quando o item/fila já finalizou."""
    scope = st.session_state.get("running_scope")
    if not scope:
        return

    def final(item):
        status = item.get("status")
        return (
            is_final_success_status(status)
            or is_final_neutral_status(status)
            or is_final_error_status(status)
            or int(item.get("progress", 0) or 0) >= 100
        )

    if scope == "item":
        cid = st.session_state.get("running_content_id")
        for item in items:
            if str(item.get("content_id")) == str(cid) and final(item):
                clear_loading_state()
                return
            if str(item.get("content_id")) == str(cid) and is_running_status(item.get("status")) and not is_pid_running():
                mark_item(cid, "Erro", 100, "Processo encerrado antes de registrar status final. Tente novamente.")
                clear_loading_state()
                return

    if scope == "queue" and items and all(final(item) for item in items):
        clear_loading_state()
        return

    if scope == "queue" and items and not is_pid_running():
        for item in items:
            if is_running_status(item.get("status")):
                mark_item(item.get("content_id"), "Erro", 100, "Processo encerrado antes de registrar status final. Tente novamente.")
        clear_loading_state()


def render_queue_workspace(auto_refresh: bool, refresh_secs: int, no_upload: bool, selected_language: str):
    run_every = f"{int(refresh_secs)}s" if auto_refresh else None

    @st.fragment(run_every=run_every)
    def queue_fragment():
        queue_ids = list(st.session_state.get("queue_ids", []))
        selected_queue_ids = selected_ids_in_queue(queue_ids)
        items = sorted_queue_items(get_items(queue_ids))
        sync_loading_state_with_queue(items)
        items = sorted_queue_items(get_items(queue_ids))
        total, concl, andam, pend, erros, geral, sem_legenda = summary(items)
        queue_loading = is_queue_loading()

        top_left, top_right = st.columns([1, 1], vertical_alignment="top")

        with top_left:
            md('<div class="top-panel">')
            st.subheader("Adicionar à fila")
            if st.session_state.pop("clear_content_ids_input", False):
                st.session_state["content_ids_input"] = ""
            txt = st.text_area(
                "Códigos de conteúdo",
                key="content_ids_input",
                height=150,
                placeholder="Cole um ou mais Content IDs, um por linha.",
            )
            detected_ids = ids_from_text(txt)
            md(f'<div class="small">{len(detected_ids)} conteúdo(s) detectado(s)</div>')
            md('</div>')

        with top_right:
            md('<div class="top-panel">')
            st.subheader("Progresso geral da fila")
            md(bar(geral, "#3B82F6" if erros == 0 else "#EAB308"))
            md(
                f'<div class="status-text">{geral}% - {concl} concluído(s), '
                f'{andam} em andamento, {pend} pendente(s), {erros} erro(s)</div>'
            )
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                md(metric("Total", total))
            with m2:
                md(metric("Concluídos", concl))
            with m3:
                md(metric("Pendentes", pend))
            with m4:
                md(metric("Erros", erros))
            md('</div>')

        selected_queue_ids = selected_ids_in_queue(queue_ids)
        processable_ids = processable_queue_ids(queue_ids, items)
        if selected_queue_ids:
            selected_set = set(selected_queue_ids)
            process_targets = [cid for cid in processable_ids if cid in selected_set]
        else:
            process_targets = processable_ids
        process_label = "Processar selecionados" if selected_queue_ids else "Processar fila inteira"
        processing_label = "Processando selecionados" if selected_queue_ids else "Processando fila"
        remove_label = "Remover selecionados" if selected_queue_ids else "Remover concluídos"

        action_left, action_mid, action_right, action_clear = st.columns([1.25, 1.05, .95, .75], vertical_alignment="center")
        with action_left:
            if st.button("Adicionar à fila", type="primary", use_container_width=True, disabled=queue_loading):
                detected_ids = ids_from_text(st.session_state.get("content_ids_input", ""))
                added = add_to_queue(detected_ids)
                if added:
                    st.toast(f"{added} conteúdo(s) adicionado(s) à fila.")
                    st.session_state["clear_content_ids_input"] = True
                    st.rerun(scope="fragment")
                else:
                    st.info("Nenhum conteúdo novo para adicionar.")
        with action_mid:
            if st.button(button_label(processing_label, queue_loading) if queue_loading else process_label, type="primary", disabled=(not process_targets or queue_loading), use_container_width=True):
                set_queue_loading()
                for _cid in process_targets:
                    mark_item(_cid, "Iniciando", 5, "Fila iniciada. Aguardando processamento...")
                ok, msg = start_flow(process_targets, no_upload, language=selected_language, open_edited_file=False)
                if ok:
                    st.toast(msg)
                    st.rerun(scope="fragment")
                else:
                    clear_loading_state()
                    st.error(msg)
        with action_right:
            if st.button(remove_label, disabled=(not queue_ids or queue_loading), use_container_width=True):
                if selected_queue_ids:
                    selected_set = set(selected_queue_ids)
                    remaining = [cid for cid in queue_ids if cid not in selected_set]
                else:
                    remaining = [item["content_id"] for item in items if item["progress"] < 100 or "erro" in item["status"].lower()]
                save_queue(remaining)
                st.rerun(scope="fragment")
        with action_clear:
            if st.button("Limpar fila", disabled=(not queue_ids or queue_loading), use_container_width=True):
                clear_queue()
                st.rerun(scope="fragment")

        queue_ids = list(st.session_state.get("queue_ids", []))
        selected_queue_ids = selected_ids_in_queue(queue_ids)
        items = sorted_queue_items(get_items(queue_ids))

        st.subheader("Fila de conteúdos")
        if selected_queue_ids:
            md(f'<div class="small">{len(selected_queue_ids)} conteúdo(s) selecionado(s).</div>')

        if not queue_ids:
            st.info("Adicione Content IDs à fila para iniciar o processamento.")
        else:
            for item in items:
                render_queue_item(item, no_upload, selected_language)

    queue_fragment()


def main():
    mkdirs()
    init_state()
    init_loading_state()

    st.set_page_config(
        page_title="SubNexus",
        layout="wide",
        page_icon=str(FAVICON_FILE),
        initial_sidebar_state="expanded",
    )
    css()

    demo_mode = not EDITOR_SCRIPT.exists()

    render_header()

    if demo_mode:
        md("""
<div class="demo">
Modo demonstração ativo. A interface está simulando os status porque o script principal não está nesta pasta.
</div>
""")

    with st.sidebar:
        st.subheader("Ações rápidas")

        sidebar_language_name = st.session_state.get("language_name", "Português")
        sidebar_language = LANGUAGE_OPTIONS.get(sidebar_language_name, "pt-br")
        sidebar_project = expected_cms_instance(sidebar_language)
        instance_state = read_cms_instance_state()
        confirmed_project = instance_state.get("instance") or "Não confirmado"

        if st.button("Change Project", key="change_project", use_container_width=True):
            ok, msg = open_cms_manual_session()
            if not ok:
                st.error(msg)

        if st.button("Confirmar instância atual", key="confirm_cms_instance", use_container_width=True):
            write_cms_instance_state(sidebar_project, sidebar_language)
            confirmed_project = sidebar_project

        md(f'<div class="project-state">CMS instance: <strong>{html.escape(confirmed_project)}</strong></div>')
        if confirmed_project != "Não confirmado" and confirmed_project != sidebar_project:
            st.warning(f"Idioma selecionado espera {sidebar_project}. Confirme a troca no CMS antes de processar.")
        if cms_manual_browser_open():
            st.caption("Janela do Change Project aberta. Feche o Chrome antes de processar a fila.")

        if st.button("Abrir pasta de saída", use_container_width=True):
            open_folder(PASTAS["Finais"])

        if st.button("Abrir originais", use_container_width=True):
            open_folder(PASTAS["Originais"])

        if st.button("Abrir relatórios", use_container_width=True):
            open_folder(PASTAS["Relatórios"])

        if st.button("Abrir tempos", use_container_width=True):
            if not open_path(TIMING_CSV):
                st.info("O arquivo de tempos será criado no próximo processamento.")

        st.divider()

        auto = st.checkbox("Atualizar automaticamente", value=True)
        secs = st.selectbox("Intervalo", [2, 3, 5, 10], index=1)

        if st.button("Atualizar agora", use_container_width=True):
            st.rerun()

        if auto:
            st.caption("Auto-refresh ativo para acompanhar o processamento.")

        if st.button("Parar fluxo", use_container_width=True):
            if request_stop_flow():
                st.warning("Parada solicitada. O item atual pode terminar; os próximos não serão iniciados.")
            else:
                st.error("Não foi possível solicitar a parada.")

        st.divider()

        if st.button("Limpar execução atual", use_container_width=True):
            backups = clean_exec()
            if backups:
                st.success("Execução limpa.")
            else:
                st.info("Nada para limpar.")

        if st.button("Limpar fila", use_container_width=True):
            clear_queue()
            st.rerun()

    mode_options = ["Manual", "Automático"]
    legacy_mode = st.session_state.get("execution_mode", "Apenas gerar arquivos")
    if legacy_mode == "Apenas gerar arquivos":
        legacy_mode = "Manual"
    if legacy_mode == "Gerar e enviar ao CMS":
        legacy_mode = "Automático"
    if legacy_mode not in mode_options:
        legacy_mode = "Manual"
    st.session_state["execution_mode"] = "Manual"

    current_mode = st.session_state.get("execution_mode", "Manual")
    no_upload = True
    current_lang_name = st.session_state.get("language_name", "Português")
    selected_language = LANGUAGE_OPTIONS.get(current_lang_name, "pt-br")

    queue_ids = list(st.session_state.get("queue_ids", []))
    selected_queue_ids = selected_ids_in_queue(queue_ids)
    items = sorted_queue_items(get_items(queue_ids))
    sync_loading_state_with_queue(items)
    items = sorted_queue_items(get_items(queue_ids))
    total, concl, andam, pend, erros, geral, sem_legenda = summary(items)
    queue_loading = is_queue_loading()

    st.write("")
    mode_col, lang_col = st.columns([1.25, 1], vertical_alignment="top")

    with mode_col:
        st.subheader("Modo de execução")
        md("""
<div class="small">Selecione:</div>
<div class="mode-lock">
    <span class="mode-option active"><span class="mode-dot"></span>Manual</span>
    <span class="mode-option disabled"><span class="mode-dot"></span>Automático</span>
</div>
""")
        no_upload = True

    with lang_col:
        st.subheader("Idioma da legenda")
        queue_has_items = bool(st.session_state.get("queue_ids", []))
        lang_names = list(LANGUAGE_OPTIONS.keys())
        current_lang_name = st.session_state.get("language_name", "Português")
        if current_lang_name not in lang_names:
            current_lang_name = "Português"
        selected_lang_name = st.selectbox(
            "Idioma",
            lang_names,
            index=lang_names.index(current_lang_name),
            disabled=queue_has_items,
            key="language_name",
            help="O idioma vale para a fila inteira. Para alterar, limpe ou conclua a fila atual.",
        )
        selected_language = LANGUAGE_OPTIONS[selected_lang_name]
        if queue_has_items:
            md('<div class="small">Bloqueado durante a fila atual.</div>')
        md(f'<div class="small">CMS: {"Portuguese" if selected_language == "pt-br" else "Spanish"}</div>')

    render_queue_workspace(auto, int(secs), no_upload, selected_language)
    return

if __name__ == "__main__":
    main()
