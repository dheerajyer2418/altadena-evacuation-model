"""Configuration loading and merging.

All model parameters live in ``config/*.yaml`` so Dr. Grajdura can change behavior
without touching code. ``load_config`` resolves the ``includes:`` block in
experiments.yaml into one nested dict.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    # altadena_evac/config.py -> project root is one level up from the package.
    return Path(__file__).resolve().parent.parent


def load_yaml(path: str | os.PathLike) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = _project_root() / p
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(path: str | os.PathLike) -> dict[str, Any]:
    """Load a config file. If it has an ``includes:`` map, load each included
    file under its key. Returns a single nested dict.

    Example result keys: study, population, network, behavior, hazard, fleet,
    plus any top-level keys of the given file (sim, scenarios, reporting).
    """
    cfg = load_yaml(path)
    includes = cfg.pop("includes", {})
    for key, inc_path in includes.items():
        cfg[key] = load_yaml(inc_path)
    return cfg


def project_path(*parts: str) -> Path:
    """Resolve a path relative to the project root."""
    return _project_root().joinpath(*parts)
