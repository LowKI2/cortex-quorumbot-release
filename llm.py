"""LLM-Anbindung.

Drei Wege:
- anthropic:   Anthropic-API mit API-Key
- openai:      jede OpenAI-kompatible API (z. B. Ollama lokal)
- claude_code: Claude Code im Print-Modus (`claude -p`) mit dem eingeloggten Abo, ohne API-Key
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self._client = None
        self._sig = None

    def _client_for(self):
        provider = self.cfg.get("llm.provider", "anthropic")
        key = os.environ.get(self.cfg.get("llm.api_key_env", "") or "", "")
        base_url = self.cfg.get("llm.base_url")
        sig = (provider, key, base_url)
        if sig == self._sig and self._client:
            return provider, self._client
        if provider == "anthropic":
            from anthropic import AsyncAnthropic
            if not key:
                raise RuntimeError("API-Key fehlt (llm.api_key_env in .env setzen)")
            self._client = AsyncAnthropic(api_key=key, base_url=base_url or None)
        elif provider == "openai":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=key or "lokal", base_url=base_url or None)
        else:
            raise RuntimeError(f"Unbekannter Provider: {provider}")
        self._sig = sig
        return provider, self._client

    async def complete(self, system: str, messages: list[dict]):
        """Gibt (text, input_tokens, output_tokens) zurück."""
        if self.cfg.get("llm.provider", "anthropic") == "claude_code":
            return await self._claude_code(system, messages)

        provider, client = self._client_for()
        model = self.cfg.get("llm.model")
        max_tokens = int(self.cfg.get("llm.max_tokens", 800))
        temperature = self.cfg.get("llm.temperature")
        extra = {} if temperature is None else {"temperature": float(temperature)}

        if provider == "anthropic":
            resp = await client.messages.create(
                model=model, max_tokens=max_tokens, system=system, messages=messages, **extra
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return text, resp.usage.input_tokens, resp.usage.output_tokens

        resp = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, *messages],
            **extra,
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "prompt_tokens", 0) or 0
        tout = getattr(usage, "completion_tokens", 0) or 0
        return text, tin, tout

    # --- Abo-Variante ----------------------------------------------------
    def claude_code_command(self, system_file: str) -> list[str]:
        """Baut den Aufruf. Ohne Freigaben: keine Werkzeuge, keine MCP-Server."""
        exe = self.cfg.get("claude_code.path", "claude")
        resolved = shutil.which(exe) or exe
        cmd = [
            resolved, "-p",
            "--output-format", "json",
            "--system-prompt-file", system_file,
            "--no-session-persistence",
            "--permission-mode", "dontAsk",   # nur ausdrücklich freigegebene Werkzeuge laufen
            "--tools", "",                    # eingebaute Werkzeuge (Bash, Edit, ...) aus
            "--strict-mcp-config",            # MCP nur aus der eigenen Freigabedatei
        ]
        model = self.cfg.get("llm.model")
        if model:
            cmd += ["--model", str(model)]
        mcp_config = self.cfg.get("claude_code.mcp_config")
        allowed = self.cfg.get("claude_code.allowed_tools") or []
        if mcp_config:
            cmd += ["--mcp-config", str(mcp_config)]
        if allowed:
            cmd += ["--allowedTools", ",".join(allowed)]
        return cmd

    async def _claude_code(self, system: str, messages: list[dict]):
        workdir = Path(self.cfg.get("claude_code.workdir", "./claude-sandbox")).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        timeout = float(self.cfg.get("claude_code.timeout_seconds", 180))

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(system)
            system_file = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.claude_code_command(system_file),
                cwd=str(workdir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=abo_env(),
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(render_transcript(messages).encode("utf-8")), timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(f"claude -p hat nach {timeout:.0f} s nicht geantwortet")
        finally:
            try:
                os.unlink(system_file)
            except OSError:
                pass

        return parse_claude_json(out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode)


def abo_env() -> dict:
    """Umgebung für `claude -p` ohne API-Keys – sonst rechnet Claude Code über den Key ab statt übers Abo."""
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    return env


def render_transcript(messages: list[dict]) -> str:
    """Verlauf als Text für den Print-Modus. Eigene Beiträge sind markiert."""
    lines = ["Bisheriger Verlauf im Kanal (älteste zuerst):", ""]
    for m in messages:
        if m["role"] == "assistant":
            lines.append(f"[Du]: {m['content']}")
        else:
            lines.append(m["content"])
        lines.append("")
    lines.append("Schreib jetzt deine nächste Chat-Nachricht. Nur den Text, ohne Namenspräfix.")
    return "\n".join(lines)


def parse_claude_json(stdout: str, stderr: str, returncode: int | None):
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except (ValueError, IndexError):
        data = {}
    if returncode or not data or data.get("is_error"):
        detail = (data.get("result") if data else None) or stderr.strip() or stdout.strip()
        raise RuntimeError(f"claude -p fehlgeschlagen: {str(detail)[:300]}")
    usage = data.get("usage") or {}
    tin = int(usage.get("input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    return str(data.get("result", "")), tin, tout
