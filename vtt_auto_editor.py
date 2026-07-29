#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Editor mecânico de legendas .VTT — Python puro

Versão: final_operacional

Não usa IA.
Não usa API.
Não usa internet.
Não usa bibliotecas externas.
Não faz substituições automáticas de palavras.

REGRAS FIXAS:
- Preserva WEBVTT e blocos especiais.
- Remove <i> e </i>.
- Converte <br>, <br/> e <br /> em separador interno de texto.
- Não trata </br> como erro.
- Preserva reticências "...".
- Converte travessão de diálogo "—" e meia-risca "–" em hífen "-".
- Limite absoluto: 33 caracteres por linha.
- Nunca mais de 2 linhas por cue.
- Até 33 caracteres: 1 linha.
- De 34 até 66 caracteres: até 2 linhas.
- Acima de 66 caracteres: divide em novos cues.
- Se uma parte ainda geraria 3 linhas, divide em mais cues.
- Mantém o formato original do timecode na saída.
- Calcula internamente com 30 fps.
- Não altera timecodes em cascata.
- Só divide internamente o tempo do próprio cue quando ele for quebrado.
- O próximo cue criado começa 1 frame após o anterior.
- Não separa palavras.
- Não quebra antes de vírgula, ponto ou pontuação.
- A conjunção "e" só é considerada ponto de quebra quando for palavra isolada: " e ".
- Não junta falas de diálogo marcadas com "-".
- Processa apenas o .vtt mais recente ainda não processado na pasta de entrada.
- Registra arquivos processados em .vtt_processados.json.
- Pode monitorar a pasta automaticamente com --watch.
- Mostra pop-up ao finalizar o processamento.
- Abre automaticamente o arquivo processado para conferência.
- No modo --watch, ignora os arquivos que já existiam na pasta ao iniciar.
- Remove espaço inútil em marcador de diálogo: "- " vira "-".
- Lê configurações do arquivo config.json.
- Gera relatório JSON e TXT.
- Valida sobreposição no arquivo final.
- Move o arquivo para Revisados após confirmação.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import socket
from datetime import datetime
import os
import subprocess
import sys
import shutil
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Union, Dict, Any, Tuple

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = TimeoutError



FPS = 30
MAX_CHARS_PER_LINE = 33
MAX_CHARS_PER_CUE = 66
MAX_LINES_PER_CUE = 2
FRAME_STEP = 1
STATE_FILE_NAME = ".vtt_processados.json"

SINGLE_INSTANCE_HOST = "127.0.0.1"
SINGLE_INSTANCE_PORT = 49321
_SINGLE_INSTANCE_SOCKET = None


def acquire_single_instance_lock() -> bool:
    """
    Impede múltiplas instâncias do script rodando ao mesmo tempo.

    Usa uma porta local fixa. Se outra instância já estiver rodando,
    a porta estará ocupada e esta execução encerra.
    """
    global _SINGLE_INSTANCE_SOCKET

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((SINGLE_INSTANCE_HOST, SINGLE_INSTANCE_PORT))
        sock.listen(1)
        _SINGLE_INSTANCE_SOCKET = sock
        return True
    except OSError:
        return False


def notify_already_running() -> None:
    """
    Mostra aviso quando o usuário tenta iniciar o script mais de uma vez.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(
            "Editor VTT já está rodando",
            "O script de automação de legendas já está em execução.\n\n"
            "Nenhuma nova instância foi iniciada."
        )
        root.destroy()
    except Exception:
        pass

CONFIG = {}


MIN_CREATED_PART_CHARS = 12
MIN_CREATED_PART_WORDS = 2


TIMECODE_RE = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}(?::\d{2}|\.\d{3}))\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}(?::\d{2}|\.\d{3}))(?P<settings>.*)$"
)

ITALIC_TAG_RE = re.compile(r"</?\s*i\s*>", flags=re.IGNORECASE)
BR_TAG_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
MULTISPACE_RE = re.compile(r"[ \t]+")

PUNCTUATION = ".,!?;:"
STRONG_PUNCTUATION = ".!?"
SOFT_PUNCTUATION = ",;:"

# Caracteres aceitos em legendas PT/ES + pontuação comum.
# Tudo fora disso será apenas reportado, nunca substituído automaticamente.
ALLOWED_LETTERS_EXTRA = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
ALLOWED_SYMBOLS_EXTRA = (
    " \n\t"
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    + ALLOWED_LETTERS_EXTRA +
    ".,;:!?…"
    "'\"“”‘’"
    "-"
    "()[]{}"
    "/\\"
    "@#$%&*+=_"
    "°ªº"
    "¿¡"
)

# Caracteres tecnicamente suspeitos mesmo que sejam letras Unicode.
# Ex.: ŕ parece erro de encoding/OCR quando o esperado seria "à".
SUSPICIOUS_EXPLICIT_CHARS = set("ŕŔ")


@dataclass
class VttCue:
    index: int
    identifier: Optional[str]
    timecode: str
    text: str


@dataclass
class RawBlock:
    content: str


Block = Union[VttCue, RawBlock]


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def log_event(message: str) -> None:
    """
    Registra eventos importantes em arquivo de log.
    Útil quando o script roda por pythonw sem CMD aberto.
    """
    try:
        log_path = Path(__file__).resolve().parent / "execucao.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def make_unique_output_path(output_dir: Path, input_file: Path) -> Path:
    """
    Gera um nome único para o arquivo processado.
    Isso evita que o Subtitle Edit/Windows abra uma versão antiga em cache
    quando vários arquivos têm o mesmo nome.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = input_file.stem
    suffix = input_file.suffix or ".vtt"
    return output_dir / f"{safe_stem}_editado_{timestamp}{suffix}"


