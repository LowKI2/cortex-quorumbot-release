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
import re
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
        import knowledge
        reader = knowledge.reader(self.cfg)          # Wissensordner/Repos → Lese-Werkzeuge
        rounds = int(self.cfg.get("knowledge.max_tool_rounds", 6) or 6)

        if provider == "anthropic":
            if not _accepts(client.messages.create, "temperature"):
                extra = {}          # anthropic-SDK ab 2.x kennt temperature nicht mehr (neue Modelle steuern das selbst)
            if reader:
                extra["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
                                  for t in TOOL_DEFS]
            msgs, tin, tout = list(messages), 0, 0
            for step in range(rounds + 1):
                if step == rounds:
                    extra.pop("tools", None)        # letzte Runde: ohne Werkzeuge, damit eine Antwort kommt
                    msgs.append({"role": "user", "content": "Bitte antworte jetzt mit dem, was du gefunden hast."})
                resp = await client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=msgs, **extra)
                tin += resp.usage.input_tokens
                tout += resp.usage.output_tokens
                uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
                if not uses or not reader:
                    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                    return text, tin, tout
                msgs.append({"role": "assistant", "content": [_block(b) for b in resp.content]})
                msgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": u.id, **run_tool(reader, u.name, u.input)} for u in uses]})
            return "", tin, tout

        kw = dict(extra)
        if reader:
            kw["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                             "parameters": t["inputSchema"]}} for t in TOOL_DEFS]
        msgs, tin, tout = [{"role": "system", "content": system}, *messages], 0, 0
        for step in range(rounds + 1):
            if step == rounds:
                kw.pop("tools", None)
                msgs.append({"role": "user", "content": "Bitte antworte jetzt mit dem, was du gefunden hast."})
            resp = await client.chat.completions.create(model=model, max_tokens=max_tokens, messages=msgs, **kw)
            usage = getattr(resp, "usage", None)
            tin += getattr(usage, "prompt_tokens", 0) or 0
            tout += getattr(usage, "completion_tokens", 0) or 0
            m = resp.choices[0].message
            calls = getattr(m, "tool_calls", None) or []
            if not calls or not reader:
                return m.content or "", tin, tout
            msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except ValueError:
                    args = {}
                res = run_tool(reader, c.function.name, args)
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": res["content"]})
        return "", tin, tout

    # --- Abo-Variante ----------------------------------------------------
    def claude_code_command(self, system_file: str, knowledge_config: str | None = None) -> list[str]:
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
        import knowledge
        mcp_configs = [str(c) for c in (self.cfg.get("claude_code.mcp_config"), knowledge_config) if c]
        allowed = list(self.cfg.get("claude_code.allowed_tools") or [])
        if knowledge_config:
            allowed += knowledge.allowed_tool_names(self.cfg)
            cmd += ["--disallowedTools", ",".join(knowledge.DENIED)]
        if mcp_configs:
            cmd += ["--mcp-config", *mcp_configs]
        if allowed:
            cmd += ["--allowedTools", ",".join(allowed)]
        return cmd

    async def _claude_code(self, system: str, messages: list[dict]):
        workdir = Path(self.cfg.get("claude_code.workdir", "./claude-sandbox")).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        timeout = float(self.cfg.get("claude_code.timeout_seconds", 180))

        import knowledge
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(system)
            system_file = f.name
        knowledge_config = knowledge.write_mcp_config(self.cfg, dict(os.environ))
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.claude_code_command(system_file, knowledge_config),
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
            for tmp in (system_file, knowledge_config):
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

        return parse_claude_json(out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode)


from wissen_ordner import TOOLS as TOOL_DEFS  # noqa: E402

TOOL_RESULT_MAX = 20000


def run_tool(reader, name: str, args) -> dict:
    """Lese-Werkzeug ausführen. Nur list_files/search/read_file – sonst nichts."""
    fn = {"list_files": reader.list_files, "search": reader.search, "read_file": reader.read_file}.get(name)
    if fn is None:
        return {"content": f"Unbekanntes Werkzeug {name}", "is_error": True}
    try:
        args = {k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames}
        text = fn(**args)
    except (ValueError, OSError, TypeError) as e:
        return {"content": f"Fehler: {e}", "is_error": True}
    if len(text) > TOOL_RESULT_MAX:
        text = text[:TOOL_RESULT_MAX] + "\n[… gekürzt]"
    return {"content": text}


def _block(b) -> dict:
    t = getattr(b, "type", "")
    if t == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return {"type": "text", "text": getattr(b, "text", "")}


def _accepts(fn, name: str) -> bool:
    """Nimmt die Funktion diesen Parameter an? (SDK-Versionen unterscheiden sich.)"""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def abo_env() -> dict:
    """Umgebung für `claude -p` ohne Schlüssel und Tokens.

    API-Keys würden das Abo aushebeln (Claude Code rechnet dann über den Key ab), und Discord-Token,
    MediaVault-Schlüssel usw. braucht Claude nicht – MediaVault bekommt er über die MCP-Konfiguration.
    Die Anmeldung von Claude Code selbst (CLAUDE_*) bleibt erhalten.
    """
    from version import child_env
    secret = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD)", re.I)
    env = {k: v for k, v in os.environ.items() if k.upper().startswith("CLAUDE") or not secret.search(k)}
    return child_env(env)          # Claude startet ggf. den Wissensordner-Server aus der exe


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
