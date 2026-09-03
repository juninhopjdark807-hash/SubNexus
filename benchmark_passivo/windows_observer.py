from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import PureWindowsPath
import threading
from typing import Callable

from .controller import BenchmarkController


IS_WINDOWS = os.name == "nt"

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - fallback usado em instalação mínima
    psutil = None


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
VK_F9 = 0x78
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class GlobalHotkeyObserver:
    """Ctrl+Alt+F8 inicia; Ctrl+Alt+F9 encerra, sem mudar o foreground."""

    def __init__(
        self,
        on_start: Callable[[], None],
        on_finish: Callable[[], None],
        controller: BenchmarkController,
    ):
        self.on_start = on_start
        self.on_finish = on_finish
        self.controller = controller
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self.ready = threading.Event()
        self.failed_reason = ""

    def start(self) -> bool:
        if not IS_WINDOWS:
            self.failed_reason = "Hotkey global está disponível somente no Windows."
            return False
        self._thread = threading.Thread(
            target=self._run,
            name="BenchmarkGlobalHotkeys",
            daemon=True,
        )
        self._thread.start()
        self.ready.wait(timeout=3)
        return not self.failed_reason and self.ready.is_set()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        start_ok = bool(
            user32.RegisterHotKey(
                None,
                1,
                MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                VK_F8,
            )
        )
        finish_ok = bool(
            user32.RegisterHotKey(
                None,
                2,
                MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                VK_F9,
            )
        )
        if not start_ok or not finish_ok:
            if start_ok:
                user32.UnregisterHotKey(None, 1)
            if finish_ok:
                user32.UnregisterHotKey(None, 2)
            self.failed_reason = (
                "Não foi possível registrar Ctrl+Alt+F8/F9; outro programa pode "
                "estar usando essas combinações."
            )
            self.ready.set()
            return

        self.ready.set()
        self.controller.record_internal(
            "windows.hotkeys.ready",
            {"start": "Ctrl+Alt+F8", "finish": "Ctrl+Alt+F9"},
        )
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message != WM_HOTKEY:
                    continue
                if int(message.wParam) == 1:
                    self.on_start()
                elif int(message.wParam) == 2:
                    self.on_finish()
        finally:
            user32.UnregisterHotKey(None, 1)
            user32.UnregisterHotKey(None, 2)

    def stop(self) -> None:
        if IS_WINDOWS and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id,
                WM_QUIT,
                0,
                0,
            )
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


class ForegroundObserver:
    """Registra apenas transições de aplicativo, sem percorrer árvore UIA."""

    def __init__(self, controller: BenchmarkController, store_titles: bool = False):
        self.controller = controller
        self.store_titles = store_titles
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_signature: tuple[int, str] | None = None

    def start(self) -> bool:
        if not IS_WINDOWS:
            return False
        self._thread = threading.Thread(
            target=self._run,
            name="BenchmarkForegroundObserver",
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        while not self._stop.wait(0.10):
            try:
                hwnd = int(user32.GetForegroundWindow())
                if not hwnd:
                    continue
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process_name = self._process_name(int(pid.value))
                app = self._classify_app(process_name)
                signature = (int(pid.value), app)
                if signature == self._last_signature:
                    continue
                self._last_signature = signature
                data = {
                    "app": app,
                    "process_name": process_name,
                    "pid": int(pid.value),
                }
                if self.store_titles:
                    data["window_title"] = self._window_title(hwnd)
                self.controller.record_internal(
                    "windows.foreground.changed",
                    data,
                )
            except Exception as exc:
                self.controller.record_internal(
                    "windows.foreground.warning",
                    {"error_type": type(exc).__name__},
                )
                self._stop.wait(0.5)

    @staticmethod
    def _process_name(pid: int) -> str:
        if psutil is not None:
            try:
                return str(psutil.Process(pid).name()).lower()[:128]
            except Exception:
                pass
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                return f"pid-{pid}"
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(buffer))
                if kernel32.QueryFullProcessImageNameW(
                    handle,
                    0,
                    buffer,
                    ctypes.byref(size),
                ):
                    return PureWindowsPath(buffer.value).name.lower()[:128]
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
        return f"pid-{pid}"

    @staticmethod
    def _classify_app(process_name: str) -> str:
        compact = recompact(process_name)
        if "subtitleedit" in compact:
            return "subtitle_edit"
        if compact in {"chromeexe", "msedgeexe", "chromiumexe"}:
            return "browser"
        if compact in {"excelexe", "libreofficeexe", "scalcexe"}:
            return "spreadsheet"
        if any(
            token in compact
            for token in (
                "cmdexe",
                "powershellexe",
                "windowsterminalexe",
                "pythonexe",
                "pythonwexe",
            )
        ):
            return "benchmark_console"
        return "other"

    @staticmethod
    def _window_title(hwnd: int) -> str:
        user32 = ctypes.windll.user32
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(min(length + 1, 1024))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value[:1000]

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


def recompact(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())
