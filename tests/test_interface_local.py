# -*- coding: utf-8 -*-
"""
Testes da interface local (interface_local.py) — camada de lógica, sem display.

Execução:  python -m pytest tests/ -v
"""
import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "interface_local.py"


def _load_ui():
    spec = importlib.util.spec_from_file_location("interface_local_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ui = _load_ui()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Redireciona os arquivos de estado do módulo para um diretório temporário."""
    cache = {}
    monkeypatch.setattr(ui, "_UI_CACHE", cache)
    monkeypatch.setattr(ui, "QUEUE_FILE", tmp_path / "logs" / "fila_interface.json")
    monkeypatch.setattr(ui, "STATUS_CSV", tmp_path / "logs" / "cms_fluxo_status.csv")
    monkeypatch.setattr(ui, "CONTENT_FILE", tmp_path / "content_ids_interface.txt")
    monkeypatch.setattr(ui, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ui, "PID_FILE", tmp_path / "logs" / "processo_atual.pid")
    monkeypatch.setattr(ui, "STOP_FILE", tmp_path / "logs" / "parar_fluxo.flag")
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    yield cache


# ------------------------------------------------------------ fila

def test_ids_from_text():
    assert ui.ids_from_text("a1\nb2\na1") == ["a1", "b2"]
    assert ui.ids_from_text("a1, b2; c3") == ["a1", "b2", "c3"]
    assert ui.ids_from_text("  \n ") == []


def test_queue_persistence_roundtrip():
    saved = ui.save_queue(["x1", "x2", "x1", ""])
    assert saved == ["x1", "x2"]
    assert ui.load_queue() == ["x1", "x2"]


# ------------------------------------------------------------ status csv

def _write_status_csv(rows):
    header = ("datetime;content_id;content_title;status;original_file;"
              "processed_temp_file;final_upload_file;report_file;error")
    lines = [header] + [
        ";".join([
            datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            cid, title, status, "o.vtt", "p.vtt", "f.vtt", report, err,
        ])
        for (ts, cid, title, status, report, err) in rows
    ]
    ui.STATUS_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def test_read_status_csv_and_cache():
    _write_status_csv([(time.time(), "c1", "Título", "Iniciando", "", "")])
    rows = ui.read_status_csv()
    assert len(rows) == 1
    assert rows[0]["content_id"] == "c1"
    assert rows[0]["content_title"] == "Título"
    # cache: mesmo resultado sem reler (mutação externa não deve afetar)
    assert ui.read_status_csv() is rows


def test_real_items_status_last_row_wins():
    t0 = time.time() - 100
    _write_status_csv([
        (t0, "c1", "", "Erro", "", "falha antiga"),
        (t0 + 50, "c1", "Novo", "Enviado", "", ""),
    ])
    items = ui.real_items_status(["c1"], {}, {})
    assert items[0]["status"] == "Enviado"
    assert items[0]["progress"] == 100
    assert items[0]["content_title"] == "Novo"


def test_stale_error_override_does_not_mask_newer_success():
    t0 = time.time() - 100
    _write_status_csv([(t0, "c1", "", "Enviado", "rel.json", "")])
    overrides = {
        "c1": {"content_id": "c1", "status": "Erro", "progress": 100,
               "message": "Falha ao iniciar: X", "updated_at": t0 - 10},
    }
    items = ui.real_items_status(["c1"], {}, overrides)
    assert items[0]["status"] == "Enviado"
    assert "c1" not in overrides  # override obsoleto foi descartado


def test_fresh_override_still_applies():
    t0 = time.time() - 100
    _write_status_csv([(t0, "c1", "", "Baixando", "", "")])
    overrides = {
        "c1": {"content_id": "c1", "status": "Editando", "progress": 55,
               "message": "processando", "updated_at": t0 + 50},
    }
    items = ui.real_items_status(["c1"], {}, overrides)
    assert items[0]["status"] == "Editando"
    assert items[0]["progress"] == 55


# ------------------------------------------------------------ pastas / file_status

def test_file_status_exact_and_substring(tmp_path, monkeypatch):
    saida = tmp_path / "saida"
    entrada = tmp_path / "entrada"
    saida.mkdir()
    entrada.mkdir()
    (saida / "abc123.vtt").write_text("x", encoding="utf-8")
    (entrada / "SHOW_E1_abc123_subtitle.vtt").write_text("x", encoding="utf-8")

    assert ui.file_status(["abc123"], {})[ "abc123"]["status"] == "Arquivo gerado"
    # substring: id que só aparece dentro do nome do original
    (entrada / "OTHER_zz99.vtt").write_text("x", encoding="utf-8")
    assert ui.file_status(["zz99"], {})[ "zz99"]["status"] == "Baixando"
    assert ui.file_status(["naoexiste"], {})[ "naoexiste"]["status"] == "Pendente"


# ------------------------------------------------------------ botões / resumo

def test_summary_and_labels():
    items = [
        {"content_id": "1", "status": "Enviado", "progress": 100},
        {"content_id": "2", "status": "Arquivo gerado", "progress": 80},
        {"content_id": "3", "status": "Pendente", "progress": 0},
        {"content_id": "4", "status": "Erro", "progress": 100},
    ]
    total, concl, andam, pend, erros, geral, sem_legenda = ui.summary(items)
    assert (total, concl, andam, pend, erros) == (4, 1, 1, 1, 1)

    assert ui.display_button_label(items[0], "1", set()) == "Reprocessar"
    assert ui.display_button_label(items[1], "2", set()) == "Regerar"
    assert ui.display_button_label(items[2], "3", set()) == "Processar"
    assert ui.display_button_label(items[3], "4", set()) == "Reprocessar"
    running_item = {"content_id": "5", "status": "Baixando", "progress": 30}
    assert "Processando" in ui.display_button_label(running_item, "5", {"5"})
    # "Rergerar" tem precedência para arquivo já gerado (mesma ordem da Streamlit)
    assert ui.display_button_label(items[1], "2", {"2"}) == "Regerar"


def test_processable_only_pending():
    items = [
        {"content_id": "p", "status": "Pendente", "progress": 0},
        {"content_id": "d", "status": "Enviado", "progress": 100},
    ]
    assert ui.processable_queue_ids(["p", "d"], items) == ["p"]


def test_sorted_queue_running_first():
    items = [
        {"content_id": "done", "status": "Enviado", "progress": 100},
        {"content_id": "run", "status": "Baixando", "progress": 30},
        {"content_id": "pend", "status": "Pendente", "progress": 0},
    ]
    ordered = [i["content_id"] for i in ui.sorted_queue_items(items)]
    assert ordered[0] == "run"
    assert ordered[-1] == "done"


# ------------------------------------------------------------ fluxo (sem navegador)

def test_start_flow_refuses_without_ids(tmp_path, monkeypatch):
    ok, msg = ui.start_flow([], no_upload=True)
    assert not ok
    assert "Nenhum Content ID" in msg


def test_request_stop_flow_writes_flag(tmp_path, monkeypatch):
    assert ui.request_stop_flow() is True
    assert ui.STOP_FILE.exists()


def test_clean_exec_blocked_when_pid_running(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "is_pid_running", lambda: True)
    assert ui.clean_exec() is None


def test_clean_exec_moves_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "is_pid_running", lambda: False)
    ui.STATUS_CSV.write_text("x", encoding="utf-8")
    moved = ui.clean_exec()
    assert moved is not None and any("cms_fluxo_status" in m for m in moved)
    assert not ui.STATUS_CSV.exists()


