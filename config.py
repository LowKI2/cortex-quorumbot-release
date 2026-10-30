"""Config: YAML-Datei + Overrides aus dem Chat (!set), mit Hot-Reload."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

# Diese Schlüssel darf der Besitzer per Chat ändern.
DEFAULT_SETTABLE = [
    "llm.model", "llm.temperature", "llm.max_tokens",
    "persona.system_prompt", "persona.max_reply_chars",
    "context.max_messages",
    "guardrails.require_mention_from_owner", "guardrails.allow_bot_dialog",
    "guardrails.dialog_default_rounds", "guardrails.dialog_max_rounds",
    "guardrails.dialog_max_minutes", "guardrails.cooldown_seconds",
    "guardrails.max_requests_per_hour", "guardrails.max_tokens_per_day",
    "voice_notifier.enabled", "voice_notifier.cooldown_seconds",
]


class Config:
    def __init__(self, path: str | Path, data: dict | None = None):
        self.path = Path(path)
        self.overrides_path = self.path.with_name(self.path.stem + ".overrides.json")
        self._mtime = 0.0
        self._ov_mtime = 0.0
        self.base: dict = {}
        self.overrides: dict = {}
        if data is not None:
            self.base = data
        else:
            self.reload_if_changed(force=True)

    # --- Laden ---------------------------------------------------------
    def reload_if_changed(self, force: bool = False) -> bool:
        changed = False
        try:
            m = self.path.stat().st_mtime
            if force or m != self._mtime:
                self.base = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._mtime = m
                changed = True
        except FileNotFoundError:
            if force:
                raise
        if self.overrides_path.exists():
            m = self.overrides_path.stat().st_mtime
            if force or m != self._ov_mtime:
                self.overrides = json.loads(self.overrides_path.read_text(encoding="utf-8"))
                self._ov_mtime = m
                changed = True
        return changed

    # --- Zugriff -------------------------------------------------------
    def _lookup(self, data: dict, key: str):
        cur = data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None, False
            cur = cur[part]
        return cur, True

    def get(self, key: str, default=None):
        if key in self.overrides:
            return self.overrides[key]
        val, found = self._lookup(self.base, key)
        return val if found and val is not None else default

    def settable(self) -> list[str]:
        return self.get("guardrails.settable_keys") or DEFAULT_SETTABLE

    def set(self, key: str, raw: str):
        """Wert aus dem Chat setzen. Typ richtet sich nach dem bisherigen Wert."""
        if key not in self.settable():
            raise KeyError(f"'{key}' ist nicht per Chat änderbar")
        from settings_schema import FIELDS, to_value  # spät importiert, sonst Kreisimport
        if key in FIELDS:
            value = to_value(FIELDS[key], raw)   # gleiche Prüfung wie im Konfigurator
        else:
            value = coerce(raw, self.get(key))
        self.overrides[key] = value
        self._save_overrides()
        return value

    def unset(self, key: str):
        self.overrides.pop(key, None)
        self._save_overrides()

    def _save_overrides(self):
        self.overrides_path.write_text(json.dumps(self.overrides, indent=2, ensure_ascii=False), encoding="utf-8")
        self._ov_mtime = self.overrides_path.stat().st_mtime


def coerce(raw: str, current):
    raw = raw.strip()
    if isinstance(current, bool):
        low = raw.lower()
        if low in ("true", "ja", "an", "on", "1"):
            return True
        if low in ("false", "nein", "aus", "off", "0"):
            return False
        raise ValueError("erwarte ja/nein")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw.replace(",", "."))
    return raw
