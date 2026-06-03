"""Persistent provider credentials.

Stored at ~/.poor-code/auth.json with 0600 perms. Schema is intentionally
flat: one entry per provider id, holding api_key + model. Not encrypted — same
trust level as a shell rc file. Use an OS keyring later if we need stronger
storage.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TypedDict

from poor_code.infra import paths


class ProviderCreds(TypedDict, total=False):
    api_key: str
    model: str


class AuthFile(TypedDict, total=False):
    providers: dict[str, ProviderCreds]
    active: str


def _path() -> Path:
    return paths.auth_json(Path.home())


def load() -> AuthFile:
    p = _path()
    if not p.exists():
        return {"providers": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"providers": {}}
    if not isinstance(data, dict) or "providers" not in data:
        return {"providers": {}}
    return data  # type: ignore[return-value]


def save(provider: str, *, api_key: str, model: str) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    providers = data.setdefault("providers", {})
    providers[provider] = {"api_key": api_key, "model": model}
    data["active"] = provider
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def get(provider: str) -> ProviderCreds | None:
    return load().get("providers", {}).get(provider)


def get_active() -> str | None:
    return load().get("active")