def find_subtitle_edit_exe() -> Optional[Path]:
    """
    Tenta localizar o Subtitle Edit em caminhos comuns.
    Se config.json tiver subtitle_edit_path, ele tem prioridade.
    """
    configured = str(CONFIG.get("subtitle_edit_path", "")).strip() if CONFIG else ""
    if configured:
        p = Path(configured)
        if p.exists():
            return p

    candidates = [
        Path(r"C:\Program Files\Subtitle Edit\SubtitleEdit.exe"),
        Path(r"C:\Program Files (x86)\Subtitle Edit\SubtitleEdit.exe"),
        Path.home() / r"AppData\Local\Programs\Subtitle Edit\SubtitleEdit.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def load_config(config_path: Path) -> Dict[str, Any]:
    default = {
        "fps": 30,
        "max_chars_per_line": 33,
        "max_lines_per_cue": 2,
        "max_chars_per_cue": 66,
        "input_folder": "entrada",
        "output_folder": "saida",
        "reports_folder": "relatorios",
        "reviewed_folder": "Revisados",
        "show_popup": True,
        "open_after_process": True,
        "move_to_reviewed_after_confirmation": True,
        "watch_interval_seconds": 3,
        "process_existing_on_start": False,
        "state_file": ".vtt_processados.json",
        "subtitle_edit_path": ""
    }
    if config_path.exists():
        try:
            data = json.loads(read_text_file(config_path))
            if isinstance(data, dict):
                default.update(data)
        except Exception as exc:
            print(f"AVISO: não foi possível ler config.json; usando padrão. Erro: {exc}")
    return default


def apply_config(config: Dict[str, Any]) -> None:
    global CONFIG, FPS, MAX_CHARS_PER_LINE, MAX_LINES_PER_CUE, MAX_CHARS_PER_CUE, STATE_FILE_NAME
    CONFIG = config
    FPS = int(config.get("fps", 30))
    MAX_CHARS_PER_LINE = int(config.get("max_chars_per_line", 33))
    MAX_LINES_PER_CUE = int(config.get("max_lines_per_cue", 2))
    MAX_CHARS_PER_CUE = int(config.get("max_chars_per_cue", MAX_CHARS_PER_LINE * MAX_LINES_PER_CUE))
    STATE_FILE_NAME = str(config.get("state_file", ".vtt_processados.json"))


def resolve_path(value: str, base_dir: Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else base_dir / p


def show_popup(title: str, message: str) -> None:
    if CONFIG and not CONFIG.get("show_popup", True):
        return
    """
    Mostra um pop-up usando tkinter, que faz parte da biblioteca padrão do Python.
    Se o ambiente bloquear janela gráfica, apenas imprime no terminal.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(title, message)
        root.destroy()
    except Exception:
        print("\n" + "=" * 60)
        print(title)
        print("-" * 60)
        print(message)
        print("=" * 60 + "\n")


def wait_until_file_is_stable(path: Path, checks: int = 2, interval: float = 1.0) -> bool:
    """
    Evita processar arquivo enquanto o download ainda está sendo concluído.

    Retorna True se tamanho e data de modificação ficarem estáveis
    por algumas checagens consecutivas.
    """
    last = None
    stable_count = 0

    for _ in range(checks + 3):
        try:
            stat = path.stat()
            current = (stat.st_size, stat.st_mtime)
        except FileNotFoundError:
            return False

        if current == last and stat.st_size > 0:
            stable_count += 1
        else:
            stable_count = 0

        if stable_count >= checks:
            return True

        last = current
        time.sleep(interval)

    return False


def open_file_for_review(path: Path) -> bool:
    """
    Abre exatamente o arquivo informado.

    Prioridade:
    1. Subtitle Edit configurado ou localizado automaticamente.
    2. Programa padrão do Windows.

    Também registra em execucao.log qual caminho foi aberto.
    """
    if CONFIG and not CONFIG.get("open_after_process", True):
        return False

    try:
        path = path.resolve()

        if not path.exists():
            msg = f"Não foi possível abrir: arquivo não existe: {path}"
            print(msg)
            log_event(msg)
            return False

        log_event(f"Tentando abrir arquivo para revisão: {path}")

        subtitle_edit = find_subtitle_edit_exe()
        if subtitle_edit and subtitle_edit.exists():
            subprocess.Popen([str(subtitle_edit), str(path)])
            log_event(f"Aberto com Subtitle Edit: exe={subtitle_edit} arquivo={path}")
            return True

        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            log_event(f"Aberto com programa padrão do Windows: {path}")
            return True

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            log_event(f"Aberto com open: {path}")
            return True

        subprocess.Popen(["xdg-open", str(path)])
        log_event(f"Aberto com xdg-open: {path}")
        return True

    except Exception as exc:
        msg = f"Não foi possível abrir o arquivo para revisão: {exc}"
        print(msg)
        log_event(msg)
        return False


def ask_review_confirmation(file_path: Path) -> bool:
    if CONFIG and not CONFIG.get("move_to_reviewed_after_confirmation", True):
        return False
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        messagebox.showinfo(
            "Mover para Revisados",
            "Revise e salve o arquivo aberto.\n\n"
            "Quando terminar, clique OK para mover o arquivo para a pasta Revisados.\n\n"
            f"Arquivo:\n{file_path}"
        )
        root.destroy()
        return True
    except Exception:
        input("Depois de revisar e salvar, pressione ENTER para mover para Revisados...")
        return True


def move_to_reviewed(file_path: Path, reviewed_dir: Path) -> Optional[Path]:
    reviewed_dir.mkdir(parents=True, exist_ok=True)
    dest = reviewed_dir / file_path.name
    if dest.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest = reviewed_dir / f"{dest.stem}_{stamp}{dest.suffix}"
    try:
        shutil.move(str(file_path), str(dest))
        return dest
    except Exception as exc:
        print(f"Não foi possível mover para Revisados: {exc}")
        return None


def normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def is_timecode_line(line: str) -> bool:
    return bool(TIMECODE_RE.match(line.strip()))


def parse_vtt(content: str) -> List[Block]:
    content = normalize_newlines(content).strip("\n")
    raw_blocks = re.split(r"\n\s*\n", content)
    parsed: List[Block] = []
    cue_index = 0

    for raw in raw_blocks:
        block = raw.strip("\n")
        if not block.strip():
            continue

        lines = block.split("\n")
        timecode_pos = None

        for i, line in enumerate(lines):
            if is_timecode_line(line):
                timecode_pos = i
                break

        if timecode_pos is None:
            parsed.append(RawBlock(content=block))
            continue

        identifier = None
        if timecode_pos > 0:
            identifier = "\n".join(lines[:timecode_pos]).strip() or None

        cue_index += 1
        parsed.append(
            VttCue(
                index=cue_index,
                identifier=identifier,
                timecode=lines[timecode_pos].strip(),
                text="\n".join(line.rstrip() for line in lines[timecode_pos + 1:]).strip(),
            )
        )

    if not any(isinstance(block, VttCue) for block in parsed):
        raise ValueError("Nenhum cue VTT encontrado.")

    return parsed


def rebuild_vtt(blocks: List[Block]) -> str:
    parts: List[str] = []

    for block in blocks:
        if isinstance(block, RawBlock):
            parts.append(block.content.strip("\n"))
            continue

        cue_lines = []
        if block.identifier:
            cue_lines.append(block.identifier)

        cue_lines.append(block.timecode)
        cue_lines.append(block.text)
        parts.append("\n".join(cue_lines).strip("\n"))

    return "\n\n".join(parts) + "\n"


def protect_ellipsis(text: str) -> str:
    return text.replace("...", "§ELLIPSIS§")


def restore_ellipsis(text: str) -> str:
    return text.replace("§ELLIPSIS§", "...")


def normalize_dash_characters(text: str) -> str:
    """
    Converte travessões em hífen antes das regras de diálogo e quebra de linha.
    """
    return text.replace("—", "-").replace("–", "-")


def normalize_dialogue_marker_spacing(line: str) -> str:
    """
    Remove espaço inútil após marcador de diálogo.

    Exemplo:
    "- Por favor." vira "-Por favor."

    A regra só atua no início da fala/linha.
    Não altera hífen no meio de palavras.
    """
    return re.sub(r"^-\s+", "-", line.strip())


def split_inline_dialogue_markers(line: str) -> List[str]:
    """
    Separa diálogo inline marcado com hífen.

    Exemplo:
    "Monsenhor, por favor. -Por favor."
    vira:
    "Monsenhor, por favor."
    "-Por favor."

    Não separa hífen dentro de palavra.
    """
    line = line.strip()
    if not line:
        return []

    parts = re.split(r"\s+(?=-\s*[A-Za-zÀ-ÿ0-9])", line)
    return [normalize_dialogue_marker_spacing(part) for part in parts if part.strip()]


def clean_text(text: str) -> str:
    """
    Limpeza segura:
    - Remove <i> e </i>.
    - Converte <br>, <br/> e <br /> em separador interno.
    - Não mexe em </br>.
    - Preserva reticências.
    - Converte travessão de diálogo em hífen antes das quebras.
    - Separa falas inline com " -".
    """
    text = normalize_dash_characters(normalize_newlines(text))
    text = ITALIC_TAG_RE.sub("", text)
    text = BR_TAG_RE.sub("\n", text)

    protected = protect_ellipsis(text)

    cleaned_lines = []
    for line in protected.split("\n"):
        line = MULTISPACE_RE.sub(" ", line).strip()

        # Remove espaço antes de pontuação.
        line = re.sub(r"\s+([,.!?;:])", r"\1", line)

        # Espaço depois de pontuação sem afetar reticências protegidas.
        line = re.sub(r"([,.!?;:])([^\s])", r"\1 \2", line)

        line = restore_ellipsis(line)

        if line:
            cleaned_lines.extend(split_inline_dialogue_markers(normalize_dialogue_marker_spacing(line)))

    return "\n".join(cleaned_lines).strip()



def find_suspicious_characters_in_text(text: str) -> List[Dict[str, Any]]:
    """
    Localiza caracteres suspeitos no texto da legenda.

    Importante:
    - Não substitui nada automaticamente.
    - Apenas registra para revisão manual.
    """
    findings: List[Dict[str, Any]] = []

    for pos, ch in enumerate(text):
        if ch in "\n\t ":
            continue

        is_allowed = ch in ALLOWED_SYMBOLS_EXTRA
        is_explicit_suspicious = ch in SUSPICIOUS_EXPLICIT_CHARS

        if not is_allowed or is_explicit_suspicious:
            findings.append({
                "character": ch,
                "unicode": f"U+{ord(ch):04X}",
                "position": pos,
                "reason": "explicit_suspicious" if is_explicit_suspicious else "outside_allowed_character_set"
            })

    return findings


def validate_suspicious_characters(blocks: List[Block]) -> List[Dict[str, Any]]:
    """
    Varre todos os cues em busca de caracteres estranhos.
    """
    warnings: List[Dict[str, Any]] = []

    for block in blocks:
        if not isinstance(block, VttCue):
            continue

        findings = find_suspicious_characters_in_text(block.text)
        if findings:
            warnings.append({
                "index": block.index,
                "timecode": block.timecode,
                "text": block.text,
                "findings": findings
            })

    return warnings


def visible_char_count(text: str) -> int:
    return len(" ".join(text.split()))


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def time_weight(text: str) -> int:
    return max(1, len(re.sub(r"\s+", "", text)))


def detect_timecode_format(tc: str) -> str:
    if re.match(r"^\d{2}:\d{2}:\d{2}:\d{2}$", tc):
        return "frame_hh"
    if re.match(r"^\d{2}:\d{2}:\d{2}$", tc):
        return "frame_mm"
    if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", tc):
        return "ms_hh"
    if re.match(r"^\d{2}:\d{2}\.\d{3}$", tc):
        return "ms_mm"
    raise ValueError(f"Formato de timecode não reconhecido: {tc}")


def timecode_to_frames(tc: str) -> int:
    tc = tc.strip()
    fmt = detect_timecode_format(tc)

    if fmt == "frame_hh":
        h, m, s, f = [int(x) for x in tc.split(":")]
        return (((h * 60 + m) * 60 + s) * FPS) + f

    if fmt == "frame_mm":
        m, s, f = [int(x) for x in tc.split(":")]
        return ((m * 60 + s) * FPS) + f

    if fmt == "ms_hh":
        hms, ms_s = tc.split(".")
        h, m, s = [int(x) for x in hms.split(":")]
        ms = int(ms_s)
        return round(((h * 3600 + m * 60 + s) * FPS) + (ms / 1000 * FPS))

    if fmt == "ms_mm":
        mmss, ms_s = tc.split(".")
        m, s = [int(x) for x in mmss.split(":")]
        ms = int(ms_s)
        return round(((m * 60 + s) * FPS) + (ms / 1000 * FPS))

    raise ValueError(f"Formato de timecode inválido: {tc}")


def frames_to_timecode(frames: int, fmt: str) -> str:
    if frames < 0:
        frames = 0

    f = frames % FPS
    total_seconds = frames // FPS
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60

    if fmt == "frame_hh":
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    if fmt == "frame_mm":
        total_m = total_minutes
        return f"{total_m:02d}:{s:02d}:{f:02d}"

    ms = round((f / FPS) * 1000)

    if ms >= 1000:
        ms = 0
        total_seconds += 1
        s = total_seconds % 60
        total_minutes = total_seconds // 60
        m = total_minutes % 60
        h = total_minutes // 60

    if fmt == "ms_hh":
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    if fmt == "ms_mm":
        total_m = total_minutes
        return f"{total_m:02d}:{s:02d}.{ms:03d}"

    raise ValueError(f"Formato de saída inválido: {fmt}")


def parse_timecode_line(timecode_line: str) -> Tuple[int, int, str, str]:
    m = TIMECODE_RE.match(timecode_line.strip())
    if not m:
        raise ValueError(f"Linha de timecode inválida: {timecode_line}")

    start_tc = m.group("start")
    end_tc = m.group("end")
    settings = m.group("settings") or ""
    fmt = detect_timecode_format(start_tc)

    return timecode_to_frames(start_tc), timecode_to_frames(end_tc), settings, fmt


def build_timecode_line(start: int, end: int, settings: str, fmt: str) -> str:
    return f"{frames_to_timecode(start, fmt)} --> {frames_to_timecode(end, fmt)}{settings}"


def is_isolated_e_at_start(text: str) -> bool:
    """
    True apenas para conjunção "e" isolada no começo de um trecho.
    Ex.: "e abotoaduras" => True
    Ex.: "entre amigos" => False
    """
    return bool(re.match(r"^e\s+", text.strip(), flags=re.IGNORECASE))


def split_starts_with_isolated_e(right: str) -> bool:
    """
    Verifica se o lado direito começa com "e" conjunção isolada.
    Isso implica que a quebra ocorreu antes de " e ".
    """
    return is_isolated_e_at_start(right)


def score_break(text: str, pos: int, target: int) -> int:
    left = text[:pos].rstrip()
    right = text[pos:].lstrip()

    if not left or not right:
        return -100000

    score = 0
    score -= abs(len(left) - target) * 8

    if left[-1] in STRONG_PUNCTUATION:
        score += 300
    elif left[-1] in SOFT_PUNCTUATION:
        score += 250

    # Quebra antes de "e" isolado é permitida e pode ser boa.
    # Segurança: só funciona porque right precisa começar com "e ".
    if split_starts_with_isolated_e(right):
        score += 120

    first_right = right.split(" ", 1)[0]

    if first_right.startswith(tuple(PUNCTUATION)):
        score -= 1000

    if len(first_right) <= 2 and any(ch in PUNCTUATION for ch in first_right):
        score -= 1000

    bad_endings = {
        "a", "o", "as", "os", "um", "uma", "uns", "umas",
        "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
        "para", "por", "com", "sem", "ou", "que", "se", "mas",
        "como", "quando", "porque", "pra"
    }

    # Não inclui "e" aqui, porque "e" pode iniciar linha de continuação.
    last = left.split()[-1].lower().strip(PUNCTUATION)
    if last in bad_endings:
        score -= 180

    if len(right) < 10 and len(left) > 20:
        score -= 350

    if len(left) < 10 and len(right) > 20:
        score -= 350

    return score


def best_two_line_split(text: str) -> Optional[List[str]]:
    """
    Tenta dividir texto em 2 linhas balanceadas,
    ambas com no máximo 33 caracteres.
    """
    text = " ".join(text.split()).strip()

    if len(text) <= MAX_CHARS_PER_LINE:
        return [text]

    spaces = [m.start() for m in re.finditer(r" ", text)]
    if not spaces:
        return [text] if len(text) <= MAX_CHARS_PER_LINE else None

    valid = []
    for p in spaces:
        left = text[:p].rstrip()
        right = text[p:].lstrip()

        if len(left) <= MAX_CHARS_PER_LINE and len(right) <= MAX_CHARS_PER_LINE:
            valid.append(p)

    if not valid:
        return None

    target = len(text) // 2
    best = max(valid, key=lambda p: score_break(text, p, target))

    return [text[:best].rstrip(), text[best:].lstrip()]


def wrap_text_to_lines(text: str) -> List[str]:
    """
    Quebra em linhas com limite fixo de 33 caracteres.
    """
    text = " ".join(text.split()).strip()

    if not text:
        return []

    if len(text) <= MAX_CHARS_PER_LINE:
        return [text]

    balanced = best_two_line_split(text)
    if balanced is not None:
        return balanced

    lines: List[str] = []
    remaining = text

    while len(remaining) > MAX_CHARS_PER_LINE:
        spaces = [m.start() for m in re.finditer(r" ", remaining)]

        if not spaces:
            lines.append(remaining)
            return lines

        candidates = [p for p in spaces if len(remaining[:p].rstrip()) <= MAX_CHARS_PER_LINE]

        if not candidates:
            first_space = spaces[0]
            lines.append(remaining[:first_space].rstrip())
            remaining = remaining[first_space:].lstrip()
            continue

        best = max(candidates, key=lambda p: score_break(remaining, p, MAX_CHARS_PER_LINE))
        left = remaining[:best].rstrip()
        right = remaining[best:].lstrip()

        if not left:
            break

        lines.append(left)
        remaining = right

    if remaining:
        lines.append(remaining)

    return lines


def format_cue_text(text: str) -> str:
    """
    Formata texto final do cue.
    Nunca retorna mais de 2 linhas.
    Cada linha terá no máximo 33 caracteres, exceto palavra única maior que 33.
    """
    raw_lines = [normalize_dialogue_marker_spacing(line) for line in text.splitlines() if line.strip()]

    if not raw_lines:
        return ""

    # Preserva diálogo: linhas iniciadas com hífen ficam separadas.
    if len(raw_lines) >= 2 and any(line.startswith("-") for line in raw_lines):
        compact = [" ".join(line.split()) for line in raw_lines]

        if len(compact) <= 2 and all(len(line) <= MAX_CHARS_PER_LINE for line in compact):
            return "\n".join(compact)

        output = []
        for line in compact:
            output.extend(wrap_text_to_lines(line))
        return "\n".join(output[:MAX_LINES_PER_CUE])

    plain = " ".join(raw_lines)

    if len(plain) <= MAX_CHARS_PER_LINE:
        return plain

    lines = wrap_text_to_lines(plain)
    return "\n".join(lines[:MAX_LINES_PER_CUE])


def is_created_orphan_part(text: str) -> bool:
    """
    Proteção contra parte criada artificialmente muito fraca.
    Só é usada durante divisão automática.
    Blocos curtos originais NÃO são problema.
    """
    clean = " ".join(text.split()).strip()
    return (
        visible_char_count(clean) < MIN_CREATED_PART_CHARS
        or word_count(clean) < MIN_CREATED_PART_WORDS
    )


def score_cue_split(text: str, pos: int, target: int) -> int:
    left = text[:pos].rstrip()
    right = text[pos:].lstrip()

    if not left or not right:
        return -100000

    score = 0
    score -= abs(len(left) - target) * 5

    if left[-1] in STRONG_PUNCTUATION:
        score += 500
    elif left[-1] in SOFT_PUNCTUATION:
        score += 420

    # Quebrar antes de "e" isolado pode ser bom quando preserva adição.
    if split_starts_with_isolated_e(right):
        score += 160

    first_right = right.split(" ", 1)[0]
    first_right_clean = first_right.lower().strip(PUNCTUATION)

    if first_right.startswith(tuple(PUNCTUATION)):
        score -= 1500

    if first_right_clean in {"mas", "porque", "então", "entao", "porém", "porem"}:
        score += 120

    # Não usa "e" aqui por letra; o "e" só é avaliado por split_starts_with_isolated_e().
    if is_created_orphan_part(left):
        score -= 350

    if is_created_orphan_part(right):
        score -= 450

    bad_endings = {
        "a", "o", "as", "os", "um", "uma", "uns", "umas",
        "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
        "para", "por", "com", "sem", "ou", "que", "se", "mas",
        "como", "quando", "porque", "pra"
    }

    last = left.split()[-1].lower().strip(PUNCTUATION)
    if last in bad_endings:
        score -= 300

    return score


def would_fit_in_one_or_two_lines(text: str) -> bool:
    lines = wrap_text_to_lines(text)
    if len(lines) > MAX_LINES_PER_CUE:
        return False
    return all(len(line) <= MAX_CHARS_PER_LINE for line in lines)


def has_dialogue_lines(text: str) -> bool:
    lines = [normalize_dialogue_marker_spacing(line) for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and any(line.startswith("-") for line in lines)


def split_dialogue_parts(text: str) -> List[str]:
    """
    Preserva falas de diálogo sem juntá-las indevidamente.
    """
    lines = [normalize_dialogue_marker_spacing(line) for line in text.splitlines() if line.strip()]

    if not has_dialogue_lines(text):
        return []

    parts: List[str] = []
    current: List[str] = []

    for line in lines:
        candidate = "\n".join(current + [line]) if current else line

        if (
            len(current) < MAX_LINES_PER_CUE
            and visible_char_count(candidate) <= MAX_CHARS_PER_CUE
            and all(len(x) <= MAX_CHARS_PER_LINE for x in candidate.splitlines())
        ):
            current.append(line)
        else:
            if current:
                parts.append("\n".join(current))
            current = [line]

    if current:
        parts.append("\n".join(current))

    return parts


def split_text_into_cue_parts(text: str) -> List[str]:
    """
    Divide texto em partes válidas:
    - até 2 linhas;
    - 33 caracteres por linha;
    - até 66 caracteres por cue;
    - não separa palavras;
    - não quebra antes de pontuação;
    - "e" só como conjunção isolada: espaço + e + espaço.
    """
    text = clean_text(text)

    dialogue_parts = split_dialogue_parts(text)
    if dialogue_parts:
        final_parts = []
        for part in dialogue_parts:
            if would_fit_in_one_or_two_lines(part):
                final_parts.append(part)
            else:
                final_parts.extend(split_text_into_cue_parts(" ".join(part.split())))
        return final_parts

    text = " ".join(text.split()).strip()

    if visible_char_count(text) <= MAX_CHARS_PER_CUE and would_fit_in_one_or_two_lines(text):
        return [text]

    parts: List[str] = []
    remaining = text

    while remaining:
        if visible_char_count(remaining) <= MAX_CHARS_PER_CUE and would_fit_in_one_or_two_lines(remaining):
            parts.append(remaining)
            break

        spaces = [m.start() for m in re.finditer(r" ", remaining)]

        if not spaces:
            parts.append(remaining)
            break

        candidates = [
            p for p in spaces
            if visible_char_count(remaining[:p].rstrip()) <= MAX_CHARS_PER_CUE
            and would_fit_in_one_or_two_lines(remaining[:p].rstrip())
        ]

        if not candidates:
            candidates = [
                p for p in spaces
                if visible_char_count(remaining[:p].rstrip()) <= MAX_CHARS_PER_CUE
            ]

        if not candidates:
            first_space = spaces[0]
            parts.append(remaining[:first_space].rstrip())
            remaining = remaining[first_space:].lstrip()
            continue

        best = max(candidates, key=lambda p: score_cue_split(remaining, p, MAX_CHARS_PER_CUE))
        left = remaining[:best].rstrip()
        right = remaining[best:].lstrip()

        if not left:
            break

        parts.append(left)
        remaining = right

    # Segunda passada: se a última parte criada ficou órfã e existe parte anterior,
    # tenta recombinar e redistribuir apenas dentro do mesmo cue original.
    if len(parts) >= 2 and is_created_orphan_part(parts[-1]):
        recombined = parts[-2] + " " + parts[-1]
        replacement = split_text_into_cue_parts_without_orphan_retry(recombined)
        if len(replacement) >= 1:
            parts = parts[:-2] + replacement

    return parts


def split_text_into_cue_parts_without_orphan_retry(text: str) -> List[str]:
    """
    Variante sem chamada recursiva de proteção contra órfão,
    para evitar loop infinito.
    """
    text = " ".join(clean_text(text).split()).strip()

    if visible_char_count(text) <= MAX_CHARS_PER_CUE and would_fit_in_one_or_two_lines(text):
        return [text]

    parts: List[str] = []
    remaining = text

    while remaining:
        if visible_char_count(remaining) <= MAX_CHARS_PER_CUE and would_fit_in_one_or_two_lines(remaining):
            parts.append(remaining)
            break

        spaces = [m.start() for m in re.finditer(r" ", remaining)]

        if not spaces:
            parts.append(remaining)
            break

        candidates = [
            p for p in spaces
            if visible_char_count(remaining[:p].rstrip()) <= MAX_CHARS_PER_CUE
            and would_fit_in_one_or_two_lines(remaining[:p].rstrip())
        ]

        if not candidates:
            candidates = [
                p for p in spaces
                if visible_char_count(remaining[:p].rstrip()) <= MAX_CHARS_PER_CUE
            ]

        if not candidates:
            first_space = spaces[0]
            parts.append(remaining[:first_space].rstrip())
            remaining = remaining[first_space:].lstrip()
            continue

        best = max(candidates, key=lambda p: score_cue_split(remaining, p, MAX_CHARS_PER_CUE))
        left = remaining[:best].rstrip()
        right = remaining[best:].lstrip()

        parts.append(left)
        remaining = right

    return parts


def distribute_timecodes(original_timecode: str, parts: List[str]) -> Tuple[List[str], List[str]]:
    """
    Divide apenas o intervalo interno do cue original.
    Não altera nenhum cue vizinho.
    """
    warnings = []

    if len(parts) == 1:
        return [original_timecode], warnings

    start_frame, end_frame, settings, fmt = parse_timecode_line(original_timecode)

    total_frames = end_frame - start_frame + 1

    if total_frames < len(parts):
        warnings.append("Duração curta demais para dividir corretamente.")
        total_frames = len(parts)

    weights = [time_weight(part) for part in parts]
    total_weight = sum(weights)

    durations = []
    used = 0

    for i, weight in enumerate(weights):
        if i == len(weights) - 1:
            duration = total_frames - used
        else:
            duration = max(1, round(total_frames * weight / total_weight))
            used += duration

        durations.append(max(1, duration))

    diff = total_frames - sum(durations)
    durations[-1] += diff

    for _ in range(10):
        changed = False
        for i in range(len(parts)):
            for j in range(len(parts)):
                if weights[i] > weights[j] and durations[i] < durations[j] and durations[j] > 1:
                    durations[i] += 1
                    durations[j] -= 1
                    changed = True
        if not changed:
            break

    timecodes = []
    current_start = start_frame

    for i, duration in enumerate(durations):
        current_end = current_start + duration - 1

        if i == len(durations) - 1:
            current_end = end_frame

        if current_end < current_start:
            current_end = current_start

        timecodes.append(build_timecode_line(current_start, current_end, settings, fmt))
        current_start = current_end + FRAME_STEP

    previous_end = None
    for tc in timecodes:
        s, e, _, _ = parse_timecode_line(tc)
        if previous_end is not None:
            if s <= previous_end:
                warnings.append(f"Sobreposição detectada: {tc}")
            if s != previous_end + 1:
                warnings.append(f"Intervalo diferente de 1 frame antes de: {tc}")
        previous_end = e

    return timecodes, warnings


def edit_cue(cue: VttCue) -> Tuple[List[VttCue], Dict[str, Any]]:
    cleaned = clean_text(cue.text)

    parts = split_text_into_cue_parts(cleaned)
    split_applied = len(parts) > 1

    timecodes, warnings = distribute_timecodes(cue.timecode, parts)

    new_cues: List[VttCue] = []

    for i, (part, timecode) in enumerate(zip(parts, timecodes), start=1):
        formatted = format_cue_text(part)

        new_cues.append(
            VttCue(
                index=cue.index,
                identifier=cue.identifier if i == 1 else None,
                timecode=timecode,
                text=formatted,
            )
        )

    return new_cues, {
        "split_applied": split_applied,
        "parts_count": len(new_cues),
        "warnings": warnings,
    }



def validate_overlaps(blocks: List[Block]) -> List[Dict[str, Any]]:
    """
    Verifica sobreposição no arquivo final.
    Não corrige em cascata; apenas reporta no relatório.
    """
    warnings: List[Dict[str, Any]] = []
    previous = None

    for block in blocks:
        if not isinstance(block, VttCue):
            continue

        try:
            start, end, _, _ = parse_timecode_line(block.timecode)
        except Exception as exc:
            warnings.append({
                "index": block.index,
                "timecode": block.timecode,
                "problem": f"timecode_unreadable: {exc}"
            })
            continue

        if start > end:
            warnings.append({
                "index": block.index,
                "timecode": block.timecode,
                "problem": "start_after_end"
            })

        if previous is not None and start <= previous["end"]:
            warnings.append({
                "previous_index": previous["index"],
                "previous_timecode": previous["timecode"],
                "current_index": block.index,
                "current_timecode": block.timecode,
                "problem": "overlap"
            })

        previous = {
            "index": block.index,
            "timecode": block.timecode,
            "start": start,
            "end": end,
        }

    return warnings


def repair_overlapping_timecodes(blocks: List[Block]) -> Tuple[List[Block], List[Dict[str, Any]]]:
    """
    Corrige sobreposicoes entre cues consecutivos.

    Regra conservadora:
    - nao reordena cues;
    - nao mexe em RawBlock;
    - se o cue atual invade o anterior, move apenas o inicio do cue atual
      para 1 frame apos o fim anterior;
    - se o fim original ficaria antes do novo inicio, cria intervalo minimo
      de 1 frame.
    """
    repaired: List[Block] = []
    fixes: List[Dict[str, Any]] = []
    previous_end: Optional[int] = None

    for block in blocks:
        if not isinstance(block, VttCue):
            repaired.append(block)
            continue

        try:
            start, end, settings, fmt = parse_timecode_line(block.timecode)
        except Exception:
            repaired.append(block)
            continue

        original_start = start
        original_end = end
        original_timecode = block.timecode

        if start > end:
            end = start

        if previous_end is not None and start <= previous_end:
            start = previous_end + FRAME_STEP
            if end < start:
                end = start

        if start != original_start or end != original_end:
            new_timecode = build_timecode_line(start, end, settings, fmt)
            block = VttCue(
                index=block.index,
                identifier=block.identifier,
                timecode=new_timecode,
                text=block.text,
            )
            fixes.append({
                "index": block.index,
                "original_timecode": original_timecode,
                "new_timecode": new_timecode,
                "problem": "overlap_or_invalid_interval",
            })

        repaired.append(block)
        previous_end = end

    return repaired, fixes


def analyze_issues(blocks: List[Block]) -> Dict[str, List[Dict[str, Any]]]:
    long_lines = []
    long_cues = []
    too_many_lines = []
    remaining_italic_tags = []
    remaining_br_tags = []

    for block in blocks:
        if not isinstance(block, VttCue):
            continue

        if visible_char_count(block.text) > MAX_CHARS_PER_CUE:
            long_cues.append({
                "index": block.index,
                "timecode": block.timecode,
                "chars": visible_char_count(block.text),
                "text": block.text,
            })

        lines = block.text.splitlines()

        if len(lines) > MAX_LINES_PER_CUE:
            too_many_lines.append({
                "index": block.index,
                "timecode": block.timecode,
                "line_count": len(lines),
                "text": block.text,
            })

        if ITALIC_TAG_RE.search(block.text):
            remaining_italic_tags.append({
                "index": block.index,
                "timecode": block.timecode,
                "text": block.text,
            })

        if BR_TAG_RE.search(block.text):
            remaining_br_tags.append({
                "index": block.index,
                "timecode": block.timecode,
                "text": block.text,
            })

        for line_no, line in enumerate(lines, start=1):
            if len(line) > MAX_CHARS_PER_LINE:
                long_lines.append({
                    "index": block.index,
                    "timecode": block.timecode,
                    "line_number": line_no,
                    "length": len(line),
                    "line": line,
                })

    return {
        "long_lines": long_lines,
        "long_cues_over_66_chars": long_cues,
        "too_many_lines": too_many_lines,
        "remaining_italic_tags": remaining_italic_tags,
        "remaining_br_tags": remaining_br_tags,
        "overlap_warnings": validate_overlaps(blocks),
    }



def build_status(issues: Dict[str, Any]) -> str:
    """
    Define o status final do processamento.
    Retorna ATENÇÃO se houver qualquer problema estrutural relevante.
    """
    has_problem = any([
        len(issues.get("long_lines", [])) > 0,
        len(issues.get("long_cues_over_66_chars", [])) > 0,
        len(issues.get("too_many_lines", [])) > 0,
        len(issues.get("remaining_italic_tags", [])) > 0,
        len(issues.get("remaining_br_tags", [])) > 0,
        len(issues.get("overlap_warnings", [])) > 0,
        len(issues.get("suspicious_characters", [])) > 0,
    ])
    return "ATENÇÃO — REVISAR PROBLEMAS" if has_problem else "OK PARA REVISÃO"


def build_txt_report(report: Dict[str, Any]) -> str:
    """
    Gera relatório TXT legível para conferência rápida.
    """
    issues = report.get("remaining_issues", {})

    lines = [
        f"Arquivo: {report.get('file', '')}",
        f"Status: {report.get('status', '')}",
        "",
        f"FPS: {report.get('fps', '')}",
        f"Máximo de caracteres por linha: {report.get('max_chars_per_line', '')}",
        f"Máximo de linhas por cue: {report.get('max_lines_per_cue', '')}",
        f"Máximo de caracteres por cue: {report.get('max_chars_per_cue', '')}",
        "",
        f"Alterações: {report.get('changed_cues', 0)}",
        f"Legendas divididas: {report.get('split_cues', 0)}",
        "",
        "Validações:",
        f"- Linhas acima do limite: {len(issues.get('long_lines', []))}",
        f"- Blocos acima do limite: {len(issues.get('long_cues_over_66_chars', []))}",
        f"- Cues com linhas excessivas: {len(issues.get('too_many_lines', []))}",
        f"- Tags <i> restantes: {len(issues.get('remaining_italic_tags', []))}",
        f"- Tags <br> restantes: {len(issues.get('remaining_br_tags', []))}",
        f"- Sobreposições: {len(issues.get('overlap_warnings', []))}",
        f"- CARACTERES SUSPEITOS: {len(issues.get('suspicious_characters', []))}",
        "",
    ]

    if issues.get("suspicious_characters"):
        lines.append("========================================")
        lines.append("ATENÇÃO: CARACTERES SUSPEITOS ENCONTRADOS")
        lines.append("========================================")
        for item in issues.get("suspicious_characters", [])[:50]:
            lines.append(f"Cue: {item.get('index')} | Timecode: {item.get('timecode')}")
            lines.append(f"Texto: {item.get('text')}")
            for finding in item.get("findings", []):
                lines.append(
                    f"  - Caractere: {finding.get('character')} | "
                    f"Unicode: {finding.get('unicode')} | "
                    f"Posição: {finding.get('position')} | "
                    f"Motivo: {finding.get('reason')}"
                )
            lines.append("")
        lines.append("")

    if issues.get("overlap_warnings"):
        lines.append("Sobreposições encontradas:")
        for item in issues.get("overlap_warnings", [])[:30]:
            lines.append(str(item))
        lines.append("")

    if report.get("timecode_fixes"):
        lines.append("Timecodes corrigidos automaticamente:")
        for item in report.get("timecode_fixes", [])[:50]:
            lines.append(
                f"- Cue {item.get('index')}: "
                f"{item.get('original_timecode')} -> {item.get('new_timecode')}"
            )
        lines.append("")

    if issues.get("long_lines"):
        lines.append("Linhas acima do limite:")
        for item in issues.get("long_lines", [])[:30]:
            lines.append(str(item))
        lines.append("")

    if report.get("splits"):
        lines.append("Resumo de divisões:")
        for split in report.get("splits", [])[:50]:
            lines.append(
                f"- Cue original {split.get('original_index')} | "
                f"partes: {split.get('parts_count')} | "
                f"{split.get('original_timecode')}"
            )
        lines.append("")

    return "\n".join(lines) + "\n"

def process_file(input_file: Path, output_dir: Path, reports_dir: Path) -> None:
    content = read_text_file(input_file)
    blocks = parse_vtt(content)

    output_blocks: List[Block] = []
    changes = []
    splits = []

    for block in blocks:
        if isinstance(block, RawBlock):
            output_blocks.append(block)
            continue

        new_cues, info = edit_cue(block)
        output_blocks.extend(new_cues)

        after_preview = "\n\n".join(f"{cue.timecode}\n{cue.text}" for cue in new_cues)

        original_cleaned = clean_text(block.text)

        if block.text != "\n".join(cue.text for cue in new_cues) or info["split_applied"]:
            changes.append({
                "original_index": block.index,
                "original_timecode": block.timecode,
                "before": block.text,
                "cleaned_before_split": original_cleaned,
                "after": after_preview,
            })

        if info["split_applied"]:
            splits.append({
                "original_index": block.index,
                "original_timecode": block.timecode,
                "parts_count": info["parts_count"],
                "warnings": info["warnings"],
                "new_parts": [
                    {
                        "timecode": cue.timecode,
                        "text": cue.text,
                        "chars": visible_char_count(cue.text),
                        "line_count": len(cue.text.splitlines()),
                    }
                    for cue in new_cues
                ],
            })

    output_blocks, timecode_fixes = repair_overlapping_timecodes(output_blocks)

    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    output_file = make_unique_output_path(output_dir, input_file)
    report_file = reports_dir / f"{input_file.stem}_relatorio.json"
    report_txt_file = reports_dir / f"{input_file.stem}_relatorio.txt"

    issues = analyze_issues(output_blocks)

    status = build_status(issues)

    report = {
        "file": input_file.name,
        "mode": "vtt_automation_cms_integrado_download_edicao_upload_fix_status",
        "status": status,
        "fps": FPS,
        "max_chars_per_line": MAX_CHARS_PER_LINE,
        "max_lines_per_cue": MAX_LINES_PER_CUE,
        "max_chars_per_cue": MAX_CHARS_PER_CUE,
        "changed_cues": len(changes),
        "split_cues": len(splits),
        "timecode_fixes": timecode_fixes,
        "splits": splits,
        "remaining_issues": issues,
        "changes": changes,
    }

    write_text_file(output_file, rebuild_vtt(output_blocks))
    write_text_file(report_file, json.dumps(report, ensure_ascii=False, indent=2))
    write_text_file(report_txt_file, build_txt_report(report))
    log_event(f"Arquivo processado gerado: origem={input_file.resolve()} saida={output_file.resolve()}")

    summary = {
        "input_file": input_file.name,
        "output_file": str(output_file),
        "report_file": str(report_file),
        "report_txt_file": str(report_txt_file),
        "status": status,
        "changes": len(changes),
        "split_cues": len(splits),
        "timecode_fixes": len(timecode_fixes),
        "long_lines": len(issues["long_lines"]),
        "long_cues": len(issues["long_cues_over_66_chars"]),
        "too_many_lines": len(issues["too_many_lines"]),
        "remaining_italic_tags": len(issues["remaining_italic_tags"]),
        "remaining_br_tags": len(issues["remaining_br_tags"]),
        "overlaps": len(issues["overlap_warnings"]),
        "suspicious_characters": len(issues.get("suspicious_characters", [])),
    }

    print(f"OK: {input_file.name} -> {output_file}")
    print(f"STATUS: {summary['status']}")
    print(f"Alterações: {summary['changes']}")
    print(f"Legendas divididas: {summary['split_cues']}")
    print(f"Timecodes corrigidos: {summary['timecode_fixes']}")
    print(f"Linhas acima de 33 caracteres: {summary['long_lines']}")
    print(f"Blocos acima de 66 caracteres: {summary['long_cues']}")
    print(f"Cues com mais de 2 linhas: {summary['too_many_lines']}")
    print(f"Sobreposições: {summary['overlaps']}")
    print(f"Caracteres suspeitos: {summary['suspicious_characters']}")
    print(f"Tags <i> restantes: {summary['remaining_italic_tags']}")
    print(f"Tags <br> restantes: {summary['remaining_br_tags']}")

    return summary


def get_file_signature(path: Path) -> Dict[str, Any]:
    """
    Assinatura simples para saber se um arquivo já foi processado.

    Usa:
    - nome;
    - tamanho;
    - data de modificação.

    Se o mesmo arquivo for baixado novamente com outro tamanho/data,
    ele será considerado novo.
    """
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": round(stat.st_mtime, 3),
    }


def signature_key(signature: Dict[str, Any]) -> str:
    return f"{signature['name']}|{signature['size']}|{signature['mtime']}"


def load_processed_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {
            "processed": {},
            "last_processed": None,
        }

    try:
        return json.loads(read_text_file(state_path))
    except Exception:
        # Se o arquivo de estado corromper, não trava o script.
        return {
            "processed": {},
            "last_processed": None,
            "warning": "state_file_was_unreadable_and_was_reset",
        }


def save_processed_state(state_path: Path, state: Dict[str, Any]) -> None:
    write_text_file(state_path, json.dumps(state, ensure_ascii=False, indent=2))



def is_generated_output_file(path: Path) -> bool:
    """
    Evita que o script reprocesse arquivos gerados por ele mesmo.

    Exemplo ignorado:
    Men_subtitle_editado_20260602_204407.vtt
    """
    return bool(re.search(r"_editado_\d{8}_\d{6}\.vtt$", path.name, flags=re.IGNORECASE))


def is_probably_still_downloading(path: Path) -> bool:
    """
    Evita processar arquivos temporários ou vazios.
    Para downloads, o navegador geralmente usa extensão temporária,
    mas esta checagem também evita .vtt com tamanho 0.
    """
    if path.name.endswith((".crdownload", ".tmp", ".part")):
        return True

    try:
        return path.stat().st_size == 0
    except FileNotFoundError:
        return True


def pick_latest_unprocessed_vtt(input_dir: Path, state: Dict[str, Any]) -> Optional[Path]:
    """
    Escolhe apenas o .vtt mais recente que ainda não foi processado.

    Critério de "mais recente":
    - maior data de modificação do arquivo.

    Arquivos já registrados em .vtt_processados.json são ignorados.
    """
    processed = state.get("processed", {})

    candidates = []
    for file in input_dir.glob("*.vtt"):
        if not file.is_file():
            continue

        if is_probably_still_downloading(file):
            continue

        if is_generated_output_file(file):
            continue

        signature = get_file_signature(file)
        key = signature_key(signature)

        if key in processed:
            continue

        candidates.append(file)

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def mark_file_as_processed(state: Dict[str, Any], file: Path, output_file: Optional[Path] = None, report_file: Optional[Path] = None) -> None:
    signature = get_file_signature(file)
    key = signature_key(signature)

    state.setdefault("processed", {})
    state["processed"][key] = {
        "signature": signature,
        "output": str(output_file) if output_file else None,
        "report": str(report_file) if report_file else None,
    }
    state["last_processed"] = signature


def mark_existing_files_as_baseline(input_dir: Path, state_path: Path) -> int:
    """
    No modo --watch, evita processar todos os arquivos antigos da pasta de downloads.

    Ao iniciar o monitoramento, todos os .vtt que já existem na pasta são registrados
    como baseline/ignorados. Depois disso, somente arquivos novos, baixados após o
    script estar rodando, serão processados.

    Isso não altera os arquivos. Apenas registra no .vtt_processados.json.
    """
    state = load_processed_state(state_path)
    state.setdefault("processed", {})

    marked = 0

    for file in input_dir.glob("*.vtt"):
        if not file.is_file():
            continue

        if is_probably_still_downloading(file):
            continue

        signature = get_file_signature(file)
        key = signature_key(signature)

        if key in state["processed"]:
            continue

        state["processed"][key] = {
            "signature": signature,
            "output": None,
            "report": None,
            "baseline_ignored": True,
        }
        marked += 1

    if marked:
        state["baseline_initialized"] = True
        save_processed_state(state_path, state)

    return marked


def build_popup_message(summary: Dict[str, Any], state_path: Path) -> str:
    return (
        f"Arquivo processado: {summary['input_file']}\n"
        f"Origem: {summary.get('source_file', '')}\n"
        f"Saída aberta: {summary['output_file']}\n"
        f"Relatório: {summary['report_file']}\n\n"
        f"Alterações: {summary['changes']}\n"
        f"Legendas divididas: {summary['split_cues']}\n"
        f"Linhas acima de 33 caracteres: {summary['long_lines']}\n"
        f"Blocos acima de 66 caracteres: {summary['long_cues']}\n"
        f"Cues com mais de 2 linhas: {summary['too_many_lines']}\n"
        f"Tags <i> restantes: {summary['remaining_italic_tags']}\n"
        f"Tags <br> restantes: {summary['remaining_br_tags']}\n\n"
        f"Controle: {state_path}"
    )



# ============================================================
# CMS FLOW - DOWNLOAD + EDIÇÃO + UPLOAD
# ============================================================

CMS_BASE_URL = "https://dtv-cms-ui.tbxnet.com/contents"
CMS_HOME_URL = "https://dtv-cms-ui.tbxnet.com"
CMS_USER_DATA_DIR = Path(__file__).resolve().parent / "perfil_navegador_cms"
CMS_PROFILE_LOCK = CMS_USER_DATA_DIR / "lockfile"
CMS_DOWNLOAD_TIMEOUT_MS = 120_000
CMS_PAGE_TIMEOUT_MS = 60_000
CMS_LANGUAGE = "Portuguese"
CMS_STOP_FILE = Path(__file__).resolve().parent / "logs" / "parar_fluxo.flag"

CMS_LANGUAGE_LABELS = {
    "pt-br": "Portuguese",
    "es": "Spanish",
}

def set_cms_language(language: str) -> None:
    global CMS_LANGUAGE
    CMS_LANGUAGE = CMS_LANGUAGE_LABELS.get((language or "pt-br").lower(), "Portuguese")


def cms_clear_stop_request() -> None:
    try:
        CMS_STOP_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def cms_stop_requested() -> bool:
    return CMS_STOP_FILE.exists()


def cms_profile_has_running_browser() -> Optional[bool]:
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


def cms_require_profile_available() -> None:
    if cms_manual_browser_open():
        raise CmsProfileLockedError(
            "O perfil do CMS esta aberto no Chrome. Feche a janela do Change Project antes de processar/uploadar."
        )


def cms_log_stop(content_id: str = "") -> None:
    msg = "Parada solicitada pela interface. Nenhum novo conteúdo será iniciado."
    if content_id:
        msg += f" Próximo conteúdo não iniciado: {content_id}"
    print("=" * 80)
    print(msg)
    print("=" * 80)



def cms_url(content_id: str) -> str:
    return f"{CMS_BASE_URL}/{content_id}"


class CmsNoSubtitleError(RuntimeError):
    pass


class CmsTransientError(RuntimeError):
    pass


class CmsProfileLockedError(RuntimeError):
    pass


def cms_wait_page_ready(page, timeout_ms: int = 15_000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def clean_content_title(value: str, content_id: str = "") -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-–—|")
    if content_id:
        title = re.sub(re.escape(content_id), "", title, flags=re.IGNORECASE).strip(" \t\r\n-–—|")
    title = re.sub(r"\b(SubNexus|CMS|Contents?)\b", "", title, flags=re.IGNORECASE).strip(" \t\r\n-–—|")
    return title[:180]


def title_from_filename(filename: str, content_id: str) -> str:
    stem = Path(filename or "").stem
    stem = re.sub(r"(?i)(_original|_subtitle|_legenda|subtitle|legenda)$", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    return clean_content_title(stem, content_id)


def cms_extract_content_title(page, content_id: str = "") -> str:
    """
    Tenta obter o titulo na pagina ja aberta do CMS.
    Nao navega nem espera rede: a leitura precisa ser barata para nao atrasar o fluxo.
    """
    try:
        candidates = page.evaluate(
            """
            () => {
              const out = [];
              const add = (value) => {
                const text = String(value || '').replace(/\\s+/g, ' ').trim();
                if (text && text.length >= 3 && text.length <= 220) out.push(text);
              };
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              for (const el of document.querySelectorAll('h1,h2,h3,[data-testid],[aria-label],input,textarea')) {
                if (!visible(el)) continue;
                const hint = [
                  el.getAttribute('data-testid') || '',
                  el.getAttribute('aria-label') || '',
                  el.getAttribute('name') || '',
                  el.getAttribute('placeholder') || '',
                  el.className || ''
                ].join(' ').toLowerCase();
                if (['title', 'titulo', 'name', 'nome'].some(k => hint.includes(k))) {
                  add(el.value || el.innerText || el.textContent);
                }
              }
              for (const el of document.querySelectorAll('h1,h2')) {
                if (visible(el)) add(el.innerText || el.textContent);
              }
              add(document.title);
              return out.slice(0, 12);
            }
            """,
        )
        for candidate in candidates or []:
            title = clean_content_title(candidate, content_id)
            if title and not title.lower().startswith("http"):
                return title
    except Exception:
        pass
    return ""


def cms_append_timing(row: Dict[str, Any], stage: str, seconds: float, status: str = "") -> None:
    import csv

    try:
        logs_dir = Path(__file__).resolve().parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timing_file = logs_dir / "cms_fluxo_tempos.csv"

        fieldnames = [
            "datetime",
            "content_id",
            "content_title",
            "stage",
            "seconds",
            "status",
        ]

        exists = timing_file.exists()
        with timing_file.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            if not exists:
                writer.writeheader()
            writer.writerow({
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content_id": row.get("content_id", ""),
                "content_title": row.get("content_title", ""),
                "stage": stage,
                "seconds": f"{float(seconds):.3f}",
                "status": status or row.get("status", ""),
            })
    except Exception:
        pass


@contextmanager
def cms_timed_stage(row: Dict[str, Any], stage: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        cms_append_timing(row, stage, time.perf_counter() - start)


def cms_status_from_exception(exc: Exception) -> str:
    if isinstance(exc, CmsNoSubtitleError):
        return "Sem legenda"
    if isinstance(exc, (CmsTransientError, PlaywrightTimeoutError)):
        return "Erro CMS"

    text = str(exc).lower()
    cms_markers = [
        "timeout",
        "locator",
        "navigation",
        "page",
        "download subtitle",
        "upload subtitle",
        "input[type='file']",
    ]
    if any(marker in text for marker in cms_markers):
        return "Erro CMS"

    return "Erro"


def cms_set_status(row: Dict[str, Any], status: str, error: str = "") -> None:
    row["status"] = status
    if error:
        row["error"] = error
    cms_append_status(row)


def cms_prepare_page(context):
    """
    Reaproveita uma aba util do contexto persistente e fecha abas vazias extras.

    O Chromium costuma abrir uma aba about:blank quando o perfil persistente
    inicia. Se usarmos essa aba sem limpar o restante, o usuario ve varias abas
    acumuladas entre download e upload.
    """
    pages = list(context.pages)
    selected = None

    for candidate in pages:
        if str(candidate.url or "").startswith(CMS_BASE_URL):
            selected = candidate
            break

    if selected is None:
        for candidate in pages:
            url = str(candidate.url or "")
            if url and url != "about:blank":
                selected = candidate
                break

    if selected is None:
        selected = pages[0] if pages else context.new_page()

    for candidate in list(context.pages):
        if candidate == selected:
            continue
        if str(candidate.url or "") in {"", "about:blank"}:
            try:
                candidate.close()
            except Exception:
                pass

    try:
        selected.bring_to_front()
    except Exception:
        pass

    return selected


def unique_path(directory: Path, filename: str) -> Path:
    """
    Retorna caminho único sem sobrescrever arquivo existente.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = directory / f"{stem}_{stamp}{suffix}"

    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{stamp}_{counter}{suffix}"
        counter += 1

    return candidate


def cms_download_subtitle(page, content_id: str, input_dir: Path) -> Path:
    """
    Baixa a legenda do CMS e mantém o nome original sugerido pelo site.
    A pasta entrada preserva o arquivo bruto, sem edição e sem renomear para content_id.
    """
    url = cms_url(content_id)
    input_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(f"CMS DOWNLOAD: {content_id}")
    print(url)

    page.goto(url, wait_until="domcontentloaded", timeout=CMS_PAGE_TIMEOUT_MS)
    cms_wait_page_ready(page)

    download_button = page.get_by_role("button", name="DOWNLOAD SUBTITLE")
    try:
        download_button.wait_for(state="visible", timeout=12_000)
    except PlaywrightTimeoutError as exc:
        body_count = page.locator("body").count()
        if body_count:
            raise CmsNoSubtitleError("CMS carregou, mas nao exibiu DOWNLOAD SUBTITLE.") from exc
        raise CmsTransientError("CMS nao respondeu corretamente ao abrir a pagina de download.") from exc

    with page.expect_download(timeout=CMS_DOWNLOAD_TIMEOUT_MS) as download_info:
        download_button.click()

    download = download_info.value
    suggested_name = download.suggested_filename or f"{content_id}_original.vtt"

    # Mantém nome original. Só adiciona sufixo se já existir para não sobrescrever.
    original_path = unique_path(input_dir, suggested_name)
    download.save_as(str(original_path))

    print(f"Original salvo sem alteração em: {original_path}")
    return original_path


def cms_make_final_edited_file(content_id: str, processed_file: Path, output_dir: Path) -> Path:
    """
    Copia o arquivo processado para o nome final de upload:
    saida/{content_id}.vtt

    Não altera o arquivo original em entrada.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    final_path = output_dir / f"{content_id}.vtt"

    # Para upload, queremos nome fixo por content_id.
    # Se existir, substitui o editado anterior, mas nunca mexe no original da entrada.
    if final_path.exists():
        final_path.unlink()

    shutil.copy2(processed_file, final_path)
    print(f"Arquivo final para upload: {final_path}")

    return final_path


def cms_upload_subtitle(page, content_id: str, edited_file: Path) -> bool:
    """
    Faz upload da legenda editada no CMS.
    """
    if not edited_file.exists():
        raise FileNotFoundError(f"Arquivo editado não encontrado para upload: {edited_file}")

    url = cms_url(content_id)

    print("=" * 80)
    print(f"CMS UPLOAD: {content_id}")
    print(url)
    print(f"Arquivo: {edited_file}")

    page.goto(url, wait_until="domcontentloaded", timeout=CMS_PAGE_TIMEOUT_MS)
    cms_wait_page_ready(page)

    upload_button = page.get_by_role("button", name="UPLOAD SUBTITLE")
    upload_button.wait_for(state="visible", timeout=20_000)
    upload_button.click()

    dialog = page.get_by_role("dialog")
    try:
        dialog.last.wait_for(state="visible", timeout=10_000)
        upload_scope = dialog.last
    except Exception:
        upload_scope = page

    file_inputs = upload_scope.locator("input[type='file']")
    if file_inputs.count() == 0:
        try:
            upload_scope.get_by_text("Drop a file to upload, or").click()
            file_inputs.first.wait_for(state="attached", timeout=5_000)
        except Exception:
            pass
        file_inputs = upload_scope.locator("input[type='file']")

    if file_inputs.count() == 0:
        raise RuntimeError("Nenhum input[type='file'] encontrado para anexar a legenda.")

    file_inputs.first.set_input_files(str(edited_file))

    language_combo = upload_scope.get_by_role("combobox", name=re.compile("Language", re.IGNORECASE))
    if language_combo.count() == 0:
        language_combo = upload_scope.locator("[role='combobox']")
    if language_combo.count() == 0:
        raise RuntimeError("Campo Language nao encontrado no modal de upload.")

    language_combo.last.click()

    language_options = [CMS_LANGUAGE]
    if CMS_LANGUAGE == "Portuguese":
        language_options = ["Portuguese Brazil", "Portuguese"]
    elif CMS_LANGUAGE == "Spanish":
        language_options = ["Spanish"]

    selected = False
    for option_name in language_options:
        option = page.get_by_role("option", name=option_name, exact=True)
        try:
            option.first.wait_for(state="visible", timeout=3_000)
            option.first.click()
            selected = True
            break
        except Exception:
            continue

    if not selected:
        raise RuntimeError(f"Opcao de idioma nao encontrada no upload: {CMS_LANGUAGE}")

    submit_button = upload_scope.get_by_role("button", name=re.compile(r"^Upload$", re.IGNORECASE))
    if submit_button.count() == 0:
        submit_button = page.get_by_role("button", name=re.compile(r"^Upload$", re.IGNORECASE))
    submit_button.last.click()
    cms_wait_page_ready(page, timeout_ms=20_000)

    print("Upload acionado. Verifique visualmente se o CMS confirmou o envio.")
    return True


def cms_append_status(row: Dict[str, Any]) -> None:
    import csv

    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status_file = logs_dir / "cms_fluxo_status.csv"

    fieldnames = [
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

    exists = status_file.exists()

    with status_file.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        if not exists:
            writer.writeheader()
        row = dict(row)
        row["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow({k: row.get(k, "") for k in fieldnames})


def run_cms_flow(
    content_ids: List[str],
    input_dir: Path,
    output_dir: Path,
    reports_dir: Path,
    reviewed_dir: Path,
    do_upload: bool = True,
    open_edited_file: bool = False,
) -> None:
    """
    Fluxo integrado de validação:
    1. Baixa legenda do CMS.
    2. Mantém original intacto em entrada/.
    3. Edita com o motor atual.
    4. Gera saida/{content_id}.vtt.
    5. Faz upload do arquivo editado.
    """
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright não está instalado. Rode: py -m pip install playwright && py -m playwright install chromium"
        )

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    reviewed_dir.mkdir(parents=True, exist_ok=True)
    cms_clear_stop_request()
    cms_require_profile_available()

    print("=" * 80)
    print("FLUXO CMS: DOWNLOAD + EDIÇÃO + UPLOAD")
    print("=" * 80)
    print(f"Total de conteúdos: {len(content_ids)}")
    print(f"Upload habilitado: {do_upload}")
    print("Originais: entrada/ com nome original do site")
    print("Editados: saida/{content_id}.vtt")
    print("=" * 80)

    with sync_playwright() as p:
        browser_path = find_installed_browser()
        launch_options = {
            "user_data_dir": str(CMS_USER_DATA_DIR),
            "headless": False,
            "accept_downloads": True,
            "viewport": {"width": 1366, "height": 768},
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if browser_path:
            launch_options["executable_path"] = str(browser_path)

        context = p.chromium.launch_persistent_context(
            **launch_options
        )

        page = cms_prepare_page(context)

        for content_id in content_ids:
            if cms_stop_requested():
                cms_log_stop(content_id)
                break

            item_start = time.perf_counter()
            row = {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content_id": content_id,
                "content_title": "",
                "status": "",
                "original_file": "",
                "processed_temp_file": "",
                "final_upload_file": "",
                "report_file": "",
                "error": "",
            }

            try:
                cms_set_status(row, "Iniciando")
                cms_set_status(row, "Baixando")

                with cms_timed_stage(row, "download"):
                    original_file = cms_download_subtitle(page, content_id, input_dir)

                row["original_file"] = str(original_file)
                row["content_title"] = (
                    cms_extract_content_title(page, content_id)
                    or title_from_filename(original_file.name, content_id)
                )
                if row["content_title"]:
                    cms_set_status(row, "Baixando")

                print("=" * 80)
                print(f"EDITANDO ORIGINAL INTACTO: {original_file.name}")

                cms_set_status(row, "Editando")
                with cms_timed_stage(row, "edicao"):
                    summary = process_file(original_file, output_dir, reports_dir)

                processed_temp_file = Path(summary["output_file"]).resolve()
                report_file = Path(summary["report_file"]).resolve()

                row["processed_temp_file"] = str(processed_temp_file)
                row["report_file"] = str(report_file)

                with cms_timed_stage(row, "arquivo_final"):
                    final_upload_file = cms_make_final_edited_file(
                        content_id=content_id,
                        processed_file=processed_temp_file,
                        output_dir=output_dir,
                    )

                row["final_upload_file"] = str(final_upload_file)
                cms_set_status(row, "Validando")

                if do_upload:
                    cms_set_status(row, "Enviando")
                    with cms_timed_stage(row, "upload"):
                        cms_upload_subtitle(page, content_id, final_upload_file)
                    if not row["content_title"]:
                        row["content_title"] = cms_extract_content_title(page, content_id)
                    row["status"] = "Enviado"
                    if row["content_title"]:
                        cms_append_status(row)
                else:
                    row["status"] = "Arquivo gerado"
                    if open_edited_file:
                        try:
                            open_file_for_review(final_upload_file)
                        except Exception as exc:
                            print(f"Não foi possível abrir arquivo editado para revisão: {exc}")

            except Exception as exc:
                row["status"] = cms_status_from_exception(exc)
                row["error"] = str(exc)
                print("=" * 80)
                print(f"ERRO NO CONTENT_ID {content_id}")
                print(exc)
                print("=" * 80)

            finally:
                cms_append_timing(row, "total_conteudo", time.perf_counter() - item_start, row.get("status", ""))
                cms_append_status(row)

        print("=" * 80)
        print("FLUXO CMS FINALIZADO")
        print("Log: logs/cms_fluxo_status.csv")
        print("=" * 80)
        context.close()




def cms_find_existing_output_file(content_id: str, output_dir: Path) -> Path:
    exact = output_dir / f"{content_id}.vtt"
    if exact.exists():
        return exact

    matches = list(output_dir.glob(f"*{content_id}*.vtt"))
    if matches:
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]

    raise FileNotFoundError(f"Arquivo editado não encontrado em saida/ para o Content ID {content_id}.")


def run_cms_upload_existing_flow(
    content_ids: List[str],
    output_dir: Path,
) -> None:
    """
    Sobe para o CMS arquivos já existentes em saida/.
    Não baixa e não edita novamente.
    """
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright não está instalado. Rode: py -m pip install playwright && py -m playwright install chromium"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    cms_clear_stop_request()
    cms_require_profile_available()

    print("=" * 80)
    print("FLUXO CMS: UPLOAD DE ARQUIVO JÁ GERADO")
    print("=" * 80)

    with sync_playwright() as p:
        browser_path = find_installed_browser()
        launch_options = {
            "user_data_dir": str(CMS_USER_DATA_DIR),
            "headless": False,
            "accept_downloads": True,
            "viewport": {"width": 1366, "height": 768},
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if browser_path:
            launch_options["executable_path"] = str(browser_path)

        context = p.chromium.launch_persistent_context(
            **launch_options
        )

        page = cms_prepare_page(context)

        for content_id in content_ids:
            if cms_stop_requested():
                cms_log_stop(content_id)
                break

            item_start = time.perf_counter()
            row = {
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content_id": content_id,
                "content_title": "",
                "status": "",
                "original_file": "",
                "processed_temp_file": "",
                "final_upload_file": "",
                "report_file": "",
                "error": "",
            }

            try:
                cms_set_status(row, "Enviando")
                with cms_timed_stage(row, "localizar_arquivo"):
                    final_upload_file = cms_find_existing_output_file(content_id, output_dir)
                row["final_upload_file"] = str(final_upload_file)

                with cms_timed_stage(row, "upload"):
                    cms_upload_subtitle(page, content_id, final_upload_file)
                row["content_title"] = cms_extract_content_title(page, content_id)
                row["status"] = "Enviado"
                if row["content_title"]:
                    cms_append_status(row)

            except Exception as exc:
                row["status"] = cms_status_from_exception(exc)
                row["error"] = str(exc)
                print("=" * 80)
                print(f"ERRO NO UPLOAD EXISTENTE DO CONTENT_ID {content_id}")
                print(exc)
                print("=" * 80)

            finally:
                cms_append_timing(row, "total_conteudo", time.perf_counter() - item_start, row.get("status", ""))
                cms_append_status(row)

        print("=" * 80)
        print("UPLOAD EXISTENTE FINALIZADO")
        print("Log: logs/cms_fluxo_status.csv")
        print("=" * 80)
        context.close()


def find_installed_browser() -> Optional[Path]:
    """
    Localiza um navegador real para login manual.

    O Cloudflare pode ocultar ou bloquear o desafio quando a pagina e aberta
    por um contexto controlado pelo Playwright. Para o botao Change Project,
    preferimos Chrome/Edge instalados e usamos o Chromium do Playwright apenas
    como ultimo recurso, sempre via subprocess e sem remote debugging.
    """
    candidates = []
    for executable in ("chrome.exe", "msedge.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))

    program_files = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relative_paths = [
        ("Google", "Chrome", "Application", "chrome.exe"),
        ("Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for base in program_files:
        if not base:
            continue
        for parts in relative_paths:
            candidates.append(Path(base, *parts))

    local_playwright = Path.home() / "AppData" / "Local" / "ms-playwright"
    if local_playwright.exists():
        candidates.extend(sorted(local_playwright.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_cms_manual_session() -> None:
    """
    Abre o CMS no mesmo perfil persistente usado pelo SubNexus, mas fora do
    controle do Playwright.

    Uso previsto: login, Cloudflare e troca manual de instancia pelo usuario.
    """
    browser_path = find_installed_browser()
    if browser_path is None:
        raise RuntimeError("Nenhum Chrome/Edge/Chromium foi encontrado para abrir o CMS manualmente.")

    print("=" * 80)
    print("SESSAO MANUAL CMS")
    print("Use esta janela para login/troca de instancia. Feche o Chrome ao terminar.")
    print(f"Navegador: {browser_path}")
    print("=" * 80)

    CMS_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(browser_path),
        f"--user-data-dir={CMS_USER_DATA_DIR}",
        "--profile-directory=Default",
        "--new-window",
        "--start-maximized",
        "--disable-background-mode",
        CMS_HOME_URL,
    ]
    subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent), shell=False)



def process_folder(input_dir: Path, output_dir: Path, reports_dir: Path, reviewed_dir: Path, popup: bool = True, open_after: bool = True) -> bool:
    """
    Fluxo:
    - A pasta entrada pode ser a pasta de downloads.
    - O script lê apenas o .vtt mais recente ainda não processado.
    - Arquivos antigos já processados são ignorados.

    Retorna True se processou algum arquivo.
    """
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    reviewed_dir.mkdir(parents=True, exist_ok=True)

    state_path = Path(__file__).resolve().parent / STATE_FILE_NAME
    state = load_processed_state(state_path)

    file = pick_latest_unprocessed_vtt(input_dir, state)

    if file is None:
        print(f"Nenhum .vtt novo para processar em: {input_dir}")
        print(f"Controle usado: {state_path}")
        return False

    print(f"Arquivo selecionado: {file.name}")
    log_event(f"Arquivo selecionado para processamento: {file.resolve()}")

    if not wait_until_file_is_stable(file):
        print(f"Arquivo ainda parece estar em download ou instável: {file.name}")
        return False

    try:
        summary = process_file(file, output_dir, reports_dir)

        output_file = Path(summary["output_file"]).resolve()
        report_file = Path(summary["report_file"]).resolve()

        summary["source_file"] = str(file.resolve())
        summary["output_file"] = str(output_file)
        summary["report_file"] = str(report_file)

        mark_file_as_processed(state, file, output_file, report_file)
        save_processed_state(state_path, state)

        print(f"Registrado como processado em: {state_path}")

        if open_after:
            output_file = Path(summary["output_file"]).resolve()
            print(f"Abrindo arquivo processado atual: {output_file}")
            log_event(f"Abrindo arquivo processado atual: {output_file}")

            if not output_file.exists():
                raise FileNotFoundError(f"Arquivo processado não encontrado para abertura: {output_file}")

            opened = open_file_for_review(output_file)
            if opened:
                print(f"Arquivo aberto para revisão: {output_file}")
                log_event(f"Arquivo aberto para revisão: {output_file}")

        if CONFIG.get("move_to_reviewed_after_confirmation", True):
            if ask_review_confirmation(output_file):
                moved_to = move_to_reviewed(output_file, reviewed_dir)
                if moved_to:
                    print(f"Arquivo movido para Revisados: {moved_to}")

        if popup:
            show_popup("Legenda processada", build_popup_message(summary, state_path))

        return True

    except Exception as exc:
        error_message = f"ERRO em {file.name}: {exc}\n\nO arquivo NÃO foi marcado como processado."
        print(error_message)

        if popup:
            show_popup("Erro ao processar legenda", error_message)

        return False


def watch_folder(
    input_dir: Path,
    output_dir: Path,
    reports_dir: Path,
    reviewed_dir: Path,
    interval: float = 3.0,
    popup: bool = True,
    open_after: bool = True,
    process_existing_on_start: bool = False,
) -> None:
    """
    Monitora a pasta continuamente.

    Comportamento padrão:
    - ignora .vtt que já estavam na pasta quando o script iniciou;
    - processa somente .vtt novos baixados depois.

    Para processar o último arquivo já existente ao iniciar, use:
    --process-existing-on-start
    """
    print(f"Monitorando: {input_dir}")
    print(f"Saída: {output_dir}")
    print(f"Relatórios: {reports_dir}")
    print(f"Revisados: {reviewed_dir}")

    state_path = Path(__file__).resolve().parent / STATE_FILE_NAME

    if not process_existing_on_start:
        marked = mark_existing_files_as_baseline(input_dir, state_path)
        if marked:
            print(f"Arquivos antigos ignorados no início: {marked}")
        else:
            print("Nenhum arquivo antigo novo para ignorar no início.")
    else:
        print("Modo: processar arquivo existente mais recente ao iniciar.")

    print("Pressione CTRL+C para parar.\n")

    while True:
        try:
            process_folder(input_dir, output_dir, reports_dir, reviewed_dir, popup=popup, open_after=open_after)
        except KeyboardInterrupt:
            print("\nMonitoramento encerrado.")
            break
        except Exception as exc:
            print(f"Erro no monitoramento: {exc}")

        time.sleep(interval)


def main() -> None:
    print("Versão: fluxo Python sem IA — download, edição e upload")
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--cms-flow", action="store_true", help="Executa fluxo CMS: download + edição + upload.")
    parser.add_argument("--open-cms-home", action="store_true", help="Abre o CMS no navegador normal para login/troca manual de instancia.")
    parser.add_argument("--content-ids", nargs="*", default=[], help="Lista de content_ids para processar no CMS.")
    parser.add_argument("--content-file", default="content_ids.txt", help="TXT com um content_id por linha.")
    parser.add_argument("--no-upload", action="store_true", help="Executa download + edição, mas não faz upload.")
    parser.add_argument("--language", default="pt-br", choices=["pt-br", "es"], help="Idioma da legenda/CMS: pt-br ou es.")
    parser.add_argument("--open-edited-file", action="store_true", help="Abre o arquivo editado após gerar sem upload.")
    parser.add_argument("--upload-existing-file", action="store_true", help="Sobe arquivo já existente em saida/ sem baixar/editar novamente.")
    parser.add_argument("--config", default="config.json", help="Arquivo de configuração JSON.")
    parser.add_argument("--input", default=None, help="Pasta de entrada/downloads com arquivos .vtt.")
    parser.add_argument("--output", default=None, help="Pasta para arquivos .vtt editados.")
    parser.add_argument("--reports", default=None, help="Pasta para relatórios.")
    parser.add_argument("--reviewed", default=None, help="Pasta para arquivos revisados.")
    parser.add_argument("--watch", action="store_true", help="Monitora a pasta e processa automaticamente novos .vtt.")
    parser.add_argument("--no-popup", action="store_true", help="Não mostra pop-up.")
    parser.add_argument("--no-open", action="store_true", help="Não abre o arquivo processado.")
    parser.add_argument("--no-move-after-review", action="store_true", help="Não move para Revisados após confirmação.")
    parser.add_argument("--process-existing-on-start", action="store_true", help="No modo --watch, processa também o .vtt mais recente já existente.")
    args = parser.parse_args()
    set_cms_language(getattr(args, "language", "pt-br"))

    if getattr(args, "open_cms_home", False):
        run_cms_manual_session()
        return

    if args.cms_flow:
        content_ids = list(args.content_ids or [])

        content_file = Path(args.content_file)
        if content_file.exists():
            extra_ids = [
                line.strip()
                for line in read_text_file(content_file).splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            content_ids.extend(extra_ids)

        seen = set()
        content_ids = [cid for cid in content_ids if not (cid in seen or seen.add(cid))]

        if not content_ids:
            print("Nenhum content_id informado.")
            print("Use --content-ids ID1 ID2 ou crie content_ids.txt com um ID por linha.")
            return

        base_dir = Path(__file__).resolve().parent

        if getattr(args, "upload_existing_file", False):
            run_cms_upload_existing_flow(
                content_ids=content_ids,
                output_dir=base_dir / "saida",
            )
            return

        run_cms_flow(
            content_ids=content_ids,
            input_dir=base_dir / "entrada",
            output_dir=base_dir / "saida",
            reports_dir=base_dir / "relatorios",
            reviewed_dir=base_dir / "Revisados",
            do_upload=not args.no_upload,
            open_edited_file=bool(getattr(args, "open_edited_file", False)),
        )
        return

    cfg_path = resolve_path(args.config, script_dir)
    cfg = load_config(cfg_path)
    if args.no_popup:
        cfg["show_popup"] = False
    if args.no_open:
        cfg["open_after_process"] = False
    if args.no_move_after_review:
        cfg["move_to_reviewed_after_confirmation"] = False
    if args.process_existing_on_start:
        cfg["process_existing_on_start"] = True
    apply_config(cfg)

    input_dir = Path(args.input) if args.input else resolve_path(str(cfg.get("input_folder", "entrada")), script_dir)
    output_dir = Path(args.output) if args.output else resolve_path(str(cfg.get("output_folder", "saida")), script_dir)
    reports_dir = Path(args.reports) if args.reports else resolve_path(str(cfg.get("reports_folder", "relatorios")), script_dir)
    reviewed_dir = Path(args.reviewed) if args.reviewed else resolve_path(str(cfg.get("reviewed_folder", "Revisados")), script_dir)
    interval = float(cfg.get("watch_interval_seconds", 3))
    process_existing = bool(cfg.get("process_existing_on_start", False))
    popup = bool(cfg.get("show_popup", True))
    open_after = bool(cfg.get("open_after_process", True))

    if args.watch:
        watch_folder(input_dir, output_dir, reports_dir, reviewed_dir, interval=interval, popup=popup, open_after=open_after, process_existing_on_start=process_existing)
    else:
        process_folder(input_dir, output_dir, reports_dir, reviewed_dir, popup=popup, open_after=open_after)


if __name__ == "__main__":
    try:
        main()
    except CmsProfileLockedError as exc:
        print(f"ERRO: {exc}")
        sys.exit(1)
