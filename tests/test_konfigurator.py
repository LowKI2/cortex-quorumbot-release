import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from konfigurator import Store, read_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OWNER, PARTNER, CH = "123456789012345678", "223456789012345678", "323456789012345678"


def store(tmp_path, with_example=True):
    if with_example:
        (tmp_path / "config.example.yaml").write_text((ROOT / "config.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return Store(tmp_path / "config.yaml")


def test_neue_config_aus_vorlage_und_speichern(tmp_path):
    s = store(tmp_path)
    st = s.state()
    assert not st["exists"] and st["values"]["bot.name"] == "Nova"
    assert any("User-ID fehlt" in e for e in st["errors"])
    r = s.save({"bot.owner_id": OWNER, "bot.partner_bot_ids": PARTNER,
                "discord.allowed_channel_ids": CH, "llm.provider": "claude_code", "llm.model": "sonnet"})
    assert r["ok"], r
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["bot"]["owner_id"] == int(OWNER) and data["bot"]["partner_bot_ids"] == [int(PARTNER)]
    assert data["llm"]["provider"] == "claude_code"
    assert data["guardrails"]["dialog_max_rounds"] == 12  # Rest der Vorlage bleibt erhalten
    st = s.state()
    assert st["values"]["bot.owner_id"] == OWNER  # als Text, damit JS die ID nicht rundet


def test_feldfehler_werden_gemeldet_und_nichts_geschrieben(tmp_path):
    s = store(tmp_path)
    r = s.save({"bot.owner_id": "abc", "guardrails.dialog_max_rounds": "99", "llm.provider": "gpt"})
    assert not r["ok"]
    assert set(r["field_errors"]) == {"bot.owner_id", "guardrails.dialog_max_rounds", "llm.provider"}
    assert not (tmp_path / "config.yaml").exists()


def test_eigene_id_als_partner_ist_fehler(tmp_path):
    s = store(tmp_path)
    r = s.save({"bot.owner_id": OWNER, "bot.partner_bot_ids": OWNER})
    assert not r["ok"] and "Partner" in r["errors"][0]


def test_backup_beim_ueberschreiben(tmp_path):
    s = store(tmp_path)
    assert s.save({"bot.owner_id": OWNER})["ok"]
    assert s.save({"bot.owner_id": OWNER, "bot.name": "Lyra"})["ok"]
    assert (tmp_path / "config.yaml.bak").exists()


def test_geheimnisse_nur_bekannte_variablen_und_nie_im_klartext(tmp_path):
    s = store(tmp_path)
    (tmp_path / ".env").write_text("# Kommentar\nDISCORD_TOKEN=\nANDERES=1\n", encoding="utf-8")
    assert s.set_secret("DISCORD_TOKEN", "abc.def")["ok"]
    assert not s.set_secret("PATH", "x")["ok"]
    assert not s.set_secret("DISCORD_TOKEN", "a\nB=1")["ok"]
    env = read_env(tmp_path / ".env")
    assert env == {"DISCORD_TOKEN": "abc.def", "ANDERES": "1"}
    st = s.state()
    assert st["secrets"]["DISCORD_TOKEN"] is True and "abc.def" not in json.dumps(st)


def test_chat_overrides_anzeigen_und_entfernen(tmp_path):
    s = store(tmp_path)
    s.save({"bot.owner_id": OWNER})
    (tmp_path / "config.overrides.json").write_text(json.dumps({"llm.temperature": 0.2, "guardrails.dialog_max_rounds": 3}))
    assert s.state()["overrides"]["llm.temperature"] == 0.2
    s.clear_override("llm.temperature")
    assert list(s.state()["overrides"]) == ["guardrails.dialog_max_rounds"]
    s.clear_override(None)
    assert s.state()["overrides"] == {}


def test_einladungslink(tmp_path):
    s = store(tmp_path)
    assert not s.invite()["ok"]
    s.save({"bot.owner_id": OWNER, "discord.application_id": "423456789012345678"})
    url = s.invite()["url"]
    assert "client_id=423456789012345678" in url and "permissions=68608" in url


def test_chat_set_nutzt_grenzen(tmp_path):
    from config import Config
    p = tmp_path / "config.yaml"
    p.write_text("guardrails:\n  dialog_max_rounds: 12\n", encoding="utf-8")
    c = Config(p)
    try:
        c.set("guardrails.dialog_max_rounds", "500")
        raise AssertionError("Grenze nicht geprüft")
    except ValueError:
        pass


def test_assistent_speichert_entwurf_ohne_owner(tmp_path):
    s = store(tmp_path)
    r = s.save({"llm.provider": "claude_code", "bot.name": "Lyra"}, draft=True)
    assert r["ok"] and r["errors"]          # unvollständig, aber gespeichert
    assert s.state()["values"]["bot.name"] == "Lyra"
    assert not s.state()["wizard_done"]
    s.wizard_done()
    assert s.state()["wizard_done"]
    assert not s.save({"bot.owner_id": "kaputt"}, draft=True)["ok"]   # Feldprüfung gilt trotzdem


def test_bot_start_verweigert_wenn_laeuft(tmp_path):
    import time
    s = store(tmp_path)
    s.save({"bot.owner_id": OWNER})
    (tmp_path / "config.status.json").write_text(json.dumps({"ts": time.time()}))
    assert not s.start_bot()["ok"]



def test_platzhalter_ids_aus_alter_vorlage_gelten_als_leer(tmp_path):
    (tmp_path / "config.yaml").write_text("bot:\n  owner_id: 000000000000000000\n  partner_bot_ids: [000000000000000000]\n", encoding="utf-8")
    s = Store(tmp_path / "config.yaml")
    st = s.state()
    assert st["values"]["bot.owner_id"] is None and st["values"]["bot.partner_bot_ids"] == []
    assert s.save({"bot.owner_id": OWNER, "bot.partner_bot_ids": st["values"]["bot.partner_bot_ids"]}, draft=True)["ok"]


def test_voice_melder_paare_speichern_und_anzeigen(tmp_path):
    import yaml
    s = store(tmp_path)
    r = s.save({"bot.owner_id": OWNER, "voice_notifier.enabled": True,
                "voice_notifier.watch": "111111111111111111 = 222222222222222222\n333333333333333333 → 444444444444444444"})
    assert r["ok"], r
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["voice_notifier"]["watch"] == {111111111111111111: 222222222222222222, 333333333333333333: 444444444444444444}
    assert s.state()["values"]["voice_notifier.watch"] == ["111111111111111111 = 222222222222222222", "333333333333333333 = 444444444444444444"]
    bad = s.save({"voice_notifier.watch": "123 = abc"})
    assert not bad["ok"] and "voice_notifier.watch" in bad["field_errors"]
    tpl = s.save({"voice_notifier.template": "{oops}"})
    assert not tpl["ok"] and "Vorlage" in tpl["errors"][0]
