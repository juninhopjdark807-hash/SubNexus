# -*- coding: utf-8 -*-
"""
SubNexus — benchmark passivo do processo manual no CMS.

Arquitetura:
  * Chrome real, sem Playwright, Selenium ou CDP;
  * extensão Manifest V3 instalada uma única vez no perfil do CMS;
  * eventos semânticos enviados para um coletor HTTP restrito ao loopback;
  * hotkeys globais: Ctrl+Alt+F8 inicia e Ctrl+Alt+F9 encerra em contingência.

A extensão não clica, não altera o DOM e não controla downloads ou abas.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading

from benchmark_passivo.config import BASE_DIR, load_config, resolve_repo_path
from benchmark_passivo.controller import BenchmarkController
from benchmark_passivo.server import start_server
from benchmark_passivo.windows_observer import (
    ForegroundObserver,
    GlobalHotkeyObserver,
    IS_WINDOWS,
)


EXTENSION_DIR = BASE_DIR / "benchmark_extension"
DEFAULT_LOGS_DIR = BASE_DIR / "logs" / "benchmark_passivo"


def find_chrome() -> Path | None:
    candidates: list[Path] = []
    for executable in ("chrome.exe",):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))

    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(
                Path(base, "Google", "Chrome", "Application", "chrome.exe")
            )

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def launch_chrome(chrome: Path, profile_dir: Path, url: str) -> subprocess.Popen:
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome),
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--new-window",
        "--start-maximized",
        url,
    ]
    return subprocess.Popen(command, cwd=str(BASE_DIR), shell=False)


def setup_extension(config: dict) -> int:
    if not IS_WINDOWS:
        print("A instalação é destinada ao Google Chrome no Windows.")
        return 2
    chrome = find_chrome()
    if chrome is None:
        print("Google Chrome não encontrado.")
        return 2
    if not (EXTENSION_DIR / "manifest.json").exists():
        print(f"Extensão não encontrada: {EXTENSION_DIR}")
        return 2

    profile_dir = resolve_repo_path(config["profile_dir"])
    print("=" * 78)
    print("INSTALAÇÃO ÚNICA — EXTENSÃO PASSIVA DO BENCHMARK")
    print("=" * 78)
    print()
    print("1. Na página chrome://extensions, ative 'Modo do desenvolvedor'.")
    print("2. Clique em 'Carregar sem compactação'.")
    print(f"3. Selecione exatamente esta pasta:\n   {EXTENSION_DIR}")
    print("4. Confirme que 'SubNexus — Observador Passivo do Benchmark' está ativo.")
    print("5. Feche completamente esse Chrome antes de iniciar o benchmark.")
    print()
    print("A instalação fica salva somente no perfil perfil_navegador_cms.")
    print()

    try:
        subprocess.Popen(["explorer.exe", str(EXTENSION_DIR)], shell=False)
    except OSError:
        pass
    launch_chrome(chrome, profile_dir, "chrome://extensions/")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark manual passivo do CMS, sem Playwright/CDP/UIA polling."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Arquivo JSON de configuração.",
    )
    parser.add_argument(
        "--setup-extension",
        action="store_true",
        help="Abre o Chrome e a pasta para instalar a extensão uma única vez.",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Inicia apenas o coletor; não abre o Chrome.",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Mantém o coletor ativo para várias tentativas.",
    )
    parser.add_argument(
        "--operator-id",
        default=os.environ.get("SUBNEXUS_OPERATOR_ID", ""),
        help="Identificador pseudonimizado do operador.",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOGS_DIR,
        help="Diretório de eventos e CSV.",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"Erro de configuração: {exc}")
        return 2

    if args.setup_extension:
        return setup_extension(config)

    if not IS_WINDOWS:
        print("Este coletor operacional requer Windows.")
        print("Os módulos de correlação podem ser testados em outras plataformas.")
        return 2

    if args.keep_running:
        config["trial"]["exit_after_finish"] = False
    config["_operator_id"] = str(args.operator_id or "").strip()

    host = str(config["collector"]["host"])
    port = int(config["collector"]["port"])
    profile_dir = resolve_repo_path(config["profile_dir"])
    logs_dir = args.logs_dir.resolve()
    stop_event = threading.Event()
    controller = BenchmarkController(config, logs_dir, stop_event=stop_event)

    try:
        server, server_thread = start_server(host, port, controller)
    except OSError as exc:
        controller.close()
        print(f"Não foi possível iniciar o coletor em {host}:{port}: {exc}")
        return 2

    foreground = ForegroundObserver(
        controller,
        store_titles=bool(config.get("privacy", {}).get("store_window_titles")),
    )
    foreground.start()

    hotkeys = GlobalHotkeyObserver(
        on_start=lambda: controller.begin_trial("global_hotkey_ctrl_alt_f8"),
        on_finish=lambda: controller.finish_trial(
            "manual_hotkey",
            "manual_boundary",
        ),
        controller=controller,
    )
    if not hotkeys.start():
        print(hotkeys.failed_reason)
        server.shutdown()
        server.server_close()
        foreground.stop()
        controller.close()
        return 2

    chrome_process: subprocess.Popen | None = None
    if not args.no_launch:
        chrome = find_chrome()
        if chrome is None:
            print("Google Chrome não encontrado.")
            stop_event.set()
        else:
            try:
                chrome_process = launch_chrome(chrome, profile_dir, config["cms_url"])
                controller.record_internal(
                    "chrome.launched",
                    {
                        "pid": chrome_process.pid,
                        "profile_dir": str(profile_dir),
                        "url": config["cms_url"],
                    },
                )
            except OSError as exc:
                print(f"Erro ao abrir o Chrome: {exc}")
                stop_event.set()

    interrupted = False

    def request_stop(signum=None, frame=None):
        nonlocal interrupted
        interrupted = True
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    exit_code = 0
    try:
        if not stop_event.is_set():
            wait_seconds = float(config["collector"].get("extension_wait_seconds", 20))
            print("Aguardando a extensão passiva conectar...", flush=True)
            if not controller.extension_connected.wait(timeout=wait_seconds):
                print()
                print("EXTENSÃO NÃO DETECTADA.")
                print("Execute primeiro:")
                print("  py benchmark_cms_passivo.py --setup-extension")
                print()
                print(
                    "Depois de carregar a extensão, feche completamente o Chrome "
                    "e execute este script novamente."
                )
                exit_code = 3
                stop_event.set()
            else:
                print()
                print("=" * 78)
                print("BENCHMARK PASSIVO PRONTO")
                print("=" * 78)
                print("Chrome real: SIM")
                print("Playwright/CDP/Selenium: NÃO")
                print("UIA polling/OCR: NÃO")
                print()
                print("1. Vá para a planilha.")
                print("2. Pressione Ctrl+Alt+F8 para INICIAR sem mudar de janela.")
                print("3. Execute todo o processo manual normalmente.")
                print("4. O Validate final encerra após a resposta correlacionada.")
                print("5. Contingência: Ctrl+Alt+F9 encerra manualmente.")
                print()
                print(f"Sessão: {controller.session_id}")
                print(f"Eventos: {controller.store.raw_path}")
                print()

        while not stop_event.wait(0.25):
            pass
    finally:
        # Primeiro deixa de aceitar novos lotes; depois encerra observadores e
        # persiste eventual tentativa incompleta como abortada.
        server.shutdown()
        server.server_close()
        if server_thread.is_alive():
            server_thread.join(timeout=2)
        hotkeys.stop()
        foreground.stop()
        controller.close()

    if interrupted:
        print("\nColetor interrompido pelo usuário.")
    print("O Chrome permanece aberto.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
