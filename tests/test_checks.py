import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from checks import (FLAG_MESSAGE_CONTENT, api_key_conflict, check_packages, check_python,  # noqa: E402
                    discord_checks, ollama_check, run_all, summary)
from config import Config  # noqa: E402

BOT, OWNER, PARTNER, CH, APP = "900000000000000001", "123456789012345678", "223456789012345678", "323456789012345678", "900000000000000001"


def cfg(**over):
    data = {"bot": {"owner_id": int(OWNER), "partner_bot_ids": [int(PARTNER)], "name": "Nova"},
            "discord": {"allowed_channel_ids": [int(CH)], "application_id": int(APP)},
            "llm": {"provider": "anthropic", "model": "claude-sonnet-5-5"}}
    for k, v in over.items():
        sec, key = k.split("__")
        data.setdefault(sec, {})[key] = v
    return Config("x.yaml", data=data)


def fake(flags=FLAG_MESSAGE_CONTENT, guilds=True, token_ok=True, owner_bot=False, partner_bot=True, channel=200):
    def get(url, headers=None, timeout=10):
        if not token_ok:
            return 401, {"message": "401: Unauthorized"}
        if url.endswith("/users/@me"):
            return 200, {"id": BOT, "username": "Nova", "bot": True}
        if url.endswith("/applications/@me"):
            return 200, {"id": APP, "flags": flags}
        if url.endswith("/users/@me/guilds"):
            return 200, ([{"name": "Testserver"}] if guilds else [])
        if f"/channels/{CH}" in url:
            return channel, {"name": "runde"} if channel == 200 else {"message": "Missing Access"}
        if url.endswith(f"/users/{OWNER}"):
            return 200, {"username": "max", "bot": owner_bot}
        if url.endswith(f"/users/{PARTNER}"):
            return 200, {"username": "Kai", "bot": partner_bot}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "llama3.3"}]}
        return 404, None
    return get


def by(results):
    return {r.name: r for r in results}


def test_alles_gut():
    r = by(discord_checks(cfg(), "tok", get=fake()))
    assert all(x.status == "ok" for x in r.values()), r
    assert "Testserver" in r["Server"].detail


def test_token_falsch():
    r = discord_checks(cfg(), "tok", get=fake(token_ok=False))
    assert r[0].status == "fail" and "Reset Token" in r[0].fix


def test_token_fehlt():
    assert discord_checks(cfg(), "", get=fake())[0].status == "fail"


def test_intent_aus_server_fehlt_kanal_unsichtbar():
    r = by(discord_checks(cfg(), "tok", get=fake(flags=0, guilds=False, channel=403)))
    assert r["Message Content Intent"].status == "fail"
    assert r["Server"].status == "fail" and "Einladungslink" in r["Server"].fix
    assert r[f"Kanal {CH}"].status == "fail"


def test_ids_vertauscht():
    r = by(discord_checks(cfg(), "tok", get=fake(owner_bot=True, partner_bot=False)))
    assert r["Deine User-ID"].status == "fail" and r["Partner-Bot"].status == "fail"


def test_partner_ist_eigener_bot():
    c = cfg(bot__partner_bot_ids=[int(BOT)])
    def get(url, headers=None, timeout=10):
        if url.endswith(f"/users/{BOT}"):
            return 200, {"username": "Nova", "bot": True}
        return fake()(url, headers, timeout)
    r = by(discord_checks(c, "tok", get=get))
    assert r["Partner-Bot"].status == "fail" and "ANDEREN" in r["Partner-Bot"].fix


def test_application_id_passt_nicht():
    r = by(discord_checks(cfg(discord__application_id=111111111111111111), "tok", get=fake()))
    assert r["Application-ID"].status == "warn" and APP in r["Application-ID"].fix


def test_abo_warnt_bei_api_key():
    c = cfg(llm__provider="claude_code")
    assert api_key_conflict(c, {"ANTHROPIC_API_KEY": "x"}).status == "warn"
    assert api_key_conflict(c, {}) is None


def test_ollama():
    c = cfg(llm__provider="openai", llm__base_url="http://localhost:11434/v1", llm__model="qwen")
    assert ollama_check(c, get=fake()).status == "warn"
    c2 = cfg(llm__provider="openai", llm__base_url="http://x/v1", llm__model="llama3.3")
    assert ollama_check(c2, get=fake()).status == "ok"
    assert ollama_check(cfg(llm__provider="openai"), get=fake()).status == "fail"


def test_run_all_ohne_key_ueberspringt_anfrage():
    res = run_all(cfg(), {"DISCORD_TOKEN": "tok"}, with_request=True, get=fake())
    r = by(res)
    assert r["API-Key"].status == "fail" and r["Testanfrage"].status == "skip"
    assert "nicht startklar" in summary(res)


def test_basis():
    assert check_python().status == "ok" and check_packages().status == "ok"


def test_voice_melder_pruefung():
    from checks import notifier_checks
    V, T = "111111111111111111", "222222222222222222"

    def get(url, headers=None, timeout=10):
        if url.endswith(f"/channels/{V}"):
            return 200, {"name": "Lounge", "type": 2}
        if url.endswith(f"/channels/{T}"):
            return 200, {"name": "runde", "type": 0}
        return 404, None
    on = cfg(voice_notifier__enabled=True, voice_notifier__watch={int(V): int(T)})
    r = notifier_checks(on, "tok", get=get)
    assert r[0].status == "ok" and "Lounge" in r[0].detail and "runde" in r[0].detail
    swapped = cfg(voice_notifier__enabled=True, voice_notifier__watch={int(T): int(V)})
    assert notifier_checks(swapped, "tok", get=get)[0].status == "fail"          # Textkanal links = kein Sprachraum
    assert notifier_checks(cfg(voice_notifier__enabled=True), "tok", get=get)[0].status == "warn"
    assert notifier_checks(cfg(), "tok", get=get) == []
