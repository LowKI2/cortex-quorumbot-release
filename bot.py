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
from voice_notifier import attach_voice_notifier

log = logging.getLogger("runde")

HILFE = """**Befehle** (nur für meinen Besitzer)
`{p}dialog [runden] <thema>` – ich diskutiere mit {partner}
`{p}stopp` – laufenden Dialog beenden (darf jeder Mensch)
`{p}status` – Einstellungen und Budget
`{p}set <schlüssel> <wert>` – Einstellung ändern, z. B. `{p}set llm.temperature 0.5`
`{p}unset <schlüssel>` – zurück auf den Wert aus der config.yaml
`{p}reset` – Verlauf zurücksetzen (bei beiden Bots; je nach Einstellung vorher zusammenfassen und speichern)
`{p}speichern` – den letzten Dialog als Datei speichern
`{p}hilfe` – diese Übersicht"""


def mentioned_ids(message) -> set[int]:
    """Erwähnte Nutzer – auch wenn statt des Bots seine automatische Rolle gleichen Namens erwähnt wurde
    (Discord schlägt beim Tippen von @Name oft die Rolle zuerst vor)."""
    ids = {u.id for u in message.mentions}
    for role in getattr(message, "role_mentions", []) or []:
        bot_id = getattr(getattr(role, "tags", None), "bot_id", None)
        if bot_id:
            ids.add(int(bot_id))
    return ids


