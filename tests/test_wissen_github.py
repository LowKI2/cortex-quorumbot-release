import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import knowledge  # noqa: E402
import wissen_github as gh  # noqa: E402
from config import Config  # noqa: E402


def zipball(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(f"Owner-repo-abc123/{n}", b)
    return buf.getvalue()


BALL = zipball({"README.md": b"# Lore\nDrache Feuer", "docs/kapitel.md": b"Kapitel eins", ".env": b"TOKEN=x",
                "secrets/passwort.txt": b"geheim", ".github/workflow.yml": b"x", "bild.png": b"\x89PNG",
                "src/code.py": b"print(1)", "gross.md": b"x" * 300_000})


class FakeGitHub:
    def __init__(self, private=False, sha="sha1", push=False):
        self.private, self.sha, self.push, self.calls = private, sha, push, []

    def __call__(self, url, headers, timeout=30, limit=None):
        self.calls.append((url, headers.get("Authorization")))
        if self.private and not headers.get("Authorization"):
            return 404, b"{}"
        if url.endswith("/repos/Owner/repo"):
            return 200, json.dumps({"full_name": "Owner/repo", "private": self.private, "default_branch": "main",
                                    "permissions": {"push": self.push}}).encode()
        if "/commits/" in url:
            return 200, self.sha.encode()
        if "/zipball/" in url:
            return 200, BALL
        return 404, b"{}"


def cfg(tmp_path, **gh_):
    return Config(str(tmp_path / "config.yaml"), data={"llm": {"provider": "claude_code"},
                  "knowledge": {"github": {"enabled": True, "repos": ["Owner/repo"], **gh_}}})


def test_repo_angaben():
    assert gh.parse("BBZGames/Bratratz_lore") == ("BBZGames", "Bratratz_lore", None)
    assert gh.parse("https://github.com/BBZGames/Bratratz_lore.git") == ("BBZGames", "Bratratz_lore", None)
    assert gh.parse("BBZGames/Bratratz_lore@dev") == ("BBZGames", "Bratratz_lore", "dev")
    for bad in ("nur-ein-name", "a/b/c", "https://gitlab.com/a/b", "../x/y"):
        with pytest.raises(gh.RepoError):
            gh.parse(bad)


def test_laden_nur_textdateien_und_nur_bei_aenderung(tmp_path):
    c, fake = cfg(tmp_path), FakeGitHub()
    r = gh.sync(c, {}, get=fake)[0]
    assert r["ok"] and r["updated"] and r["files"] == 2
    d = gh.repo_dir(c, "Owner/repo")
    assert (d / "README.md").exists() and (d / "docs" / "kapitel.md").exists()
    for bad in (".env", "secrets/passwort.txt", ".github/workflow.yml", "bild.png", "src/code.py", "gross.md"):
        assert not (d / bad).exists(), bad
    n = len(fake.calls)
    again = gh.sync(c, {}, get=fake)[0]
    assert not again["updated"] and not any("zipball" in u for u, _ in fake.calls[n:])
    fake.sha = "sha2"
    assert gh.sync(c, {}, get=fake)[0]["updated"]


def test_privat_braucht_token_und_token_bleibt_beim_bot(tmp_path):
    c, fake = cfg(tmp_path), FakeGitHub(private=True)
    r = gh.sync(c, {}, get=fake)[0]
    assert not r["ok"] and "GITHUB_TOKEN" in r["error"]
    assert gh.sync(c, {"GITHUB_TOKEN": "ghp_test"}, get=fake)[0]["ok"]
    assert all(a == "Bearer ghp_test" for u, a in fake.calls[-3:])


def test_wird_ueber_ordner_server_freigegeben(tmp_path):
    import os
    c = cfg(tmp_path)
    assert knowledge.read_roots(c) == []                       # noch nichts geladen
    gh.sync(c, {}, get=FakeGitHub())
    roots = knowledge.read_roots(c)
    assert roots == [str(gh.repo_dir(c, "Owner/repo"))] and knowledge.enabled(c)
    assert "mcp__ordner__search" in knowledge.allowed_tool_names(c)
    path = knowledge.write_mcp_config(c, {})
    try:
        args = json.loads(Path(path).read_text(encoding="utf-8"))["mcpServers"]["ordner"]["args"]
        assert args[args.index("--root") + 1] == roots[0]
    finally:
        os.unlink(path)
    from wissen_ordner import Folders
    assert "Drache" in Folders(roots).search("drache") and "GitHub-Repos" in " ".join(knowledge.prompt_rules(c))


def test_faelligkeit(tmp_path):
    c = cfg(tmp_path, refresh_minutes=60)
    assert gh.due(c)
    gh.sync(c, {}, get=FakeGitHub())
    assert not gh.due(c)


def test_pruefung_warnt_bei_schreibrechten(tmp_path):
    from checks import github_checks
    c = cfg(tmp_path)
    r = github_checks(c, {}, get=FakeGitHub(push=True))
    assert r[0].status == "warn" and "noch nicht geladen" in r[0].detail and r[1].name == "GitHub-Token"
    gh.sync(c, {}, get=FakeGitHub())
    assert github_checks(c, {}, get=FakeGitHub())[0].status == "ok"
    assert github_checks(c, {}, get=FakeGitHub(private=True))[0].status == "fail"