# ------------------------------------------------------------ smoke GUI (se Tkinter existir)

def test_tk_import_handling():
    """O módulo importa sem erro com ou sem Tkinter (erro reportado, não crash)."""
    assert ui.TK_AVAILABLE or bool(ui.TK_IMPORT_ERROR)


def test_smoke_app_headless():
    """Cria e destrói a janela (requer display; pular se não houver)."""
    pytest.importorskip("tkinter")
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"sem display disponível: {exc}")
    root.destroy()
    # Se houve display, exercita a construção do app por 1 tick.
    app = ui.SubNexusApp()
    app.root.update_idletasks()
    app.refresh()
    app._on_close()
    assert True

# ------------------------------------------------------------ render fila (regressão GUI)


class _TclError(Exception):
    """Imita o _tkinter.TclError do Windows."""


class _FakeWidget:
    """Miniatura de widget Tkinter para validar o ciclo de vida do render.

    Modela o comportamento do Tcl: chamar pack/config em widget destruído
    dispara 'TclError: bad window path name'.
    """

    def __init__(self, parent=None, **kwargs):
        self.parent = parent
        self.destroyed = False
        self.packed = False
        self.pack_kwargs = {}
        self.children = []
        if parent is not None:
            parent.children.append(self)

    def winfo_children(self):
        return [w for w in self.children if not w.destroyed]

    def destroy(self):
        self.destroyed = True

    def pack(self, **kwargs):
        if self.destroyed:
            raise _TclError("bad window path name")
        self.packed = True
        self.pack_kwargs = kwargs

    def config(self, **kwargs):
        pass


def test_render_queue_empty_recreates_placeholder(monkeypatch):
    """Fila vazia não pode quebrar com 'bad window path name'.

    Regressão: _render_queue destrói todos os filhos de queue_frame; o
    pack do placeholder antigo (já destruído) causava TclError ao abrir o
    app com a fila vazia (máquina limpa) ou ao limpar a fila.
    """
    app = object.__new__(ui.SubNexusApp)
    queue_frame = _FakeWidget()
    app.queue_frame = queue_frame
    original = _FakeWidget(parent=queue_frame)  # criado no _build_layout
    app.queue_placeholder = original
    app.queue_ids = []
    app.lbl_selected_info = _FakeWidget()

    class _FakeTk:
        Label = _FakeWidget

    monkeypatch.setattr(ui, "tk", _FakeTk, raising=False)

    app._render_queue([])

    assert original.destroyed  # ciclo de render destrói os filhos
    assert app.queue_placeholder is not original, "deve recriar o placeholder"
    assert not app.queue_placeholder.destroyed
    assert app.queue_placeholder.packed
    assert app.queue_placeholder.pack_kwargs == {"pady": 24}
