# -*- coding: utf-8 -*-
"""
Smoke test de construção da GUI com Tkinter FALSO (sem display).

Carrega interface_local.py com um tkinter simulado (injetado em
sys.modules), instancia o SubNexusApp e roda ciclos de refresh — valida o
caminho completo de construção (cards arredondados, botões em pill,
linhas da fila, chips, gradientes) sem precisar de display.

Máquinas com display real continuam cobertas pelo teste de fumaça genuíno
(test_smoke_app_headless em test_interface_local.py).
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "interface_local.py"

# ================================================================ fake tk

class _Var:
    def __init__(self, value=None):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Font:
    def __init__(self, family=None, size=10, weight="normal", **kw):
        self.size = size

    def measure(self, text):
        return max(8, int(len(str(text)) * self.size * 0.62))


class _PhotoImage:
    def __init__(self, master=None, width=1, height=1, file=None, **kw):
        self._w = width
        self._h = height
        self.put_calls = 0

    def put(self, data, to=None):
        self.put_calls += 1

    def width(self):
        return self._w

    def height(self):
        return self._h

    def subsample(self, x, y):
        self._w = max(1, self._w // x)
        self._h = max(1, self._h // y)
        return self


_AFTERS = []


def _drain_afters():
    jobs = list(_AFTERS)
    _AFTERS.clear()
    for _ms, func in jobs:
        if callable(func):
            func()


class _Widget:
    def __init__(self, master=None, **kw):
        self.master = master
        self.kw = kw
        self._children = []
        self._bindings = {}
        self._req = (kw.get("width", 120), kw.get("height", 28))
        self._alloc = (self._req[0], self._req[1])
        if master is not None and hasattr(master, "_children"):
            master._children.append(self)

    # ---- geometria
    def grid(self, **kw):
        self.kw.update(kw)

    def pack(self, **kw):
        self.kw.update(kw)

    def place(self, **kw):
        self.kw.update(kw)

    def grid_propagate(self, flag):
        pass

    def columnconfigure(self, *a, **k):
        pass

    def rowconfigure(self, *a, **k):
        pass

    def update_idletasks(self):
        for c in self._children:
            c.update_idletasks()
        w, h = self._req
        if isinstance(self, _Canvas):
            self._alloc = (max(w, 900), max(h, 300))
        else:
            self._alloc = (max(w, 220), max(h, 28))

    def winfo_width(self):
        return self._alloc[0]

    def winfo_height(self):
        return self._alloc[1]

    def winfo_reqwidth(self):
        return self._req[0]

    def winfo_reqheight(self):
        return self._req[1]

    def winfo_children(self):
        return list(self._children)

    def winfo_point(self, x, y):
        return 1

    # ---- opções
    def config(self, **kw):
        self.kw.update(kw)
        if "width" in kw:
            self._req = (kw["width"], self._req[1])
        if "height" in kw:
            self._req = (self._req[0], kw["height"])
        return None

    configure = config

    def cget(self, key, **kw):
        return self.kw.get(key)

    # ---- eventos
    def bind(self, seq, func=None, add=True):
        self._bindings[seq] = func
        return ""

    def bind_all(self, seq, func=None, add=True):
        return ""

    def unbind(self, seq, func=None):
        self._bindings.pop(seq, None)
        return ""

    def bindtags(self, tags=None):
        return ()

    # ---- ciclo de vida
    def destroy(self):
        if self.master is not None and self in getattr(self.master, "_children", []):
            self.master._children.remove(self)

    def after(self, ms, func=None, *args):
        _AFTERS.append((ms, func))
        return len(_AFTERS)

    def after_cancel(self, wid):
        pass

    def after_idle(self, func=None):
        _AFTERS.append((0, func))
        return len(_AFTERS)

    def protocol(self, name, cmd=None):
        pass

    def lift(self):
        pass

    # ---- canvas (e operações de Text: delete é no-op nos dois casos)
    def delete(self, *a):
        pass

    def create_image(self, *a, **k):
        return 1

    def create_window(self, *a, **k):
        return 2

    def create_text(self, *a, **k):
        return 3

    def create_polygon(self, *a, **k):
        return 4

    def create_line(self, *a, **k):
        return 5

    def create_oval(self, *a, **k):
        return 6

    def create_rectangle(self, *a, **k):
        return 7

    def itemconfigure(self, *a, **k):
        pass

    def bbox(self, *a):
        return (0, 0, 50, 50)

    def coords(self, *a):
        return []

    def yview_scroll(self, *a):
        pass

    def yview_moveto(self, *a):
        pass

    def yview(self, *a):
        return self

    def xview(self, *a):
        return self

    def flush(self):
        pass

    # ---- extras do Tk root
    def title(self, t):
        pass

    def geometry(self, g=None):
        pass

    def minsize(self, *a):
        pass

    def iconphoto(self, *a, **k):
        pass

    def option_add(self, *a, **k):
        pass

    # ---- text widget / combobox
    def insert(self, *a, **k):
        pass

    def get(self, *a, **k):
        return ""

    def tag_config(self, *a, **k):
        pass

    def tag_add(self, *a):
        pass

    def tag_ranges(self, *a):
        return ()

    def see(self, *a):
        pass

    def set(self, v):
        self.kw["value"] = v
        return None


class _Canvas(_Widget):
    pass


class _Frame(_Widget):
    pass


class _Label(_Widget):
    pass


class _Text(_Widget):
    pass


class _Tk(_Widget):
    pass


class _Style:
    def __init__(self, master=None, **kw):
        pass

    def theme_use(self, name=None):
        return "clam"

    def configure(self, *a, **k):
        pass

    def map(self, *a, **k):
        pass


class _TtkWidget(_Widget):
    pass


def _make_fake_tk():
    mod = types.ModuleType("tkinter")
    mod.Tk = _Tk
    mod.Frame = _Frame
    mod.Canvas = _Canvas
    mod.Label = _Label
    mod.Text = _Text
    mod.PhotoImage = _PhotoImage
    mod.BooleanVar = _Var
    mod.StringVar = _Var
    mod.TclError = type("TclError", (Exception,), {})
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Style = _Style
    ttk.Button = _TtkWidget
    ttk.Combobox = _TtkWidget
    ttk.Scrollbar = _TtkWidget
    mod.ttk = ttk
    fontmod = types.ModuleType("tkinter.font")
    fontmod.Font = _Font
    mod.font = fontmod
    return mod, ttk, fontmod


def _load_with_fake_tk(monkeypatch):
    fake, ttk, fontmod = _make_fake_tk()
    monkeypatch.setitem(sys.modules, "tkinter", fake)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.font", fontmod)
    spec = importlib.util.spec_from_file_location(
        "interface_local_fake_tk", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    mod = _load_with_fake_tk(monkeypatch)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(mod, "QUEUE_FILE", tmp_path / "logs" / "fila_interface.json")
    monkeypatch.setattr(mod, "STATUS_CSV", tmp_path / "logs" / "cms_fluxo_status.csv")
    monkeypatch.setattr(mod, "TIMING_CSV", tmp_path / "logs" / "cms_fluxo_tempos.csv")
    monkeypatch.setattr(mod, "CONTENT_FILE", tmp_path / "content_ids_interface.txt")
    monkeypatch.setattr(mod, "PID_FILE", tmp_path / "logs" / "processo_atual.pid")
    monkeypatch.setattr(mod, "STOP_FILE", tmp_path / "logs" / "parar_fluxo.flag")
    monkeypatch.setattr(mod, "CMS_INSTANCE_FILE",
                        tmp_path / "logs" / "cms_instance_state.json")
    monkeypatch.setattr(mod, "CMS_PROFILE_DIR", tmp_path / "perfil_navegador_cms")
    monkeypatch.setattr(mod, "CMS_PROFILE_LOCK",
                        tmp_path / "perfil_navegador_cms" / "lockfile")
    monkeypatch.setattr(mod, "FAVICON_FILE", tmp_path / "subnexus_favicon.png")
    monkeypatch.setattr(mod, "LOGO_FILE", tmp_path / "subnexus_logo.png")
    monkeypatch.setattr(mod, "EDITOR_SCRIPT", tmp_path / "vtt_auto_editor.py")
    monkeypatch.setattr(mod, "_UI_CACHE", {})
    yield mod
    _AFTERS.clear()
    sys.modules.pop("interface_local_fake_tk", None)


# ================================================================ testes

def test_fake_tk_build_full(app_env):
    """Construção completa do app (cards, botões, layout) sem display."""
    mod = app_env
    assert mod.TK_AVAILABLE
    assert hasattr(mod, "RoundCard") and hasattr(mod, "RoundButton")

    app = mod.SubNexusApp()
    app.root.update_idletasks()
    _drain_afters()

    # cards foram criados e desenhados (imagem gerada)
    assert len(app._cards) >= 5
    assert all(c._img is not None for c in app._cards), "card sem imagem"

    # fila vazia -> placeholder
    assert isinstance(app.queue_placeholder, mod.tk.Label)

    # widgets principais existem
    for name in ("btn_process", "btn_remove", "btn_clear_queue_main",
                 "btn_change_project", "btn_stop", "cmb_language",
                 "txt_ids", "canvas_overall", "lbl_status", "lbl_version"):
        assert getattr(app, name, None) is not None, f"falta {name}"


def test_fake_tk_rows_and_clear(app_env):
    """Fila com itens -> linhas novas; limpar -> volta ao placeholder."""
    mod = app_env
    app = mod.SubNexusApp()
    app.root.update_idletasks()
    _drain_afters()

    app.queue_ids = ["DEMO-1", "DEMO-2"]
    app._flow_active = False
    app.refresh()

    rows = [c for c in app.queue_frame.winfo_children()
            if isinstance(c, mod._QueueRow)]
    assert len(rows) == 2
    for row in rows:
        assert row._img is not None, "linha sem imagem de fundo"
        assert len(row._btns) >= 3
        assert row._chip is not None

    # limpar a fila devolve o placeholder
    app._on_clear_queue()
    rows = [c for c in app.queue_frame.winfo_children()
            if isinstance(c, mod._QueueRow)]
    assert not rows
    assert app.queue_placeholder is not None

    _drain_afters()
    app._on_close()
