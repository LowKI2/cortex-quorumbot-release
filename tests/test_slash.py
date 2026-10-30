import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from bot import RundenBot  # noqa: E402
from config import Config  # noqa: E402
from slash import group_name, setup_slash  # noqa: E402

OWNER = 123456789012345678


def make_bot(tmp_path, **extra):
    p = tmp_path / "config.yaml"
    p.write_text(f"bot:\n  name: Nova Prime\n  owner_id: {OWNER}\n  partner_bot_ids: [223456789012345678]\n"
                 "llm:\n  provider: claude_code\n  model: sonnet\n", encoding="utf-8")
    return RundenBot(Config(p))


def test_befehle_registriert(tmp_path):
    async def run():
        bot = make_bot(tmp_path)
        grp = setup_slash(bot)
        assert grp.name == "nova-prime"
        names = sorted(c.name for c in grp.commands)
        assert names == ["beitreten", "dialog", "panel", "set", "status", "stopp", "verlassen", "zuruecksetzen"]
        dialog = next(c for c in grp.commands if c.name == "dialog")
        runden = next(p for p in dialog.parameters if p.name == "runden")
        assert runden.min_value == 1 and runden.max_value == 30 and not runden.required
        await bot.close()
    asyncio.run(run())


def test_gruppenname_fallback():
    assert group_name(Config("x", data={"bot": {"name": "!!!"}})) == "runde"


def test_panel_baut_und_respektiert_rechte(tmp_path):
    async def run():
        bot = make_bot(tmp_path)
        bot.cfg.base.setdefault("guardrails", {})["settable_keys"] = ["llm.model"]
        setup_slash(bot)
        view = bot.panel_view()
        buttons = {c.label: c for c in view.children if isinstance(c, discord.ui.Button)}
        selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
        assert buttons["Nur bei Erwähnung: an"].disabled          # nicht freigegeben
        assert buttons["Persona bearbeiten"].disabled
        model_sel = next(s for s in selects if s.placeholder.startswith("Modell"))
        assert not model_sel.disabled
        assert [o.value for o in model_sel.options] == ["sonnet", "haiku", "opus"]  # Abo: Kurzformen
        assert "nova" in bot.panel_text().lower() or "Nova" in bot.panel_text()
        await bot.close()
    asyncio.run(run())


def test_start_und_stopp_ueber_guard(tmp_path):
    bot = make_bot(tmp_path)
    d = bot.guard.start_dialog(1, 50, "Thema")
    assert d.respond and d.limit == 12 and d.mode == "dialog_start"
    bot.guard.stop(1)
    assert bot.guard.state(1).halted
