from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid

from . import __version__


SUMMARY_FIELDS = [
    "session_id",
    "trial_id",
    "operator_id",
    "started_at_utc",
    "finished_at_utc",
    "content_id",
    "status",
    "end_reason",
    "end_confidence",
    "total_seconds",
    "subtitle_edit_active_seconds",
    "identify_to_search_seconds",
    "search_to_edit_1_seconds",
    "edit_1_to_download_seconds",
    "download_transfer_seconds",
    "subtitle_edit_cycle_seconds",
    "upload_form_seconds",
    "upload_processing_seconds",
    "player_open_seconds",
    "qc_seconds",
    "validate_media_processing_seconds",
    "approve_processing_seconds",
    "validate_processing_seconds",
    "search_intent_at_s",
    "edit_1_intent_at_s",
    "download_intent_at_s",
    "download_created_at_s",
    "download_completed_at_s",
    "download_file_ready_at_s",
    "subtitle_edit_first_at_s",
    "subtitle_edit_last_save_at_s",
    "edit_2_intent_at_s",
    "upload_open_intent_at_s",
    "upload_file_selected_at_s",
    "upload_language_selected_at_s",
    "upload_submit_intent_at_s",
    "upload_completed_at_s",
    "play_intent_at_s",
    "player_select_intent_at_s",
    "player_target_created_at_s",
    "player_ready_at_s",
    "qc_play_at_s",
    "validate_media_intent_at_s",
    "validate_media_completed_at_s",
    "approve_intent_at_s",
    "approve_completed_at_s",
    "validate_intent_at_s",
    "validate_completed_at_s",
    "event_count",
    "quality_valid",
    "quality_flags",
    "collector_version",
]

DURATION_FIELDS = {
    "search_to_edit_1_seconds": ("search.intent", "edit_1.intent"),
    "edit_1_to_download_seconds": ("edit_1.intent", "download.intent"),
    "download_transfer_seconds": ("download.created", "download.completed"),
    "subtitle_edit_cycle_seconds": ("download.completed", "edit_2.intent"),
    "upload_form_seconds": ("upload.open.intent", "upload.submit.intent"),
    "upload_processing_seconds": ("upload.submit.intent", "upload.completed"),
    "player_open_seconds": ("play.intent", "player.ready"),
    "qc_seconds": ("qc.play", "validate_media.intent"),
    "validate_media_processing_seconds": (
        "validate_media.intent",
        "validate_media.completed",
    ),
    "approve_processing_seconds": ("approve.intent", "approve.completed"),
    "validate_processing_seconds": ("validate.intent", "validate.completed"),
}

MARKER_TO_FIELD = {
    "search.intent": "search_intent_at_s",
    "edit_1.intent": "edit_1_intent_at_s",
    "download.intent": "download_intent_at_s",
    "download.created": "download_created_at_s",
    "download.completed": "download_completed_at_s",
    "download.file_ready": "download_file_ready_at_s",
    "subtitle_edit.first_foreground": "subtitle_edit_first_at_s",
    "subtitle_edit.last_save": "subtitle_edit_last_save_at_s",
    "edit_2.intent": "edit_2_intent_at_s",
    "upload.open.intent": "upload_open_intent_at_s",
    "upload.file_selected": "upload_file_selected_at_s",
    "upload.language_selected": "upload_language_selected_at_s",
    "upload.submit.intent": "upload_submit_intent_at_s",
    "upload.completed": "upload_completed_at_s",
    "play.intent": "play_intent_at_s",
    "player_select.intent": "player_select_intent_at_s",
    "player_target.created": "player_target_created_at_s",
    "player.ready": "player_ready_at_s",
    "qc.play": "qc_play_at_s",
    "validate_media.intent": "validate_media_intent_at_s",
    "validate_media.completed": "validate_media_completed_at_s",
    "approve.intent": "approve_intent_at_s",
    "approve.completed": "approve_completed_at_s",
    "validate.intent": "validate_intent_at_s",
    "validate.completed": "validate_completed_at_s",
}

INTENT_EVENT_ACTIONS = {
    "cms.validate_media.intent": "validate_media",
    "cms.approve.intent": "approve",
    "cms.validate.intent": "validate",
}

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CONTENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(moment: datetime | None = None) -> str:
    value = moment or utc_now()
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _safe_url(value: Any, store_full: bool) -> str:
    text = str(value or "")[:4096]
    if not text:
        return ""
    if store_full:
        return text
    try:
        parsed = urlsplit(text)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return text.split("?", 1)[0].split("#", 1)[0]


