"""Slash-Befehle und Einstellungs-Panel in Discord.

Befehlsgruppe heißt wie der Bot, z. B. /nova status – so kommen sich die Befehle
beider Bots nicht in die Quere. Antworten sind nur für den Aufrufer sichtbar.
"""
from __future__ import annotations

import re

import discord
from discord import app_commands

from guardrails import HARD_MAX_ROUNDS
from settings_schema import FIELDS

PANEL_BOOLS = [
    ("guardrails.require_mention_from_owner", "Nur bei Erwähnung"),
    ("guardrails.allow_bot_dialog", "Bot-Dialoge"),
    ("guardrails.respond_to_owner", "Antwortet mir"),
    ("voice.output", "Sprechen"),
]


def group_name(cfg) -> str:
    name = re.sub(r"[^a-z0-9_-]", "", (cfg.get("bot.name") or "").lower().replace(" ", "-"))[:32]
    return name or "runde"


def fmt(v) -> str:
    if isinstance(v, bool):
        return "an" if v else "aus"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "–"
    return str(v)


def setup_slash(bot):
    cfg = bot.cfg
    grp = app_commands.Group(name=group_name(cfg), description=f"Steuerung von {cfg.get('bot.name') or 'Bot'}",
                             guild_only=True)

    def is_owner(i: discord.Interaction) -> bool:
        from bot import has_required_role
        return i.user.id == int(cfg.get("bot.owner_id", 0) or 0) and (i.guild is None or has_required_role(cfg, i.guild))

    async def deny(i: discord.Interaction):
        await i.response.send_message("Das darf nur der Besitzer dieses Bots.", ephemeral=True)

    async def key_ac(i: discord.Interaction, current: str):
        return [app_commands.Choice(name=k, value=k) for k in cfg.settable()
                if current.lower() in k.lower()][:25]

    async def value_ac(i: discord.Interaction, current: str):
        key = getattr(i.namespace, "schluessel", "") or ""
        f = FIELDS.get(key, {})
        if f.get("type") == "bool":
            opts = ["ja", "nein"]
        elif f.get("type") == "select":
            opts = list(f["options"])
        else:
            opts = list(f.get("suggest", []))
            cur = cfg.get(key)
            if cur is not None and f.get("type") not in ("textarea",):
                opts.insert(0, fmt(cur)[:100])
        return [app_commands.Choice(name=o[:100], value=o[:100]) for o in dict.fromkeys(opts)
                if current.lower() in o.lower()][:25]

    # --- /<bot> status ------------------------------------------------
    @grp.command(name="status", description="Einstellungen und Verbrauch anzeigen")
    async def status(i: discord.Interaction):
        if not is_owner(i):
            return await deny(i)
        await i.response.send_message(bot.status_text(), ephemeral=True)

    # --- /<bot> set ---------------------------------------------------
    @grp.command(name="set", description="Eine Einstellung ändern")
    @app_commands.describe(schluessel="Welche Einstellung", wert="Neuer Wert")
    @app_commands.autocomplete(schluessel=key_ac, wert=value_ac)
    async def set_(i: discord.Interaction, schluessel: str, wert: str):
        if not is_owner(i):
            return await deny(i)
        try:
            v = cfg.set(schluessel, wert)
        except (KeyError, ValueError) as e:
            return await i.response.send_message(f"✗ {e}", ephemeral=True)
        await i.response.send_message(f"✓ `{schluessel}` = {fmt(v)[:300]}", ephemeral=True)

    # --- /<bot> zuruecksetzen ----------------------------------------
    @grp.command(name="zuruecksetzen", description="Chat-Wert entfernen, es gilt wieder die config.yaml")
    @app_commands.describe(schluessel="Leer lassen = alle Chat-Werte entfernen")
    @app_commands.autocomplete(schluessel=key_ac)
    async def reset(i: discord.Interaction, schluessel: str | None = None):
        if not is_owner(i):
            return await deny(i)
        if schluessel:
            cfg.unset(schluessel)
            return await i.response.send_message(f"✓ `{schluessel}` zurückgesetzt", ephemeral=True)
        for k in list(cfg.overrides):
            cfg.unset(k)
        await i.response.send_message("✓ Alle Chat-Werte entfernt", ephemeral=True)

    # --- /<bot> dialog -----------------------------------------------
    @grp.command(name="dialog", description="Dialog mit dem Partner-Bot starten")
    @app_commands.describe(thema="Worüber", runden="Bot-Antworten insgesamt (beide Bots)")
    async def dialog(i: discord.Interaction, thema: str,
                     runden: app_commands.Range[int, 1, HARD_MAX_ROUNDS] | None = None):
        if not is_owner(i):
            return await deny(i)
        d = bot.guard.start_dialog(i.channel_id, runden, thema)
        if not d.respond:
            return await i.response.send_message(f"Geht nicht: {d.reason}", ephemeral=True)
        ok, why = bot.budget.check()
        if not ok:
            return await i.response.send_message(f"Geht gerade nicht: {why}", ephemeral=True)
        bot.budget.reserve()
        await i.response.send_message(f"**{i.user.display_name}** startet einen Dialog ({d.limit} Runden): {thema}")
        async with bot.locks[i.channel_id]:
            await bot.respond(i.channel, d)

    # --- /<bot> stopp (jeder Mensch) ---------------------------------
    @grp.command(name="stopp", description="Laufenden Dialog beenden")
    async def stopp(i: discord.Interaction):
        bot.guard.stop(i.channel_id)
        await i.response.send_message(f"⏹ Dialog gestoppt von {i.user.display_name}")

    # --- /<bot> beitreten / verlassen ---------------------------------
    @grp.command(name="beitreten", description="In deinen Sprachraum kommen (Sprache, Beta)")
    async def beitreten(i: discord.Interaction):
        if not is_owner(i):
            return await deny(i)
        if not bot.voice.enabled:
            return await i.response.send_message("Sprache ist aus – im Konfigurator unter „Sprache“ einschalten.", ephemeral=True)
        vs = getattr(i.user, "voice", None)
        if not vs or not vs.channel:
            return await i.response.send_message("Geh zuerst in einen Sprachraum.", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            text = await bot.voice.join(vs.channel)
        except Exception as e:  # noqa: BLE001
            text = f"Beitreten fehlgeschlagen ({type(e).__name__}: {str(e)[:120]})"
        await i.followup.send(text, ephemeral=True)

    @grp.command(name="verlassen", description="Sprachraum verlassen")
    async def verlassen(i: discord.Interaction):
        if not is_owner(i):
            return await deny(i)
        await i.response.send_message(await bot.voice.leave(), ephemeral=True)

    # --- /<bot> panel -------------------------------------------------
    @grp.command(name="panel", description="Einstellungen mit Schaltern")
    async def panel(i: discord.Interaction):
        if not is_owner(i):
            return await deny(i)
        await i.response.send_message(panel_text(), view=PanelView(), ephemeral=True)

    def panel_text() -> str:
        ov = len(cfg.overrides)
        return (f"**{cfg.get('bot.name')}** · {cfg.get('llm.provider')} / {cfg.get('llm.model')}\n"
                f"Dialog: {cfg.get('guardrails.dialog_default_rounds', 6)} Runden, "
                f"max. {cfg.get('guardrails.dialog_max_minutes', 5)} min · "
                f"{cfg.get('guardrails.max_requests_per_hour', 60)} Anfragen/h\n"
                f"{bot.budget.status()}" + (f"\n-# {ov} Wert(e) per Chat überschrieben" if ov else ""))

    class PersonaModal(discord.ui.Modal, title="Persona bearbeiten"):
        text = discord.ui.TextInput(label="System-Prompt", style=discord.TextStyle.paragraph,
                                    max_length=4000, required=False)

        def __init__(self):
            super().__init__()
            self.text.default = (cfg.get("persona.system_prompt") or "")[:4000]

        async def on_submit(self, i: discord.Interaction):
            try:
                cfg.set("persona.system_prompt", str(self.text.value))
            except (KeyError, ValueError) as e:
                return await i.response.send_message(f"✗ {e}", ephemeral=True)
            await i.response.send_message("✓ Persona gespeichert", ephemeral=True)

    class PanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=600)
            allowed = set(cfg.settable())
            for key, label in PANEL_BOOLS:
                if key.startswith("voice.") and not cfg.get("voice.enabled"):
                    continue
                on = bool(cfg.get(key, True))
                b = discord.ui.Button(label=f"{label}: {'an' if on else 'aus'}",
                                      style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
                                      disabled=key not in allowed, row=0)
                b.callback = self._toggle(key)
                self.add_item(b)

            cur = int(cfg.get("guardrails.dialog_default_rounds", 6))
            maxr = int(cfg.get("guardrails.dialog_max_rounds", 12))
            rounds = sorted({2, 4, 6, 8, 10, 12, cur} & set(range(1, maxr + 1)) or {cur})
            sel = discord.ui.Select(placeholder=f"Runden pro Dialog: {cur}", row=1,
                                    disabled="guardrails.dialog_default_rounds" not in allowed,
                                    options=[discord.SelectOption(label=f"{r} Runden", value=str(r), default=r == cur)
                                             for r in rounds])
            sel.callback = self._select("guardrails.dialog_default_rounds", sel)
            self.add_item(sel)

            models = FIELDS["llm.model"]["suggest"]
            models = [m for m in models if ("-" in m) != (cfg.get("llm.provider") == "claude_code")] or models
            curm = str(cfg.get("llm.model") or "")
            msel = discord.ui.Select(placeholder=f"Modell: {curm}", row=2, disabled="llm.model" not in allowed,
                                     options=[discord.SelectOption(label=m, value=m, default=m == curm) for m in models])
            msel.callback = self._select("llm.model", msel)
            self.add_item(msel)

            pb = discord.ui.Button(label="Persona bearbeiten", style=discord.ButtonStyle.primary, row=3,
                                   disabled="persona.system_prompt" not in allowed)
            pb.callback = self._persona
            self.add_item(pb)
            rb = discord.ui.Button(label="Chat-Werte zurücksetzen", style=discord.ButtonStyle.danger, row=3,
                                   disabled=not cfg.overrides)
            rb.callback = self._reset
            self.add_item(rb)

        async def interaction_check(self, i: discord.Interaction) -> bool:
            if not is_owner(i):
                await deny(i)
                return False
            return True

        async def _refresh(self, i: discord.Interaction):
            await i.response.edit_message(content=panel_text(), view=PanelView())

        def _toggle(self, key):
            async def cb(i: discord.Interaction):
                cfg.set(key, "nein" if cfg.get(key, True) else "ja")
                await self._refresh(i)
            return cb

        def _select(self, key, sel):
            async def cb(i: discord.Interaction):
                try:
                    cfg.set(key, sel.values[0])
                except (KeyError, ValueError) as e:
                    return await i.response.send_message(f"✗ {e}", ephemeral=True)
                await self._refresh(i)
            return cb

        async def _persona(self, i: discord.Interaction):
            await i.response.send_modal(PersonaModal())

        async def _reset(self, i: discord.Interaction):
            for k in list(cfg.overrides):
                cfg.unset(k)
            await self._refresh(i)

    bot.tree.add_command(grp)
    bot.panel_view, bot.panel_text = PanelView, panel_text  # für Tests
    return grp
