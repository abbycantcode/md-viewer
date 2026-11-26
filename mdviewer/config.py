"""Persistent configuration management for Markveil."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mdviewer.themes import THEME_ORDER

VALID_THEMES = ("auto", *THEME_ORDER)
MAX_RECENT_FILES = 15


@dataclass
class AppConfig:
    """Persistent application preferences and window state."""

    theme: str = "folio"
    zoom_level: float = 1.0
    window_width: int = 1080
    window_height: int = 780
    sidebar_visible: bool = True
    sidebar_tab: str = "outline"
    sidebar_width: int = 252
    split_ratio: float = 0.5
    vim_navigation: bool = True
    allow_remote_images: bool = False
    custom_css_path: str = ""
    recent_files: list[str] = field(default_factory=list)
    preferred_agent: str = "auto"
    status_bar_visible: bool = True


def get_config_dir() -> Path:
    """Return the XDG-compliant configuration directory for Markveil."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "markveil"


def get_legacy_config_path() -> Path:
    """Return the legacy md-viewer config.json path for transparent migration."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "md-viewer" / "config.json"


def get_config_path() -> Path:
    """Return the full path to the config.json file."""
    return get_config_dir() / "config.json"


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(minimum, min(maximum, int(value)))


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(minimum, min(maximum, float(value)))


def _normalize_recent_files(items: Any, max_items: int = MAX_RECENT_FILES) -> list[str]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            continue
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= max_items:
            break
    return result


def _config_from_dict(raw: dict[str, Any]) -> AppConfig:
    defaults = AppConfig()
    theme = raw.get("theme", defaults.theme)
    if theme not in VALID_THEMES:
        theme = "auto"

    sidebar_tab = raw.get("sidebar_tab", defaults.sidebar_tab)
    if not isinstance(sidebar_tab, str) or not sidebar_tab.strip():
        sidebar_tab = defaults.sidebar_tab

    custom_css_path = raw.get("custom_css_path", defaults.custom_css_path)
    if not isinstance(custom_css_path, str):
        custom_css_path = defaults.custom_css_path

    preferred_agent = raw.get("preferred_agent", defaults.preferred_agent)
    if not isinstance(preferred_agent, str) or not preferred_agent.strip():
        preferred_agent = defaults.preferred_agent

    return AppConfig(
        theme=theme,
        zoom_level=_coerce_float(raw.get("zoom_level"), defaults.zoom_level, 0.4, 3.0),
        window_width=_coerce_int(raw.get("window_width"), defaults.window_width, 400, 7680),
        window_height=_coerce_int(raw.get("window_height"), defaults.window_height, 300, 4320),
        sidebar_visible=_coerce_bool(raw.get("sidebar_visible"), defaults.sidebar_visible),
        sidebar_tab=sidebar_tab,
        sidebar_width=_coerce_int(raw.get("sidebar_width"), defaults.sidebar_width, 140, 800),
        split_ratio=_coerce_float(raw.get("split_ratio"), defaults.split_ratio, 0.15, 0.85),
        vim_navigation=_coerce_bool(raw.get("vim_navigation"), defaults.vim_navigation),
        allow_remote_images=_coerce_bool(raw.get("allow_remote_images"), defaults.allow_remote_images),
        custom_css_path=custom_css_path,
        recent_files=_normalize_recent_files(raw.get("recent_files")),
        preferred_agent=preferred_agent,
        status_bar_visible=_coerce_bool(raw.get("status_bar_visible"), defaults.status_bar_visible),
    )


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from disk, returning defaults if missing or invalid."""
    if config_path is not None:
        path = Path(config_path)
    else:
        path = get_config_path()
        if not path.is_file():
            legacy = get_legacy_config_path()
            if legacy.is_file():
                path = legacy
    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, ValueError):
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    return _config_from_dict(data)


def save_config(cfg: AppConfig, config_path: str | Path | None = None) -> Path:
    """Atomically write configuration JSON to disk using NamedTemporaryFile + os.replace."""
    target = Path(config_path) if config_path is not None else get_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(cfg)
    payload["recent_files"] = _normalize_recent_files(cfg.recent_files)

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".config-",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            json.dump(payload, tmp, indent=2, sort_keys=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, target)
    except Exception:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise
    return target


def add_recent_file(cfg: AppConfig, path: str, max_items: int = MAX_RECENT_FILES) -> list[str]:
    """Prepend a normalized path to recent_files, deduplicating and capping at max_items."""
    if not path or not path.strip():
        return cfg.recent_files
    normalized = os.path.abspath(os.path.expanduser(path))
    updated = [normalized] + [p for p in cfg.recent_files if p != normalized]
    cfg.recent_files = updated[:max_items]
    return cfg.recent_files
