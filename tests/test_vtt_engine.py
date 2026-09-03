# -*- coding: utf-8 -*-
"""
Testes do motor de edição VTT (vtt_auto_editor.py).

Protegem as regras fixas de legendas (33 chars/linha, 2 linhas/cue, 66 chars/cue,
diálogo, timecodes) e as integrações que antes eram código morto
(caracteres suspeitos no relatório, trava de instância única).

Execução:  python -m pytest tests/ -v
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "vtt_auto_editor.py"


def _load_editor():
    spec = importlib.util.spec_from_file_location("vtt_auto_editor_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ed = _load_editor()


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch, tmp_path):
    """Evita que os testes toquem em arquivos do repositório."""
    monkeypatch.setattr(ed, "log_event", lambda msg: None)
    yield


def make_vtt(cues, header="WEBVTT"):
    parts = [header, ""]
    for start, end, text in cues:
        parts.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(parts)


def cue_lines(vtt_text):
    blocks = [b.strip() for b in vtt_text.split("\n\n") if b.strip()]
    out = []
    for b in blocks:
        lines = b.split("\n")
        if "-->" in lines[0]:
            out.append("\n".join(lines[1:]))
    return out


# ---------------------------------------------------------------- limpeza

def test_clean_text_removes_italic_and_br():
    out = ed.clean_text("<i>Teste</i> de <br/> legenda")
    assert "<i>" not in out and "</i>" not in out
    assert "<br" not in out
    assert out == "Teste de\nlegenda"


def test_clean_text_preserves_ellipsis_and_normalizes_dash():
    out = ed.clean_text("isso... — Olá, tudo bem?")
    assert "isso..." in out
    assert "—" not in out and "–" not in out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0].startswith("isso...")
    assert lines[1] == "-Olá, tudo bem?"


def test_clean_text_spacing_around_punctuation():
    out = ed.clean_text("olá,tudo   bem?")
    assert "olá, tudo bem?" in out


# ---------------------------------------------------------------- divisão

def _assert_part_within_limits(part, long_word=None):
    """Contrato de uma PARTE pré-format: <= 66 chars visíveis e cabível em 2 linhas de <= 33."""
    assert ed.visible_char_count(part) <= ed.MAX_CHARS_PER_CUE
    lines = ed.wrap_text_to_lines(part)
    assert len(lines) <= ed.MAX_LINES_PER_CUE
    for ln in lines:
        if long_word and long_word in ln:
            continue
        assert len(ln) <= ed.MAX_CHARS_PER_LINE, ln


def _assert_final_cue_text(text, long_word=None):
    """Contrato do texto FINAL do cue (após format_cue_text)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) <= ed.MAX_LINES_PER_CUE
    assert ed.visible_char_count(text) <= ed.MAX_CHARS_PER_CUE
    for ln in lines:
        if long_word and long_word in ln:
            continue
        assert len(ln) <= ed.MAX_CHARS_PER_LINE, ln


def test_split_respects_limits():
    text = " ".join(
        ["a"] * 5 + ["trabalho"] * 10 + ["muito", "longo", "trecho", "de", "legenda"] * 6
    )
    parts = ed.split_text_into_cue_parts(text)
    assert len(parts) >= 2
    for part in parts:
        _assert_part_within_limits(part)


def test_edit_cue_final_text_within_limits():
    """O texto final de cada cue criado deve respeitar 33/linha e 2 linhas."""
    long_text = " ".join(["reunião"] * 4 + ["decidiu"] * 6 + ["finalmente"] * 8)
    cue = ed.VttCue(index=1, identifier=None, timecode="00:00:00.000 --> 00:00:20.000", text=long_text)
    new_cues, info = ed.edit_cue(cue)
    assert info["split_applied"]
    for c in new_cues:
        _assert_final_cue_text(c.text, long_word="finalmente")
    assert " ".join(" ".join(c.text.split()) for c in new_cues) == long_text


def test_split_never_breaks_words():
    text = "palavra " * 25
    parts = ed.split_text_into_cue_parts(text.strip())
    rejoined = " ".join(parts)
    assert rejoined == text.strip()


def test_split_isolated_e_allowed():
    # "e" como conjunção isolada pode iniciar a parte seguinte.
    text = "Ela chegou atrasada e esperou por todo o grupo na porta da casa"
    parts = ed.split_text_into_cue_parts(text)
    assert " ".join(parts) == text
    for part in parts:
        _assert_part_within_limits(part)


def test_dialogue_lines_stay_separate():
    text = "-Olá, como vai?\n-Tudo bem, obrigado."
    parts = ed.split_text_into_cue_parts(text)
    assert len(parts) == 1
    lines = parts[0].splitlines()
    assert lines[0].startswith("-")
    assert lines[1].startswith("-")


# ---------------------------------------------------------------- timecodes