def _safe_path(value: Any, store_full: bool) -> dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"filename": "", "path_hash": ""}
    filename = PureWindowsPath(text).name if "\\" in text else Path(text).name
    result: dict[str, Any] = {
        "filename": filename[:260],
        "path_hash": _short_hash(os.path.normcase(text)),
    }
    if store_full:
        result["path"] = text
    return result


class EventStore:
    """Persistência append-only dos eventos e do resumo derivado."""

    def __init__(self, logs_dir: Path, config: dict[str, Any]):
        self.logs_dir = logs_dir.resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.session_id = f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        self.raw_path = self.logs_dir / f"session_{self.session_id}.jsonl"
        self.summary_path = self.logs_dir / "benchmark_passivo.csv"
        self._lock = threading.Lock()
        self._raw_file = self.raw_path.open("a", encoding="utf-8", buffering=1)

    def append(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._raw_file.write(line + "\n")
            self._raw_file.flush()

    def append_summary(self, row: dict[str, Any]) -> None:
        with self._lock:
            exists = self.summary_path.exists() and self.summary_path.stat().st_size > 0
            with self.summary_path.open("a", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=SUMMARY_FIELDS,
                    delimiter=";",
                    extrasaction="ignore",
                )
                if not exists:
                    writer.writeheader()
                writer.writerow({key: row.get(key, "") for key in SUMMARY_FIELDS})

    def close(self) -> None:
        with self._lock:
            if not self._raw_file.closed:
                self._raw_file.flush()
                self._raw_file.close()


class BenchmarkController:
    """
    Correlaciona eventos passivos da extensão e do Windows.

    Eventos brutos são sempre preservados; marcadores/CSV são derivados por uma
    máquina de estados por tentativa.
    """

    def __init__(
        self,
        config: dict[str, Any],
        logs_dir: Path,
        stop_event: threading.Event | None = None,
    ):
        self.config = config
        self.stop_event = stop_event or threading.Event()
        self.store = EventStore(logs_dir, config)
        self.session_token = secrets.token_urlsafe(32)
        self.extension_connected = threading.Event()
        self._paired_extension_id = ""
        self._lock = threading.RLock()
        self._anchor_wall_ms = time.time() * 1000.0
        self._anchor_perf_ns = time.perf_counter_ns()
        self._trial: dict[str, Any] | None = None
        self._seen_sequences: set[tuple[str, int]] = set()
        self._seen_sequence_order: deque[tuple[str, int]] = deque(maxlen=20_000)
        self._file_monitor_stop = threading.Event()
        self._file_monitor_threads: list[threading.Thread] = []
        self._closed = False

        self._append_system_event(
            "collector.started",
            {
                "collector_version": __version__,
                "config_path": config.get("_config_path", "default"),
                "python_version": platform.python_version(),
                "os": platform.platform(),
                "pid": os.getpid(),
            },
        )

    @property
    def session_id(self) -> str:
        return self.store.session_id

    @property
    def trial_active(self) -> bool:
        with self._lock:
            return bool(self._trial and self._trial.get("active"))

    @property
    def current_trial_id(self) -> str | None:
        with self._lock:
            return self._trial.get("trial_id") if self._trial else None

    def hello(self, extension_id: str, extension_version: str) -> dict[str, Any]:
        clean_id = extension_id[:128]
        with self._lock:
            if self._paired_extension_id and self._paired_extension_id != clean_id:
                return {"ok": False, "error": "different_extension_already_paired"}
            self._paired_extension_id = clean_id
            self.extension_connected.set()
            self._append_system_event(
                "extension.connected",
                {
                    "extension_id": clean_id,
                    "extension_version": extension_version[:64],
                },
            )
            return {
                "ok": True,
                "session_id": self.session_id,
                "session_token": self.session_token,
                "trial_active": self.trial_active,
                "collector_version": __version__,
            }

    def begin_trial(self, source: str = "global_hotkey") -> bool:
        with self._lock:
            if self._trial and self._trial.get("active"):
                print("[benchmark] Já existe uma medição ativa.", flush=True)
                return False

            now_perf = time.perf_counter_ns()
            trial_id = uuid.uuid4().hex
            self._trial = {
                "trial_id": trial_id,
                "active": True,
                "operator_id": str(self.config.get("_operator_id") or "")[:128],
                "started_perf_ns": now_perf,
                "started_at_utc": iso_utc(),
                "content_id": "",
                "markers": {},
                "marker_evidence": {},
                "pending": [],
                "requests": {},
                "event_count": 0,
                "edit_count": 0,
                "quality_flags": set(),
                "foreground_app": "",
                "foreground_enter_ns": now_perf,
                "subtitle_edit_active_ns": 0,
            }
            event = self._base_internal_event(
                "benchmark.started",
                {"source": source},
                now_perf,
                trial_id=trial_id,
            )
            self.store.append(event)

        print("\n>>> MEDIÇÃO INICIADA (hotkey global) <<<", flush=True)
        print(f"Trial ID: {trial_id}", flush=True)
        return True

    def finish_trial(
        self,
        reason: str,
        confidence: str,
        status: str = "completed",
        event_perf_ns: int | None = None,
    ) -> bool:
        with self._lock:
            trial = self._trial
            if not trial or not trial.get("active"):
                return False

            end_perf = event_perf_ns or time.perf_counter_ns()
            end_perf = max(end_perf, trial["started_perf_ns"])
            if confidence in {"manual_boundary", "manual_abort", "intent_only"}:
                trial["quality_flags"].add(f"end_{confidence}")
            self._close_foreground_interval(trial, end_perf)
            self._apply_quality_checks(trial)
            trial["active"] = False
            trial["finished_perf_ns"] = end_perf
            trial["finished_at_utc"] = self._perf_to_iso(end_perf)
            trial["end_reason"] = reason
            trial["end_confidence"] = confidence
            trial["status"] = status

            finished_event = self._base_internal_event(
                "benchmark.finished",
                {
                    "reason": reason,
                    "confidence": confidence,
                    "status": status,
                },
                end_perf,
                trial_id=trial["trial_id"],
            )
            self.store.append(finished_event)
            summary = self._build_summary(trial)
            self.store.append_summary(summary)

        print("\n>>> MEDIÇÃO ENCERRADA <<<", flush=True)
        print(f"Total: {summary['total_seconds']} s", flush=True)
        print(f"Fim: {reason} | confiança={confidence}", flush=True)
        print(f"Content ID: {summary['content_id'] or '(não identificado)'}", flush=True)
        print(f"CSV: {self.store.summary_path}", flush=True)
        print(f"Eventos: {self.store.raw_path}", flush=True)

        if self.config["trial"].get("exit_after_finish", True):
            self.stop_event.set()
        return True

    def ingest_batch(self, events: list[Any], extension_id: str) -> list[int]:
        accepted: list[int] = []
        for raw in events[:200]:
            if not isinstance(raw, dict):
                continue
            sequence = raw.get("sequence")
            if isinstance(sequence, bool):
                sequence = None
            if isinstance(sequence, (int, float)):
                sequence = int(sequence)
                dedup_key = (extension_id, sequence)
                with self._lock:
                    if dedup_key in self._seen_sequences:
                        accepted.append(sequence)
                        continue
                    if len(self._seen_sequence_order) == self._seen_sequence_order.maxlen:
                        oldest = self._seen_sequence_order.popleft()
                        self._seen_sequences.discard(oldest)
                    self._seen_sequences.add(dedup_key)
                    self._seen_sequence_order.append(dedup_key)
                accepted.append(sequence)
            self.ingest_event(raw, extension_id=extension_id)
        return accepted

    def ingest_event(self, raw: dict[str, Any], extension_id: str = "") -> None:
        with self._lock:
            if self._closed:
                return
        receipt_perf = time.perf_counter_ns()
        event = self._normalize_event(raw, receipt_perf, extension_id)
        if event is None:
            return

        raw_data = dict(event.get("data") or {})
        persisted = self._sanitize_event(event)

        with self._lock:
            if self._closed:
                return
            trial = self._trial
            if trial and trial.get("active"):
                persisted["trial_id"] = trial["trial_id"]
                trial["event_count"] += 1
            self.store.append(persisted)
            if trial and trial.get("active"):
                self._process_trial_event(trial, event, raw_data)

    def record_internal(
        self,
        name: str,
        data: dict[str, Any] | None = None,
        perf_ns: int | None = None,
    ) -> None:
        moment = perf_ns or time.perf_counter_ns()
        with self._lock:
            if self._closed:
                return
            trial_id = self._trial.get("trial_id") if self._trial else None
            event = self._base_internal_event(name, data or {}, moment, trial_id=trial_id)
            self.store.append(self._sanitize_event(event))
            trial = self._trial
            if trial and trial.get("active"):
                trial["event_count"] += 1
                self._process_trial_event(trial, event, dict(data or {}))

    def _normalize_event(
        self,
        raw: dict[str, Any],
        receipt_perf_ns: int,
        extension_id: str,
    ) -> dict[str, Any] | None:
        name = str(raw.get("name") or "").strip()[:128]
        if not name or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            return None
        data = raw.get("data")
        if not isinstance(data, dict):
            data = {}
        source_ms = raw.get("source_timestamp_ms")
        try:
            source_ms = float(source_ms)
        except (TypeError, ValueError):
            source_ms = None
        source_perf = self._source_ms_to_perf(source_ms, receipt_perf_ns)
        event: dict[str, Any] = {
            "name": name,
            "source": str(raw.get("source") or "extension")[:64],
            "source_timestamp_ms": source_ms,
            "source_estimated_perf_ns": source_perf,
            "collector_received_at_utc": iso_utc(),
            "collector_received_perf_ns": receipt_perf_ns,
            "extension_id": extension_id[:128],
            "data": data,
        }
        for key in ("sequence", "tab_id", "window_id", "frame_id", "document_id"):
            if key in raw:
                event[key] = raw[key]
        return event

    def _sanitize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        result = dict(event)
        data = dict(result.get("data") or {})
        privacy = self.config.get("privacy", {})
        store_full_urls = bool(privacy.get("store_full_urls"))
        store_full_paths = bool(privacy.get("store_full_paths"))
        store_window_titles = bool(privacy.get("store_window_titles"))

        for key in list(data):
            lowered = key.lower()
            if "url" in lowered or lowered in {"referrer", "origin"}:
                data[key] = _safe_url(data[key], store_full_urls)
            elif (
                lowered in {"filename", "path", "file_path"}
                or lowered.endswith("_path")
                or lowered.endswith("_dir")
            ):
                safe = _safe_path(data[key], store_full_paths)
                data.pop(key, None)
                if lowered == "filename":
                    data.update(safe)
                else:
                    data[f"{key}_name"] = safe["filename"]
                    data[f"{key}_hash"] = safe["path_hash"]
                    if "path" in safe:
                        data[key] = safe["path"]
            elif "window_title" in lowered and not store_window_titles:
                data[key] = ""
            elif lowered in {"cookie", "cookies", "authorization", "headers", "body"}:
                data.pop(key, None)
            elif isinstance(data[key], str):
                data[key] = data[key][:1000]

        result["data"] = data
        return result

    def _process_trial_event(
        self,
        trial: dict[str, Any],
        event: dict[str, Any],
        raw_data: dict[str, Any],
    ) -> None:
        name = event["name"]
        event_perf = int(event.get("source_estimated_perf_ns") or time.perf_counter_ns())
        tab_id = self._as_int(event.get("tab_id"), default=-1)

        # A fila da extensão pode conter telemetria produzida antes da hotkey.
        # Esses eventos ficam no JSONL para auditoria, mas não viram marcadores.
        if event_perf < int(trial["started_perf_ns"]) - 500_000_000:
            trial["quality_flags"].add("pre_trial_event_ignored")
            return

        try:
            dropped_events = int(raw_data.get("dropped_events_total") or 0)
        except (TypeError, ValueError):
            dropped_events = 0
        if dropped_events > 0:
            trial["quality_flags"].add("extension_reported_dropped_events")

        content_id = str(raw_data.get("content_id") or "").strip()
        if content_id and CONTENT_ID_RE.fullmatch(content_id):
            if trial["content_id"] and trial["content_id"] != content_id:
                trial["quality_flags"].add("multiple_content_ids")
            trial["content_id"] = content_id

        requires_trusted_input = name.endswith(".intent") or name in {
            "cms.upload.file_selected",
            "cms.upload.language_selected",
        }
        if name.startswith("cms.") and requires_trusted_input:
            if raw_data.get("trusted") is False:
                trial["quality_flags"].add("untrusted_dom_event_ignored")
                return

        if name == "cms.search.intent":
            self._mark(trial, "search.intent", event_perf, "dom_trusted")
        elif name == "cms.edit.intent":
            trial["edit_count"] += 1
            ordinal = trial["edit_count"]
            self._mark(trial, f"edit_{ordinal}.intent", event_perf, "dom_trusted")
            if ordinal > 2:
                trial["quality_flags"].add("more_than_two_edit_actions")
        elif name == "cms.download.intent":
            self._mark(trial, "download.intent", event_perf, "dom_trusted")
        elif name == "browser.download.created":
            self._mark(trial, "download.created", event_perf, "chrome_downloads_api")
        elif name == "browser.download.completed":
            self._mark(trial, "download.completed", event_perf, "chrome_downloads_api")
            filename = str(raw_data.get("filename") or "")
            if filename:
                self._start_file_verification(filename, raw_data.get("download_id"))
        elif name == "browser.download.interrupted":
            trial["quality_flags"].add("download_interrupted")
        elif name == "cms.upload.open.intent":
            self._mark(trial, "upload.open.intent", event_perf, "dom_trusted")
        elif name == "cms.upload.file_selected":
            self._mark(trial, "upload.file_selected", event_perf, "dom_change")
        elif name == "cms.upload.language_selected":
            self._mark(trial, "upload.language_selected", event_perf, "dom_change")
        elif name == "cms.upload.submit.intent":
            self._mark(trial, "upload.submit.intent", event_perf, "dom_trusted")
            trial["pending"].append(
                {
                    "action": "upload",
                    "tab_id": tab_id,
                    "perf_ns": event_perf,
                    "completed": False,
                }
            )
        elif name == "cms.play.intent":
            self._mark(trial, "play.intent", event_perf, "dom_trusted")
        elif name == "cms.player_select.intent":
            self._mark(trial, "player_select.intent", event_perf, "dom_trusted")
        elif name == "browser.player_target.created":
            self._mark(trial, "player_target.created", event_perf, "chrome_web_navigation")
        elif name == "player.ready":
            self._mark(trial, "player.ready", event_perf, "media_event")
        elif name == "player.play":
            self._mark(trial, "qc.play", event_perf, "media_event")
        elif name == "windows.foreground.changed":
            self._process_foreground(trial, event_perf, raw_data)
        elif name == "filesystem.subtitle.changed":
            self._mark(
                trial,
                "subtitle_edit.last_save",
                event_perf,
                "filesystem",
                replace=True,
            )
        elif name in INTENT_EVENT_ACTIONS:
            action = INTENT_EVENT_ACTIONS[name]
            marker = f"{action}.intent"
            self._mark(trial, marker, event_perf, "dom_trusted")
            trial["pending"].append(
                {
                    "action": action,
                    "tab_id": tab_id,
                    "perf_ns": event_perf,
                    "completed": False,
                }
            )
            if action == "validate" and self.config["trial"].get(
                "auto_finish_on_validate_intent", False
            ):
                trial["quality_flags"].add("ended_on_validate_intent")
                self.finish_trial(
                    "validate_intent",
                    "intent_only",
                    event_perf_ns=event_perf,
                )
        elif name == "browser.request.started":
            self._process_request_started(trial, event, raw_data, event_perf)
        elif name == "browser.request.completed":
            self._process_request_completed(trial, event, raw_data, event_perf)
        elif name == "browser.request.error":
            request_id = str(raw_data.get("request_id") or "")
            request = trial["requests"].pop(request_id, None)
            if request:
                trial["quality_flags"].add(f"{request['action']}_request_error")
        elif name in {"cms.notification.success", "cms.state.success"}:
            self._process_success_signal(
                trial,
                tab_id,
                event_perf,
                "ui_success",
                action_hint=str(raw_data.get("action_hint") or ""),
            )
        elif name in {"cms.notification.failure", "cms.state.failure"}:
            pending = self._latest_pending(trial, tab_id, event_perf)
            if pending:
                trial["quality_flags"].add(f"{pending['action']}_ui_failure")
        elif name == "filesystem.download.ready":
            self._mark(trial, "download.file_ready", event_perf, "filesystem")
        elif name == "filesystem.download.not_ready":
            trial["quality_flags"].add("download_file_not_ready")

    def _process_request_started(
        self,
        trial: dict[str, Any],
        event: dict[str, Any],
        data: dict[str, Any],
        event_perf: int,
    ) -> None:
        method = str(data.get("method") or "GET").upper()
        if method not in MUTATING_METHODS:
            return
        url = str(data.get("url") or "")
        if self._request_is_ignored(url):
            return
        tab_id = self._as_int(event.get("tab_id"), default=-1)
        pending = self._latest_pending(trial, tab_id, event_perf)
        if not pending:
            return

        classified = self._classify_action_url(url)
        confidence = "endpoint_pattern"
        if classified != pending["action"]:
            if not self.config["trial"].get("allow_generic_mutating_request", True):
                return
            confidence = "correlated_mutating_request"
            trial["quality_flags"].add(
                f"{pending['action']}_generic_network_correlation"
            )

        request_id = str(data.get("request_id") or "")[:256]
        if not request_id:
            return
        trial["requests"][request_id] = {
            "action": pending["action"],
            "pending": pending,
            "confidence": confidence,
            "started_perf_ns": event_perf,
            "method": method,
        }

    def _process_request_completed(
        self,
        trial: dict[str, Any],
        event: dict[str, Any],
        data: dict[str, Any],
        event_perf: int,
    ) -> None:
        request_id = str(data.get("request_id") or "")[:256]
        request = trial["requests"].pop(request_id, None)
        if not request:
            return
        try:
            status_code = int(data.get("status_code"))
        except (TypeError, ValueError):
            status_code = 0
        if not 200 <= status_code < 300:
            trial["quality_flags"].add(
                f"{request['action']}_http_{status_code or 'unknown'}"
            )
            return

        action = request["action"]
        request["pending"]["completed"] = True
        self._mark(
            trial,
            f"{action}.completed",
            event_perf,
            request["confidence"],
        )
        if action == "validate":
            self.finish_trial(
                "validate_response_success",
                request["confidence"],
                event_perf_ns=event_perf,
            )

    def _process_success_signal(
        self,
        trial: dict[str, Any],
        tab_id: int,
        event_perf: int,
        confidence: str,
        action_hint: str = "",
    ) -> None:
        allowed_actions = {"upload", "validate_media", "approve", "validate"}
        preferred = action_hint if action_hint in allowed_actions else ""
        pending = self._latest_pending(
            trial,
            tab_id,
            event_perf,
            action=preferred or None,
        )
        if not pending and preferred:
            # Notificações genéricas/mal traduzidas ainda podem ser usadas como
            # corroboradoras, mas só dentro da mesma janela temporal.
            pending = self._latest_pending(trial, tab_id, event_perf)
        if not pending:
            return
        pending["completed"] = True
        action = pending["action"]
        self._mark(trial, f"{action}.completed", event_perf, confidence)
        if action == "validate":
            self.finish_trial(
                "validate_ui_success",
                confidence,
                event_perf_ns=event_perf,
            )

    def _latest_pending(
        self,
        trial: dict[str, Any],
        tab_id: int,
        event_perf: int,
        action: str | None = None,
    ) -> dict[str, Any] | None:
        window_ns = int(
            float(self.config["trial"].get("completion_window_seconds", 15))
            * 1_000_000_000
        )
        candidates = []
        for item in trial["pending"]:
            if item.get("completed"):
                continue
            if action and item.get("action") != action:
                continue
            if tab_id >= 0 and item.get("tab_id", -1) not in {-1, tab_id}:
                continue
            delta = event_perf - int(item["perf_ns"])
            if -500_000_000 <= delta <= window_ns:
                candidates.append(item)
        return max(candidates, key=lambda item: item["perf_ns"]) if candidates else None

    def _classify_action_url(self, url: str) -> str | None:
        order = ("validate_media", "approve", "upload", "validate")
        patterns = self.config.get("network_action_patterns", {})
        for action in order:
            for pattern in patterns.get(action, []):
                try:
                    if re.search(pattern, url, flags=re.IGNORECASE):
                        return action
                except re.error:
                    continue
        return None

    def _request_is_ignored(self, url: str) -> bool:
        for pattern in self.config.get("ignored_request_patterns", []):
            try:
                if re.search(pattern, url, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    def _process_foreground(
        self,
        trial: dict[str, Any],
        event_perf: int,
        data: dict[str, Any],
    ) -> None:
        new_app = str(data.get("app") or "other")[:64]
        self._close_foreground_interval(trial, event_perf)
        trial["foreground_app"] = new_app
        trial["foreground_enter_ns"] = event_perf
        if new_app == "subtitle_edit":
            self._mark(
                trial,
                "subtitle_edit.first_foreground",
                event_perf,
                "windows_foreground",
            )

    def _close_foreground_interval(self, trial: dict[str, Any], end_perf: int) -> None:
        entered = int(trial.get("foreground_enter_ns") or end_perf)
        if trial.get("foreground_app") == "subtitle_edit" and end_perf >= entered:
            trial["subtitle_edit_active_ns"] += end_perf - entered
        trial["foreground_enter_ns"] = end_perf

    def _mark(
        self,
        trial: dict[str, Any],
        name: str,
        perf_ns: int,
        evidence: str,
        replace: bool = False,
    ) -> None:
        if name in trial["markers"] and not replace:
            return
        perf_ns = max(perf_ns, int(trial["started_perf_ns"]))
        trial["markers"][name] = perf_ns
        trial["marker_evidence"][name] = evidence
        elapsed = max(0.0, (perf_ns - trial["started_perf_ns"]) / 1_000_000_000)
        print(f"[evento] {name:<32} +{elapsed:8.3f}s ({evidence})", flush=True)

    def _start_file_verification(self, filename: str, download_id: Any) -> None:
        path = Path(filename)
        thread = threading.Thread(
            target=self._verify_and_monitor_file,
            args=(path, download_id),
            name=f"DownloadVerify-{download_id}",
            daemon=True,
        )
        self._file_monitor_threads.append(thread)
        thread.start()

    def _verify_and_monitor_file(self, path: Path, download_id: Any) -> None:
        deadline = time.monotonic() + 8.0
        previous: tuple[int, int] | None = None
        stable_count = 0
        ready = False
        while time.monotonic() < deadline and not self._file_monitor_stop.is_set():
            try:
                stat = path.stat()
                current = (stat.st_size, stat.st_mtime_ns)
                with path.open("rb") as file:
                    file.read(1)
                if current == previous:
                    stable_count += 1
                else:
                    stable_count = 0
                    previous = current
                if stable_count >= 2:
                    ready = True
                    break
            except OSError:
                previous = None
                stable_count = 0
            self._file_monitor_stop.wait(0.15)

        if not ready:
            self.record_internal(
                "filesystem.download.not_ready",
                {"filename": str(path), "download_id": download_id},
            )
            return

        self.record_internal(
            "filesystem.download.ready",
            {
                "filename": str(path),
                "download_id": download_id,
                "size": previous[0] if previous else None,
            },
        )

        baseline = previous
        while not self._file_monitor_stop.wait(0.25):
            if not self.trial_active:
                return
            try:
                stat = path.stat()
                current = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
            if baseline is not None and current != baseline:
                baseline = current
                self.record_internal(
                    "filesystem.subtitle.changed",
                    {
                        "filename": str(path),
                        "download_id": download_id,
                        "size": current[0],
                    },
                )

    def _apply_quality_checks(self, trial: dict[str, Any]) -> None:
        required = [
            "search.intent",
            "edit_1.intent",
            "download.intent",
            "download.completed",
            "download.file_ready",
            "subtitle_edit.first_foreground",
            "subtitle_edit.last_save",
            "edit_2.intent",
            "upload.open.intent",
            "upload.file_selected",
            "upload.language_selected",
            "upload.submit.intent",
            "upload.completed",
            "play.intent",
            "player_target.created",
            "player.ready",
            "qc.play",
            "validate_media.intent",
            "validate_media.completed",
            "approve.intent",
            "approve.completed",
            "validate.intent",
            "validate.completed",
        ]
        markers = trial["markers"]
        for marker in required:
            if marker not in markers:
                safe_name = marker.replace(".", "_")
                trial["quality_flags"].add(f"missing_{safe_name}")

        ordered = [
            "search.intent",
            "edit_1.intent",
            "download.intent",
            "download.completed",
            "subtitle_edit.first_foreground",
            "subtitle_edit.last_save",
            "edit_2.intent",
            "upload.open.intent",
            "upload.file_selected",
            "upload.language_selected",
            "upload.submit.intent",
            "upload.completed",
            "play.intent",
            "player_target.created",
            "player.ready",
            "qc.play",
            "validate_media.intent",
            "approve.intent",
            "validate.intent",
            "validate.completed",
        ]
        previous_value: int | None = None
        for marker in ordered:
            value = markers.get(marker)
            if value is None:
                continue
            if previous_value is not None and value < previous_value:
                trial["quality_flags"].add("event_order_violation")
                break
            previous_value = value

    def _build_summary(self, trial: dict[str, Any]) -> dict[str, Any]:
        start = int(trial["started_perf_ns"])
        finish = int(trial["finished_perf_ns"])
        row: dict[str, Any] = {
            "session_id": self.session_id,
            "trial_id": trial["trial_id"],
            "operator_id": trial["operator_id"],
            "started_at_utc": trial["started_at_utc"],
            "finished_at_utc": trial["finished_at_utc"],
            "content_id": trial["content_id"],
            "status": trial["status"],
            "end_reason": trial["end_reason"],
            "end_confidence": trial["end_confidence"],
            "total_seconds": f"{(finish - start) / 1_000_000_000:.3f}",
            "subtitle_edit_active_seconds": (
                f"{trial['subtitle_edit_active_ns'] / 1_000_000_000:.3f}"
            ),
            "event_count": trial["event_count"],
            "quality_valid": "yes" if not trial["quality_flags"] else "no",
            "quality_flags": "|".join(sorted(trial["quality_flags"])),
            "collector_version": __version__,
        }
        search_intent = trial["markers"].get("search.intent")
        row["identify_to_search_seconds"] = (
            f"{(search_intent - start) / 1_000_000_000:.3f}"
            if search_intent
            else ""
        )
        for field, (begin_marker, end_marker) in DURATION_FIELDS.items():
            begin_value = trial["markers"].get(begin_marker)
            end_value = trial["markers"].get(end_marker)
            row[field] = (
                f"{(end_value - begin_value) / 1_000_000_000:.3f}"
                if begin_value and end_value and end_value >= begin_value
                else ""
            )
        for marker, field in MARKER_TO_FIELD.items():
            value = trial["markers"].get(marker)
            row[field] = f"{(value - start) / 1_000_000_000:.3f}" if value else ""
        return row

    def _source_ms_to_perf(self, source_ms: float | None, fallback: int) -> int:
        if source_ms is None:
            return fallback
        delta_ms = source_ms - self._anchor_wall_ms
        if abs(delta_ms) > 24 * 60 * 60 * 1000:
            return fallback
        estimated = self._anchor_perf_ns + int(delta_ms * 1_000_000)
        # Mensagens antigas da fila podem anteceder esta execução. Para a medição
        # atual elas permanecem no log, mas não recebem timestamp impossível.
        return estimated

    def _perf_to_iso(self, perf_ns: int) -> str:
        delta_seconds = (perf_ns - self._anchor_perf_ns) / 1_000_000_000
        wall_seconds = self._anchor_wall_ms / 1000.0 + delta_seconds
        return datetime.fromtimestamp(wall_seconds, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")

    def _base_internal_event(
        self,
        name: str,
        data: dict[str, Any],
        perf_ns: int,
        trial_id: str | None,
    ) -> dict[str, Any]:
        event = {
            "name": name,
            "source": "collector",
            "source_timestamp_ms": None,
            "source_estimated_perf_ns": perf_ns,
            "collector_received_at_utc": iso_utc(),
            "collector_received_perf_ns": perf_ns,
            "data": data,
        }
        if trial_id:
            event["trial_id"] = trial_id
        return event

    def _append_system_event(self, name: str, data: dict[str, Any]) -> None:
        event = self._base_internal_event(
            name,
            data,
            time.perf_counter_ns(),
            trial_id=None,
        )
        self.store.append(self._sanitize_event(event))

    @staticmethod
    def _as_int(value: Any, default: int = -1) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._trial and self._trial.get("active"):
                self.finish_trial("collector_stopped", "manual_abort", status="aborted")
            self._file_monitor_stop.set()
            self._append_system_event("collector.stopped", {})
            self.store.close()
