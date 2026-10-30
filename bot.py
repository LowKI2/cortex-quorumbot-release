"""Cortex QuorumBot: ein Discord-Bot pro Person, Leitplanken siehe guardrails.py.

Start:  python bot.py [config.yaml]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from config import Config
from guardrails import Budget, Decision, Guard, Incoming
from llm import LLM
from prompting import HistMsg, build_messages, build_system

log = logging.getLogger("runde")

HILFE = """**Befehle** (nur für meinen Besitzer)
`{p}dialog [runden] <thema>` – ich diskutiere mit {partner}
`{p}stopp` – laufenden Dialog beenden (darf jeder Mensch)
`{p}status` – Einstellungen und Budget
`{p}set <schlüssel> <wert>` – Einstellung ändern, z. B. `{p}set llm.temperature 0.5`
`{p}unset <schlüssel>` – zurück auf den Wert aus der config.yaml
`{p}reset` – Gesprächsverlauf ab hier neu beginnen
`{p}hilfe` – diese Übersicht"""


class RundenBot(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
        )
        self.cfg = cfg
        self.guard = Guard(cfg)
        self.budget = Budget(cfg, cfg.path.with_name(cfg.path.stem + ".budget.json"))
        self.llm = LLM(cfg)
        self.locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.tree = app_commands.CommandTree(self)
        self._synced = False

    async def setup_hook(self):
        from slash import setup_slash
        setup_slash(self)
        self.loop.create_task(self._heartbeat())

    async def _heartbeat(self):
        """Lebenszeichen für den Konfigurator (config.status.json)."""
        path = self.cfg.path.with_name(self.cfg.path.stem + ".status.json")
        while not self.is_closed():
            data = {"ts": time.time(), "pid": os.getpid(),
                    "online_as": str(self.user) if self.user else None,
                    "user_id": str(self.user.id) if self.user else None}
            try:
                path.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
            await asyncio.sleep(20)

    async def on_ready(self):
        log.info("Online als %s (%s)", self.user, self.user.id)
        if not self._synced:
            for guild in self.guilds:   # pro Server synchronisieren: sofort sichtbar
                try:
                    self.tree.copy_global_to(guild=guild)
                    cmds = await self.tree.sync(guild=guild)
                    log.info("Slash-Befehle auf %s: %s", guild.name, ", ".join(c.name for c in cmds))
                except discord.HTTPException as e:
                    log.warning("Slash-Befehle auf %s nicht möglich (%s) – Bot mit Scope applications.commands neu einladen", guild.name, e)
            self._synced = True
        if not self.cfg.get("bot.owner_id"):
            log.warning("bot.owner_id fehlt – der Bot reagiert auf niemanden.")

    # ------------------------------------------------------------------
    async def on_message(self, message: discord.Message):
        if self.cfg.reload_if_changed():
            log.info("Config neu geladen")
        if message.guild is None:
            return  # keine DMs
        inc = Incoming(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_is_bot=message.author.bot,
            content=message.content,
            mentions_me=self.user in message.mentions,
            is_own=message.author.id == self.user.id,
        )
        self.guard.observe(inc)
        if inc.is_own:
            return

        if not inc.author_is_bot and inc.author_id == int(self.cfg.get("bot.owner_id", 0)):
            cmd = self.guard.parse_command(message.content)
            if cmd and cmd[0] != "dialog" and not self.guard.is_stop(message.content):
                await self.handle_command(message, *cmd)
                return

        d = self.guard.decide(inc)
        if not d.respond:
            log.debug("ignoriert (%s): %s", d.reason, message.content[:60])
            return

        ok, why = self.budget.check()
        if not ok:
            log.info("Budget: %s", why)
            if d.mode != "dialog" or why != "Mindestabstand":
                await message.channel.send(f"-# {self.cfg.get('bot.name')} setzt aus: {why}")
            return
        self.budget.reserve()

        async with self.locks[message.channel.id]:
            await self.respond(message.channel, d)

    # ------------------------------------------------------------------
    async def respond(self, ch, d: Decision):
        st = self.guard.state(ch.id)
        try:
            async with ch.typing():
                history, names = await self.fetch_history(ch, st.context_after_id)
                system = build_system(self.cfg, d)
                msgs = build_messages(history, self.user.id, names)
                text, tin, tout = await self.llm.complete(system, msgs)
        except Exception as e:  # noqa: BLE001
            log.exception("LLM-Fehler")
            await ch.send(f"-# {self.cfg.get('bot.name')}: Fehler bei der Anfrage ({type(e).__name__})")
            return
        self.budget.record(tin + tout)

        if d.mode == "dialog" and st.halted:
            log.info("Antwort verworfen: Dialog wurde während der Generierung gestoppt")
            return

        text, pass_on = self.guard.finalize(ch.id, d, text)
        if not text:
            return
        parts = []
        partner_ids = self.cfg.get("bot.partner_bot_ids") or []
        if pass_on and partner_ids:
            parts.append(f"<@{partner_ids[0]}> ")
        parts.append(text)
        if d.mode in ("dialog_start", "dialog"):
            ende = "" if pass_on else " · Ende"
            parts.append(f"\n-# Runde {d.turn}/{d.limit}{ende}")
        await ch.send("".join(parts)[:1990])

    async def fetch_history(self, ch, after_id: int):
        limit = int(self.cfg.get("context.max_messages", 30))
        kwargs = {"limit": limit, "oldest_first": False}
        if after_id:
            kwargs["after"] = discord.Object(id=after_id)
        msgs = [m async for m in ch.history(**kwargs)]
        msgs.reverse()
        names: dict[int, str] = {}
        for m in msgs:
            names[m.author.id] = m.author.display_name
        for pid in self.cfg.get("bot.partner_bot_ids") or []:
            names.setdefault(int(pid), self.cfg.get("bot.partner_name", "Partner"))
        prefix = self.guard.prefix()
        hist = [
            HistMsg(m.author.id, names[m.author.id], m.content)
            for m in msgs
            if not (m.content.strip().startswith(prefix) and not m.content.strip()[len(prefix):].startswith("dialog"))
        ]
        return hist, names

    def status_text(self) -> str:
        keys = self.cfg.settable()
        lines = [f"**{self.cfg.get('bot.name')}** · {self.cfg.get('llm.provider')} / {self.cfg.get('llm.model')}"]
        lines += [f"`{k}` = {str(self.cfg.get(k))[:80]!s}" + (" *(Chat)*" if k in self.cfg.overrides else "") for k in keys]
        lines.append(self.budget.status())
        return "\n".join(lines)[:1990]

    # ------------------------------------------------------------------
    async def handle_command(self, message: discord.Message, cmd: str, args: str):
        ch = message.channel
        p = self.guard.prefix()
        if cmd in ("hilfe", "help"):
            await ch.send(HILFE.format(p=p, partner=self.cfg.get("bot.partner_name", "der anderen KI")))
        elif cmd == "status":
            await ch.send(self.status_text())
        elif cmd == "set":
            key, _, val = args.partition(" ")
            try:
                v = self.cfg.set(key.strip(), val)
                await ch.send(f"✓ `{key}` = {str(v)[:200]}")
            except (KeyError, ValueError) as e:
                await ch.send(f"✗ {e}")
        elif cmd == "unset":
            self.cfg.unset(args.strip())
            await ch.send(f"✓ `{args.strip()}` zurückgesetzt")
        elif cmd == "reset":
            self.guard.state(ch.id).context_after_id = message.id
            await ch.send("✓ Verlauf ab hier neu")
        else:
            await ch.send(f"Unbekannter Befehl. `{p}hilfe` zeigt alle.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    load_dotenv(cfg_path.parent / ".env")
    cfg = Config(cfg_path)
    token = os.environ.get(cfg.get("discord.token_env", "DISCORD_TOKEN"), "")
    if not token:
        sys.exit(f"Discord-Token fehlt: {cfg.get('discord.token_env')} in .env setzen")
    RundenBot(cfg).run(token, log_handler=None)


if __name__ == "__main__":
    main()