def test_timecode_roundtrip():
    for tc, frames in [
        ("00:00:01.000", 30),
        ("01:02:03.100", ((3600 + 123) * 30) + round(0.100 * 30)),
        ("00:01:05:07", 65 * 30 + 7),
        ("01:05:07", 65 * 30 + 7),
    ]:
        assert ed.timecode_to_frames(tc) == frames
        fmt = ed.detect_timecode_format(tc)
        assert ed.frames_to_timecode(frames, fmt) == tc


def test_distribute_timecodes_contiguous_and_inside_original():
    tcs, warnings = ed.distribute_timecodes("00:00:00.000 --> 00:00:10.000", ["a b", "c d e", "f g"])
    assert len(tcs) == 3
    parsed = [ed.parse_timecode_line(tc) for tc in tcs]
    s0, e0, _, _ = parsed[0]
    s_last, e_last, _, _ = parsed[-1]
    assert s0 == 0
    assert e_last == 10 * 30
    for (s1, e1, _, _), (s2, e2, _, _) in zip(parsed, parsed[1:]):
        assert s2 == e1 + 1  # 1 frame de intervalo, sem sobreposição
        assert s2 <= e2


def test_repair_overlapping_timecodes():
    a = ed.VttCue(index=1, identifier=None, timecode="00:00:00.000 --> 00:00:05.000", text="x")
    b = ed.VttCue(index=2, identifier=None, timecode="00:00:04.000 --> 00:00:10.000", text="y")
    repaired, fixes = ed.repair_overlapping_timecodes([a, b])
    s2, e2, _, _ = ed.parse_timecode_line(repaired[1].timecode)
    s1, e1, _, _ = ed.parse_timecode_line(repaired[0].timecode)
    assert s2 >= e1 + 1
    assert len(fixes) == 1
    assert ed.validate_overlaps(repaired) == []


# ---------------------------------------------------------------- relatório

def test_process_file_flags_suspicious_characters(tmp_path):
    """A validação de caracteres suspeitos tem que chegar ao relatório (antes era código morto)."""
    vtt = make_vtt([
        ("00:00:00.000", "00:00:04.000", "texto normal de teste"),
        ("00:00:04.500", "00:00:08.000", "erro de encoding ŕ aqui"),
    ])
    src = tmp_path / "entrada" / "amostra.vtt"
    src.parent.mkdir(parents=True)
    src.write_text(vtt, encoding="utf-8")
    out_dir = tmp_path / "saida"
    rep_dir = tmp_path / "relatorios"

    summary = ed.process_file(src, out_dir, rep_dir)

    assert summary["suspicious_characters"] >= 1
    assert summary["status"].startswith("ATENÇÃO")

    report = json.loads((rep_dir / "amostra_relatorio.json").read_text(encoding="utf-8"))
    findings = report["remaining_issues"]["suspicious_characters"]
    assert findings
    assert any(f["character"] == "ŕ" for item in findings for f in item["findings"])


def test_process_file_clean_file_ok(tmp_path):
    vtt = make_vtt([
        ("00:00:00.000", "00:00:04.000", "<i>Olá</i>, tudo bem? <br/>Estamos aqui."),
        ("00:00:04.500", "00:00:09.000", "Um trecho um pouco mais longo para obrigar a divisão em duas linhas, sim."),
    ])
    src = tmp_path / "entrada" / "limpo.vtt"
    src.parent.mkdir(parents=True)
    src.write_text(vtt, encoding="utf-8")

    summary = ed.process_file(src, tmp_path / "saida", tmp_path / "relatorios")

    assert summary["status"].startswith("OK")
    assert summary["remaining_italic_tags"] == 0
    assert summary["remaining_br_tags"] == 0
    assert summary["long_lines"] == 0
    assert summary["overlaps"] == 0

    out_files = list((tmp_path / "saida").glob("*.vtt"))
    assert len(out_files) == 1
    for text in cue_lines(out_files[0].read_text(encoding="utf-8")):
        _assert_part_within_limits(text)


def test_process_file_keeps_webvtt_header_and_raw_blocks(tmp_path):
    vtt = make_vtt([("00:00:00.000", "00:00:02.000", "oi")], header="WEBVTT\nKind: captions\nLanguage: pt-BR")
    src = tmp_path / "entrada" / "raw.vtt"
    src.parent.mkdir(parents=True)
    src.write_text(vtt, encoding="utf-8")
    ed.process_file(src, tmp_path / "saida", tmp_path / "relatorios")
    out = list((tmp_path / "saida").glob("*.vtt"))[0].read_text(encoding="utf-8")
    assert out.startswith("WEBVTT")
    assert "Kind: captions" in out


# ---------------------------------------------------------------- instância única

def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "notify_already_running", lambda: None)
    assert ed.acquire_single_instance_lock() is True
    assert ed.acquire_single_instance_lock() is False
    ed._SINGLE_INSTANCE_SOCKET.close()
    ed._SINGLE_INSTANCE_SOCKET = None
