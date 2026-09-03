from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "benchmark_passivo_config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "cms_url": "https://dtv-cms-ui.tbxnet.com/",
    "profile_dir": "perfil_navegador_cms",
    "collector": {
        "host": "127.0.0.1",
        "port": 8765,
        "extension_wait_seconds": 45,
    },
    "trial": {
        "exit_after_finish": True,
        "completion_window_seconds": 15,
        "allow_generic_mutating_request": True,
        "auto_finish_on_validate_intent": False,
    },
    "network_action_patterns": {
        "validate_media": [
            r"validate[-_/]?media",
            r"media[-_/]?(validate|validation)",
        ],
        "approve": [r"approve", r"approval"],
        "upload": [r"upload", r"subtitle", r"caption"],
        "validate": [r"validate", r"validation"],
    },
    "ignored_request_patterns": [
        r"analytics",
        r"telemetry",
        r"metrics",
        r"heartbeat",
        r"tracking",
        r"sentry",
        r"datadog",
        r"newrelic",
        r"logging",
    ],
    "privacy": {
        "store_full_urls": False,
        "store_full_paths": False,
        "store_window_titles": False,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path).resolve() if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, dict):
        raise ValueError(f"Configuração inválida em {config_path}: esperado objeto JSON.")

    config = _deep_merge(DEFAULT_CONFIG, loaded)
    config["_config_path"] = str(config_path)
    return config


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()
