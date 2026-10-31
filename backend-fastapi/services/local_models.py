"""Where locally-run voice models live. Nothing under here is committed; see docs/LOCAL_VOICE.md."""

from pathlib import Path

import config

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    p = Path(config.LOCAL_MODELS_DIR)
    return p if p.is_absolute() else _BACKEND_DIR / p


def resolve(path_or_name: str, subdir: str) -> Path:
    """An absolute path is used as-is; a bare name is looked up in <models_dir>/<subdir>/."""
    p = Path(path_or_name)
    return p if p.is_absolute() else models_dir() / subdir / p