class RundenBot(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True          # für den Voice-Join-Melder (nicht privilegiert)
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
        )
        self.cfg = cfg
        self.guard = Guard(cfg)
        self.budget = Budget(cfg, cfg.path.with_name(cfg.path.stem + ".budget.json"))
        import verlauf
        self.context_store = verlauf.ContextStore(cfg.path.with_name(cfg.path.stem + ".kontext.json"))
        for cid, v in self.context_store.data.items():      # Reset-Stand nach Neustart wiederherstellen
            st = self.guard.state(int(cid))
            st.context_after_id = int(v.get("after_id") or 0)
            st.summary = v.get("summary") or ""
        self.llm = LLM(cfg)
        self.locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.pending_purge: dict[int, int] = {}      # Kanal → Nachricht bis zu der gelöscht wird (wartet auf Partner)
        self.tree = app_commands.CommandTree(self)
        self._synced = False
        attach_voice_notifier(self, self._notifier_config)

    def _notifier_config(self) -> dict:
        """Melder-Einstellungen aus config.yaml (+ Chat-Werte), live neu geladen."""
        self.cfg.reload_if_changed()
        keys = ("enabled", "watch", "disabled_guilds", "cooldown_seconds", "template")
        return {k: self.cfg.get(f"voice_notifier.{k}") for k in keys if self.cfg.get(f"voice_notifier.{k}") is not None}

    async def setup_hook(self):
        from slash import setup_slash
        setup_slash(self)
        self.loop.create_task(self._heartbeat())
        self.loop.create_task(self._github_loop())

    async def _github_loop(self):
        """GitHub-Wissen im Hintergrund aktuell halten (nur bei Änderungen wird neu geladen)."""
        import wissen_github
        from dotenv import dotenv_values
        await asyncio.sleep(3)
        while not self.is_closed():
            try:
                if self.cfg.get("knowledge.github.enabled") and wissen_github.repos(self.cfg) and wissen_github.due(self.cfg):
                    env = {**os.environ, **dotenv_values(self.cfg.path.parent / ".env")}
                    for r in await asyncio.to_thread(wissen_github.sync, self.cfg, env):
                        if r["ok"] and r.get("updated"):
                            log.info("GitHub-Wissen: %s@%s geladen (%s Dateien)", r["repo"], r["ref"], r["files"])
                        elif not r["ok"]:
                            log.warning("GitHub-Wissen: %s", r["error"])
            except Exception as e:  # noqa: BLE001
                log.warning("GitHub-Wissen: Abgleich fehlgeschlagen (%s)", e)
            await asyncio.sleep(120)

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
        mentioned = mentioned_ids(message)
        inc = Incoming(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_is_bot=message.author.bot,
            content=message.content,
            mentions_me=self.user.id in mentioned,
            is_own=message.author.id == self.user.id,
            mention_ids=tuple(mentioned),
            msg_id=message.id,
            author_name=getattr(message.author, "display_name", "") or message.author.name,
        )
        self.guard.observe(inc)
        import verlauf
        if inc.author_is_bot and verlauf.is_dialog_end(message.content) and self.cfg.get("context.dialog_save", False) \
                and self.guard.channel_allowed(message.channel.id) and (inc.is_own or inc.author_id in self.guard.partner_ids()):
            self.loop.create_task(self.save_dialog(message.channel, message.id, auto=True))
        if inc.is_own:
            return

        if (inc.author_is_bot and inc.author_id in self.guard.partner_ids() and verlauf.RESET_ACK in message.content
                and message.channel.id in self.pending_purge):
            self.pending_purge.pop(message.channel.id)
            await self.purge_chat(message.channel, message.id)   # Partner hat gespeichert → jetzt löschen
            return

        if (inc.author_is_bot and inc.author_id in self.guard.partner_ids() and verlauf.is_reset_start(message.content)
                and self.guard.channel_allowed(message.channel.id) and self.cfg.get("context.reset_follow_partner", True)):
            log.info("Partner setzt Verlauf zurück – mache mit")
            async with self.locks[message.channel.id]:
                await self.reset_context(message.channel, message.id, initiator=False)
            return

        if not inc.author_is_bot and inc.author_id == int(self.cfg.get("bot.owner_id", 0)):
            cmd = self.guard.parse_command(message.content)
            if cmd and cmd[0] != "dialog" and not self.guard.is_stop(message.content):
                await self.handle_command(message, *cmd)
                return

        d = self.guard.decide(inc)
        if not d.respond:
            # Wenn der Bot direkt angesprochen wurde, Grund sichtbar loggen – hilft bei „reagiert nicht“.
            (log.info if inc.mentions_me else log.debug)("ignoriert von %s (%s): %s", message.author, d.reason, message.content[:80])
            return
        if d.mode == "foreign":
            log.info("Standardantwort an %s", message.author)
            await message.reply(d.text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
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
                system = build_system(self.cfg, d, summary=st.summary)
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

    async def save_dialog(self, ch, until_id: int, auto: bool):
        """Letzten Dialog (ab seiner Eröffnung) als Markdown speichern – ohne KI, kostet nichts."""
        import verlauf
        st = self.guard.state(ch.id)
        name = self.cfg.get("bot.name") or "Bot"
        if not st.dialog_start_id:
            if not auto:
                await ch.send(f"-# {name}: Kein Dialog seit dem Start des Bots gefunden.")
            return
        try:
            history, names = await self.fetch_history(ch, st.dialog_start_id - 1, before_id=until_id + 1, raw=True)
            text = verlauf.transcript(history, names, keep_commands=True)
            if not text.strip():
                return
            path = verlauf.save_dialog(self.cfg, getattr(ch, "name", str(ch.id)), st.dialog_title, text)
        except Exception as e:  # noqa: BLE001
            log.exception("Dialog speichern fehlgeschlagen")
            if not auto:
                await ch.send(f"⚠️ {name}: Dialog speichern fehlgeschlagen ({type(e).__name__}).")
            return
        log.info("Dialog gespeichert: %s", path)
        await ch.send(f"-# 💾 {name}: Dialog gespeichert ({verlauf.rel(self.cfg, path)})")

    async def reset_context(self, ch, after_id: int, initiator: bool):
        """Verlauf zurücksetzen – bei „Speichern“ vorher zusammenfassen und als Datei ablegen."""
        import verlauf
        st = self.guard.state(ch.id)
        name = self.cfg.get("bot.name") or "Bot"
        marker = verlauf.RESET_START if initiator else verlauf.RESET_ACK
        summary = ""
        if self.cfg.get("context.reset_save", False):
            try:
                history, names = await self.fetch_history(ch, st.context_after_id, before_id=after_id)
                raw = verlauf.transcript(history, names)
                if raw.strip():
                    async with ch.typing():
                        summary, tin, tout = await self.llm.complete(
                            verlauf.SUMMARY_SYSTEM, [{"role": "user", "content": raw}], use_knowledge=False)
                    self.budget.record(tin + tout)
                    path = verlauf.save(self.cfg, getattr(ch, "name", str(ch.id)), summary,
                                        raw if self.cfg.get("context.reset_raw", False) else None)
                    note = f"✅ {name}: Verlauf zusammengefasst und gespeichert ({verlauf.rel(self.cfg, path)}) – Kontext ist neu."
                else:
                    note = f"✅ {name}: Nichts zu speichern (Verlauf war leer) – Kontext ist neu."
            except Exception as e:  # noqa: BLE001
                log.exception("Speichern beim Reset fehlgeschlagen")
                await ch.send(f"⚠️ {name}: Zusammenfassen/Speichern fehlgeschlagen ({type(e).__name__}) – Verlauf bleibt.")
                return
        else:
            note = f"{name}: " + (self.cfg.get("context.reset_no_save_text") or verlauf.DEFAULT_NO_SAVE)
        carry = summary if (summary and self.cfg.get("context.reset_carry_summary", True)) else ""
        st.context_after_id, st.summary = after_id, carry
        st.bot_turns, st.in_dialog = 0, False
        self.context_store.set(ch.id, after_id=after_id, summary=carry)
        sent = await ch.send(f"{note}\n{marker}"[:1990])
        if initiator and self.cfg.get("context.reset_delete", False):
            if self.cfg.get("bot.partner_bot_ids") and self.cfg.get("context.reset_follow_partner", True):
                # Erst löschen, wenn der Partner seinen Verlauf gesichert hat (Bestätigung) – spätestens nach 3 min.
                self.pending_purge[ch.id] = sent.id
                asyncio.create_task(self._purge_after_timeout(ch, sent.id, 180))
            else:
                await self.purge_chat(ch, sent.id)

    async def _purge_after_timeout(self, ch, until_id: int, seconds: float):
        await asyncio.sleep(seconds)
        if self.pending_purge.get(ch.id) == until_id:
            self.pending_purge.pop(ch.id)
            log.info("Partner hat den Reset nicht bestätigt – lösche trotzdem")
            await self.purge_chat(ch, until_id)

    async def purge_chat(self, ch, until_id: int):
        """Alle Nachrichten im Kanal bis einschließlich until_id löschen (angeheftete bleiben)."""
        name = self.cfg.get("bot.name") or "Bot"
        me = getattr(getattr(ch, "guild", None), "me", None)
        can = bool(me and ch.permissions_for(me).manage_messages)
        own = me.id if me else self.user.id
        try:
            if can:
                gone = await ch.purge(limit=None, before=discord.Object(id=until_id + 1), check=lambda m: not m.pinned,
                                      reason="!reset – Verlauf gesichert")
                await ch.send(f"-# 🧹 {name}: Chat geleert ({len(gone)} Nachrichten).")
            else:
                gone = await ch.purge(limit=None, before=discord.Object(id=until_id + 1), bulk=False,
                                      check=lambda m: m.author.id == own and not m.pinned)
                await ch.send(f"-# 🧹 {name}: Nur meine eigenen Nachrichten gelöscht ({len(gone)}) – für den ganzen Chat "
                              "braucht meine Rolle das Recht „Nachrichten verwalten“.")
        except discord.HTTPException as e:
            log.warning("Chat löschen fehlgeschlagen: %s", e)
            await ch.send(f"-# ⚠️ {name}: Chat löschen fehlgeschlagen ({e.status}).")

    async def fetch_history(self, ch, after_id: int, before_id: int | None = None, raw: bool = False):
        limit = int(self.cfg.get("context.max_messages", 30))
        kwargs = {"limit": limit if before_id is None else max(limit, 300), "oldest_first": False}
        if after_id:
            kwargs["after"] = discord.Object(id=after_id)
        if before_id:
            kwargs["before"] = discord.Object(id=before_id)
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
            if raw or (not (m.content.strip().startswith(prefix) and not m.content.strip()[len(prefix):].startswith("dialog"))
                       and "-# Kontext-Reset" not in m.content and "Dialog gespeichert" not in m.content)
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
            async with self.locks[ch.id]:
                await self.reset_context(ch, message.id, initiator=True)
        elif cmd in ("speichern", "save"):
            await self.save_dialog(ch, message.id, auto=False)
        else:
            await ch.send(f"Unbekannter Befehl. `{p}hilfe` zeigt alle.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    load_dotenv(cfg_path.parent / ".env")
    cfg = Config(cfg_path)
    import updater
    updater.cleanup_old()
    if updater.auto_update(cfg.get("update.mode", "manuell"), "bot", cfg_path, log=logging.info):
        sys.exit(updater.RESTART_CODE)
    token = os.environ.get(cfg.get("discord.token_env", "DISCORD_TOKEN"), "")
    if not token:
        sys.exit(f"Discord-Token fehlt: {cfg.get('discord.token_env')} in .env setzen")
    RundenBot(cfg).run(token, log_handler=None)


if __name__ == "__main__":
    main()
