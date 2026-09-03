# -*- coding: utf-8 -*-
"""
SubNexus - Benchmark automático do processo real no CMS

OBJETIVO
--------
Medir o processo sem colocar o CMS sob controle do Playwright.

O Chrome é aberto como no Change Project:
    chrome.exe
    --user-data-dir=perfil_navegador_cms
    --profile-directory=Default
    --new-window
    --start-maximized

A medição é automática.

O observador usa:
    1. Windows UI Automation (pywinauto) para observar a interface do Chrome;
    2. monitoramento da pasta Downloads para detectar o arquivo baixado;
    3. monitoramento das janelas/guias para detectar a abertura do player;
    4. leitura periódica dos textos acessíveis da janela do Chrome.

IMPORTANTE
----------
Esta versão NÃO clica em nada e NÃO altera o navegador.
Ela somente observa.

Como a estrutura acessível do CMS pode variar, o script registra os eventos
que conseguir identificar e também salva um log bruto para refinarmos os
detectores depois do primeiro teste.

Dependência:
    pip install pywinauto psutil

Opcional:
    pip install pyperclip
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv
import os
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from pywinauto import Desktop
except ImportError:
    print("Dependência ausente: pywinauto")
    print("Instale com: pip install pywinauto")
    input("Pressione ENTER para fechar...")
    raise SystemExit(1)

try:
    import psutil
except ImportError:
    print("Dependência ausente: psutil")
    print("Instale com: pip install psutil")
    input("Pressione ENTER para fechar...")
    raise SystemExit(1)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CMS_PROFILE_DIR = BASE_DIR / "perfil_navegador_cms"
CMS_URL = "https://dtv-cms-ui.tbxnet.com/"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RAW_LOG = LOG_DIR / "benchmark_observacao.log"
RESULTS_CSV = LOG_DIR / "benchmark_automatico.csv"

DOWNLOADS_DIR = Path.home() / "Downloads"

POLL_INTERVAL = 0.25

# Textos que podem aparecer no CMS durante o processo.
# A lista é deliberadamente ampla; os eventos serão refinados após o teste.
EVENT_PATTERNS = {
    "editar": [
        r"\bEditar\b",
        r"\bEdit\b",
    ],
    "download": [
        r"\bDownload\b",
    ],
    "upload": [
        r"\bUpload\b",
    ],
    "play": [
        r"\bPlay\b",
    ],
    "validate_media": [
        r"Validate Media",
    ],
    "approve": [
        r"\bApprove\b",
    ],
    "validate": [
        r"\bValidate\b",
    ],
}

PLAYER_PATTERNS = [
    r"\bplayback\b",
    r"\bplayer\b",
    r"\bvideo\b",
]


# ============================================================
# UTILITÁRIOS
# ============================================================

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def perf():
    return time.perf_counter()


def log(message):
    line = f"[{ts()}] {message}"
    print(line, flush=True)

    try:
        with RAW_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def human(seconds):
    if seconds is None:
        return "--:--.--"

    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ============================================================
# CHROME REAL — MESMO MODELO DO CHANGE PROJECT
# ============================================================

def find_chrome():
    candidates = []

    found = shutil.which("chrome.exe")
    if found:
        candidates.append(Path(found))

    for env_name in (
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "LOCALAPPDATA",
    ):
        base = os.environ.get(env_name)

        if base:
            candidates.append(
                Path(
                    base,
                    "Google",
                    "Chrome",
                    "Application",
                    "chrome.exe",
                )
            )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def open_chrome():
    chrome = find_chrome()

    if chrome is None:
        raise RuntimeError(
            "Google Chrome não foi encontrado."
        )

    CMS_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        str(chrome),
        f"--user-data-dir={CMS_PROFILE_DIR}",
        "--profile-directory=Default",
        "--new-window",
        "--start-maximized",
        "--disable-background-mode",
        CMS_URL,
    ]

    log(f"Chrome: {chrome}")
    log(f"Perfil: {CMS_PROFILE_DIR}")
    log("Abrindo Chrome sem Playwright e sem CDP...")

    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        shell=False,
    )

    log(f"Chrome iniciado | PID={process.pid}")

    return process


# ============================================================
# DOWNLOAD OBSERVER
# ============================================================

def download_snapshot():
    result = {}

    if not DOWNLOADS_DIR.exists():
        return result

    try:
        for item in DOWNLOADS_DIR.iterdir():
            if item.is_file():
                try:
                    stat = item.stat()
                    result[str(item)] = (
                        stat.st_size,
                        stat.st_mtime_ns,
                    )
                except OSError:
                    pass
    except OSError:
        pass

    return result


def find_completed_download(before, started_at):
    """
    Detecta arquivo novo/modificado na pasta Downloads.

    Arquivos .crdownload são ignorados até que o Chrome os converta
    em arquivo final.
    """

    current = download_snapshot()

    candidates = []

    for path_text, metadata in current.items():
        path = Path(path_text)

        if path.name.endswith(".crdownload"):
            continue

        if path.name.endswith(".tmp"):
            continue

        old = before.get(path_text)

        # Arquivo novo
        if old is None:
            try:
                if path.stat().st_mtime >= started_at:
                    candidates.append(path)
            except OSError:
                pass

        # Arquivo existente que mudou
        elif metadata != old:
            candidates.append(path)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    return candidates[0]


# ============================================================
# WINDOWS UI AUTOMATION
# ============================================================

def chrome_windows():
    """
    Obtém as janelas visíveis do Chrome através do Windows UI Automation.
    """

    try:
        windows = Desktop(backend="uia").windows(
            title_re=r".*",
            visible_only=True,
        )
    except Exception:
        return []

    result = []

    for window in windows:
        try:
            process_id = window.process_id()

            if not process_id:
                continue

            process = psutil.Process(process_id)

            if process.name().lower() == "chrome.exe":
                result.append(window)

        except Exception:
            continue

    return result


def get_window_text(window):
    """
    Extrai texto acessível da janela.

    Não interage com a página.
    """

    chunks = []

    try:
        title = normalize(window.window_text())

        if title:
            chunks.append(title)
    except Exception:
        pass

    try:
        descendants = window.descendants(
            control_type="Text"
        )

        for control in descendants:
            try:
                text = normalize(control.window_text())

                if text:
                    chunks.append(text)
            except Exception:
                pass

    except Exception:
        pass

    # Também tentamos controles gerais, pois alguns elementos web do
    # Chrome aparecem com outros tipos de UIA.
    try:
        descendants = window.descendants()

        for control in descendants:
            try:
                text = normalize(control.window_text())

                if text:
                    chunks.append(text)
            except Exception:
                pass

    except Exception:
        pass

    # Remove duplicatas mantendo a ordem.
    seen = set()
    result = []

    for item in chunks:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def contains_pattern(text, patterns):
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue

    return False


# ============================================================
# OBSERVADOR
# ============================================================

class Observer:
    def __init__(self):
        self.running = False
        self.thread = None

        self.started_at = None
        self.finished_at = None

        self.download_before = {}
        self.events = {}

        self.last_signature = ""
        self.last_window_count = 0

        self.raw_text_dumped = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            name="CMSBenchmarkObserver",
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

    def mark(self, name):
        if name in self.events:
            return

        moment = perf()
        self.events[name] = moment

        elapsed = (
            moment - self.started_at
            if self.started_at is not None
            else None
        )

        log(
            f"EVENTO: {name.upper()} | "
            f"desde início={human(elapsed)}"
        )

    def _run(self):
        while self.running:

            try:
                self.scan()
            except Exception as exc:
                log(
                    f"Observer warning: "
                    f"{type(exc).__name__}: {exc}"
                )

            time.sleep(POLL_INTERVAL)

    def scan(self):
        windows = chrome_windows()

        if len(windows) != self.last_window_count:
            log(
                f"Chrome windows: "
                f"{self.last_window_count} -> {len(windows)}"
            )
            self.last_window_count = len(windows)

        combined = []

        for window in windows:
            texts = get_window_text(window)

            for text in texts:
                combined.append(text)

        full_text = normalize(" | ".join(combined))

        # Loga mudanças significativas da árvore acessível.
        signature = full_text[:10000]

        if signature != self.last_signature:
            self.last_signature = signature

            # Durante o primeiro teste queremos enxergar o que o CMS
            # realmente expõe para o Windows UI Automation.
            log(
                "UIA SNAPSHOT: "
                + full_text[:3000]
            )

        if self.started_at is None:
            return

        # ----------------------------------------------------
        # EVENTOS DE UI
        # ----------------------------------------------------

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["editar"],
        ):
            self.mark("editar")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["download"],
        ):
            self.mark("download_ui")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["upload"],
        ):
            self.mark("upload_ui")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["play"],
        ):
            self.mark("play")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["validate_media"],
        ):
            self.mark("validate_media")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["approve"],
        ):
            self.mark("approve")

        if contains_pattern(
            full_text,
            EVENT_PATTERNS["validate"],
        ):
            self.mark("validate")

        # ----------------------------------------------------
        # DOWNLOAD REAL
        # ----------------------------------------------------

        downloaded = find_completed_download(
            self.download_before,
            time.time() - 1,
        )

        if downloaded:
            self.mark("download_completed")
            log(
                f"DOWNLOAD REAL DETECTADO: "
                f"{downloaded.name}"
            )

        # ----------------------------------------------------
        # NOVA JANELA / PLAYER
        # ----------------------------------------------------

        if len(windows) > 1:
            self.mark("nova_janela_chrome")

    def begin(self):
        self.started_at = perf()
        self.download_before = download_snapshot()
        log(">>> MEDIÇÃO INICIADA <<<")

    def finish(self):
        self.finished_at = perf()

        if self.started_at is None:
            return

        total = self.finished_at - self.started_at

        log(
            f">>> MEDIÇÃO ENCERRADA | "
            f"TOTAL={human(total)} <<<"
        )


# ============================================================
# RESULTADO
# ============================================================

def save_csv(content_id, observer):
    if observer.started_at is None:
        return

    total = (
        observer.finished_at - observer.started_at
        if observer.finished_at
        else None
    )

    fields = [
        "data",
        "content_id",
        "tempo_total",
        "editar",
        "download_ui",
        "download_completed",
        "upload_ui",
        "play",
        "nova_janela_chrome",
        "validate_media",
        "approve",
        "validate",
    ]

    row = {
        "data": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "content_id": content_id,
        "tempo_total": total,
    }

    for key in fields[3:]:
        if (
            key in observer.events
            and observer.started_at is not None
        ):
            row[key] = (
                observer.events[key]
                - observer.started_at
            )
        else:
            row[key] = None

    file_exists = RESULTS_CSV.exists()

    with RESULTS_CSV.open(
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        if not file_exists:
            writer.writeheader()

        formatted = {}

        for key, value in row.items():
            if isinstance(value, float):
                formatted[key] = f"{value:.3f}"
            else:
                formatted[key] = value

        writer.writerow(formatted)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 78)
    print("SUBNEXUS — BENCHMARK AUTOMÁTICO")
    print("=" * 78)
    print()
    print("Chrome: REAL")
    print("Playwright: NÃO")
    print("CDP: NÃO")
    print("Cliques automáticos: NÃO")
    print("Monitoramento: WINDOWS UI AUTOMATION + DOWNLOADS")
    print()

    content_id = input(
        "Content ID para identificação: "
    ).strip()

    if not content_id:
        print("Content ID não informado.")
        input("Pressione ENTER para fechar...")
        return

    print()
    print("Feche completamente o Chrome antes de continuar.")
    print()

    input("Pressione ENTER quando o Chrome estiver fechado...")

    try:
        open_chrome()
    except Exception as exc:
        print()
        print(
            f"Erro ao abrir o Chrome: "
            f"{type(exc).__name__}: {exc}"
        )
        input("Pressione ENTER para fechar...")
        return

    print()
    print("Chrome aberto.")
    print("Aguardando a interface do CMS...")
    time.sleep(3)

    observer = Observer()
    observer.start()

    print()
    print("=" * 78)
    print("OBSERVADOR ATIVO")
    print("=" * 78)
    print()
    print(
        "Quando o CMS estiver pronto para começar, "
        "pressione ENTER UMA ÚNICA VEZ."
    )
    print()
    print(
        "Depois disso, execute TODO o processo normalmente."
    )
    print(
        "Não será necessário pressionar ENTER em nenhuma etapa."
    )
    print()
    print(
        "Ao terminar o processo completo, volte ao CMD e "
        "pressione ENTER para encerrar a coleta."
    )
    print()

    input("ENTER → INICIAR MEDIÇÃO")

    observer.begin()

    print()
    print("MEDIÇÃO EM ANDAMENTO.")
    print("Execute o processo normalmente.")
    print()

    input("ENTER → ENCERRAR MEDIÇÃO")

    observer.finish()
    observer.stop()

    save_csv(content_id, observer)

    print()
    print("=" * 78)
    print("RESULTADO")
    print("=" * 78)

    if observer.started_at and observer.finished_at:
        print(
            f"Tempo total: "
            f"{human(observer.finished_at - observer.started_at)}"
        )

    print()
    print("EVENTOS DETECTADOS")
    print("-" * 78)

    for name, moment in observer.events.items():
        elapsed = (
            moment - observer.started_at
            if observer.started_at
            else None
        )

        print(
            f"{name:<25} "
            f"{human(elapsed)}"
        )

    print()
    print(f"CSV: {RESULTS_CSV}")
    print(f"Log: {RAW_LOG}")
    print()
    print(
        "O Chrome permanece aberto."
    )

    input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 78)
        print("ERRO NÃO TRATADO")
        print("=" * 78)
        print(f"{type(exc).__name__}: {exc}")
        print("=" * 78)
        input("\nPressione ENTER para fechar...")
