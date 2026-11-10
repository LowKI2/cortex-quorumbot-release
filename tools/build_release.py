"""Release-Pakete für Cortex QuorumBot bauen.

    python tools/build_release.py v0.5.0 [--out dist]

Erzeugt aus dem Git-Tag (oder dem aktuellen Ordner, wenn kein Git da ist):
  CortexQuorumBot.zip                    Nutzerpaket – fester Name, damit der Link
                                         .../releases/latest/download/CortexQuorumBot.zip immer stimmt
  cortex-quorumbot-<tag>-quellcode.zip   kompletter Quellcode inkl. Tests
  CortexQuorumBot-Windows.zip            nur wenn dist/exe/CortexQuorumBot.exe existiert (tools/build_exe.py):
                                         Windows-Programm ohne Python, fester Name für den Dauer-Link

Das Nutzerpaket enthält keine Tests und Entwicklerdateien, dafür ANLEITUNG.html
(aus INSTALLATION.md, im BZi-Studio-Stil) und LIESMICH.txt.
Benötigt nur für den Bau: pip install markdown pillow
"""
from __future__ import annotations

import argparse
import html
import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_PACKAGE = "CortexQuorumBot.zip"
EXE_PACKAGE = "CortexQuorumBot-Windows.zip"
EXE_FILE = ROOT / "dist" / "exe" / "CortexQuorumBot.exe"
EXE_EXTRA = ("config.example.yaml", ".env.example", "LICENSE", "README.md", "DATENSCHUTZ.md")
EXE_BATS = {
    "konfigurator.bat": "CortexQuorumBot.exe konfigurator config.yaml %* & if errorlevel 75 (exit) else (pause)",
    "start.bat": "if not exist config.yaml echo config.yaml fehlt - erst konfigurator.bat starten. & pause & exit /b 1\r\n"
                 "CortexQuorumBot.exe bot config.yaml & if errorlevel 75 (exit) else (pause)",
    "pruefen.bat": "chcp 65001 >nul\r\nCortexQuorumBot.exe pruefen config.yaml & pause",
}
BAT_HEAD = ("@echo off\r\nrem Programmaufruf in EINER Zeile am Ende - ein Update ersetzt diese Datei evtl. im laufenden Betrieb.\r\n"
            "cd /d %~dp0\r\n")
EXCLUDE_PREFIXES = ("tests/", "tools/", ".github/")
EXCLUDE_FILES = {".gitignore", ".gitattributes"}

LIESMICH = """Cortex QuorumBot {version}
=========================

Discord-Bot für eine Runde aus Menschen und KI-Bots – mit Leitplanken.

So geht's los
1. Python 3.11 oder neuer installieren (python.org) – beim Setup "Add python.exe to PATH" anhaken.
2. Diesen Ordner an einen festen Platz legen (nicht in einen Cloud-Ordner).
3. konfigurator.bat doppelklicken – der Einrichtungsassistent führt durch alles.
4. Wenn der Test "Startklar" meldet: start.bat doppelklicken.

Ausführliche Anleitung mit Funktionstest: ANLEITUNG.html (Doppelklick öffnet sie im Browser).
Datenschutz (was wohin fließt + Vorlage für deinen Discord-Server): DATENSCHUTZ.html

Wichtig
- Discord-Token und API-Key gehören nur in die Datei .env in diesem Ordner. Niemals weitergeben.
- Der Bot liest im freigegebenen Kanal mit und schickt die letzten Nachrichten an das gewählte KI-Modell.

Updates: Konfigurator → Bereich "Updates" (Einstellungen bleiben erhalten).
Neueste Version: https://github.com/LowKI2/cortex-quorumbot-release/releases/latest
Unabhängiges Projekt von BZi Studio, keine Verbindung zu Anthropic oder Discord. MIT-Lizenz, ohne Gewähr.
"""

LIESMICH_EXE = """Cortex QuorumBot {version} – Windows-Programm
=============================================

Discord-Bot für eine Runde aus Menschen und KI-Bots – mit Leitplanken. Diese Variante braucht kein Python.

So geht's los
1. Diesen Ordner an einen festen Platz legen (nicht in einen Cloud-Ordner, nicht in "Programme").
2. CortexQuorumBot.exe (oder konfigurator.bat) doppelklicken – der Einrichtungsassistent führt durch alles.
3. Wenn der Test "Startklar" meldet: start.bat doppelklicken.

Windows-Warnung beim ersten Start
Das Programm ist nicht digital signiert. Windows SmartScreen zeigt deshalb "Der Computer wurde durch
Windows geschützt" -> "Weitere Informationen" -> "Trotzdem ausführen". Manche Virenscanner melden
Programme, die mit PyInstaller gebaut wurden, fälschlich als verdächtig. Wer dem nicht trauen will,
nimmt die Python-Variante (CortexQuorumBot.zip) – gleicher Inhalt, offener Quellcode.

Für die Abo-Variante muss Claude Code installiert und angemeldet sein (siehe ANLEITUNG.html).
Datenschutz (was wohin fließt + Vorlage für deinen Discord-Server): DATENSCHUTZ.html
Updates: Konfigurator -> Bereich "Updates" (Einstellungen bleiben erhalten).

Wichtig
- Discord-Token und API-Key gehören nur in die Datei .env in diesem Ordner. Niemals weitergeben.
- Der Bot liest im freigegebenen Kanal mit und schickt die letzten Nachrichten an das gewählte KI-Modell.

Neueste Version: https://github.com/LowKI2/cortex-quorumbot-release/releases/latest
Unabhängiges Projekt von BZi Studio, keine Verbindung zu Anthropic oder Discord. MIT-Lizenz, ohne Gewähr.
"""

HTML = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cortex QuorumBot · {doc}</title>
<style>
:root{{--font-sans:"Inter","Segoe UI",system-ui,-apple-system,sans-serif;--font-mono:"JetBrains Mono","Cascadia Mono","Consolas",monospace;
  --bg-0:#070b12;--bg-1:#0c121d;--bg-2:#111a28;--bg-3:#162233;--line:rgba(255,255,255,.07);--line-strong:rgba(255,255,255,.14);
  --text-0:#eef4ff;--text-1:#9fb1cc;--text-2:#62748f;--acc:#2fd6e8;--acc-2:#4f8cff;--acc-rgb:47,214,232;--warn:#fbbf24;--grid:rgba(255,255,255,.025)}}
@media (prefers-color-scheme: light){{:root{{--bg-0:#e9e4d8;--bg-1:#f2ede2;--bg-2:#faf6ec;--bg-3:#ece5d6;--line:rgba(60,48,28,.1);
  --line-strong:rgba(60,48,28,.2);--text-0:#2c2418;--text-1:#6a5e49;--text-2:#9a8d76;--acc:#0d7d8c;--acc-2:#2f5fd0;--acc-rgb:13,125,140;--warn:#a66a00;--grid:rgba(60,48,28,.028)}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg-0);color:var(--text-0);font:15px/1.6 var(--font-sans);
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:32px 32px}}
header{{border-bottom:1px solid var(--line);background:var(--bg-1)}}
.top{{max-width:920px;margin:auto;padding:18px 16px;display:flex;gap:12px;align-items:center}}
.logo{{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,var(--acc),var(--acc-2));
  box-shadow:0 0 22px -4px rgba(var(--acc-rgb),.7);color:var(--bg-0);flex:none}}
.logo svg{{width:20px;height:20px;stroke:currentColor;stroke-width:2.2;fill:none;stroke-linecap:round}}
.top b{{display:block;font-size:17px}}
.label{{font:600 10px/1.2 var(--font-mono);letter-spacing:.18em;text-transform:uppercase;color:var(--text-2)}}
main{{max-width:920px;margin:auto;padding:24px 16px 80px}}
.card{{position:relative;background:var(--bg-2);border:1px solid var(--line);border-radius:12px;padding:28px}}
.card::before,.card::after{{content:"";position:absolute;width:14px;height:14px;border:solid rgba(var(--acc-rgb),.6)}}
.card::before{{top:-1px;left:-1px;border-width:1px 0 0 1px;border-top-left-radius:12px}}
.card::after{{bottom:-1px;right:-1px;border-width:0 1px 1px 0;border-bottom-right-radius:12px}}
h1{{font-size:26px;margin:0 0 12px}} h2{{font-size:19px;margin:34px 0 10px;padding-top:12px;border-top:1px solid var(--line)}}
h3{{font-size:16px;margin:24px 0 8px;color:var(--acc)}}
p,li{{color:var(--text-1)}} b,strong{{color:var(--text-0)}}
a{{color:var(--acc)}}
p,li,a,code,td{{overflow-wrap:anywhere}}
code{{font-family:var(--font-mono);font-size:13px;background:var(--bg-3);padding:1px 6px;border-radius:5px;color:var(--text-0)}}
pre{{background:var(--bg-1);border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto}} pre code{{background:none;padding:0}}
blockquote{{margin:16px 0;padding:10px 14px;border-left:3px solid var(--acc);background:rgba(var(--acc-rgb),.07);border-radius:0 8px 8px 0}}
blockquote p{{margin:0;color:var(--text-0)}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px;display:block;overflow-x:auto}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font:600 11px var(--font-mono);letter-spacing:.1em;text-transform:uppercase;color:var(--text-2)}}
hr{{display:none}}
.dl{{display:inline-flex;gap:8px;align-items:center;margin-top:14px;padding:9px 16px;border-radius:8px;font-weight:600;text-decoration:none;
  background:linear-gradient(135deg,var(--acc),var(--acc-2));color:var(--bg-0);box-shadow:0 0 22px -6px rgba(var(--acc-rgb),.7)}}
footer{{max-width:920px;margin:auto;padding:0 16px 40px;color:var(--text-2);font-size:12px}}
@media (max-width:600px){{.card{{padding:18px}}}}
</style>
</head>
<body>
<header><div class="top">
  <div class="logo" aria-hidden="true" style="background:#000;overflow:hidden"><img src="{logo}" alt="" style="width:100%;height:100%;object-fit:cover"></div>
  <div><b>Cortex QuorumBot</b><span class="label">{doc} · {version}</span></div>
</div></header>
<main><article class="card">
{body}
<p><a class="dl" href="https://github.com/LowKI2/cortex-quorumbot-release/releases/latest">Neueste Version prüfen</a></p>
</article></main>
<footer>BZi Studio · Unabhängiges Projekt, keine Verbindung zu Anthropic oder Discord · MIT-Lizenz, ohne Gewähr</footer>
</body>
</html>
"""


def source_files(tag: str | None) -> dict[str, bytes]:
    """Dateien aus dem Git-Tag (bevorzugt) oder aus dem Arbeitsordner."""
    if tag and (ROOT / ".git").exists():
        data = subprocess.run(["git", "archive", "--format=zip", tag], cwd=ROOT, check=True,
                              capture_output=True).stdout
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    out = {}
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and not rel.startswith((".git/", ".venv/", "dist/")) and "__pycache__" not in rel \
                and not rel.endswith((".pyc",)) and rel not in {".env", "config.yaml"} and not re.search(r"\.(overrides|status|budget)\.json$", rel):
            out[rel] = p.read_bytes()
    return out


def render_guide(md_text: str, version: str, doc: str = "Anleitung") -> str:
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = body.replace("<li>[ ] ", "<li>☐ ").replace("<li>[x] ", "<li>☑ ")
    body = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" target="_blank" rel="noopener">', body)
    import base64
    from PIL import Image
    buf = io.BytesIO()
    Image.open(ROOT / "assets" / "icon-256.png").resize((96, 96)).save(buf, "PNG", optimize=True)
    logo = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return HTML.format(version=html.escape(version), body=body, doc=html.escape(doc), logo=logo)


def write_zip(path: Path, files: dict[str, bytes], prefix: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name])


def build(tag: str, out: Path) -> list[Path]:
    files = source_files(tag)
    m = re.search(rb'VERSION\s*=\s*"([^"]+)"', files.get("version.py", b""))
    if not m or m.group(1).decode() != tag.lstrip("v"):
        sys.exit(f"Abbruch: version.py ({m.group(1).decode() if m else '?'}) passt nicht zum Tag {tag}.")
    for leaked in (".env", "config.yaml"):
        if leaked in files:
            sys.exit(f"Abbruch: {leaked} gehört nicht ins Release.")
    out.mkdir(parents=True, exist_ok=True)

    user = {n: b for n, b in files.items()
            if not n.startswith(EXCLUDE_PREFIXES) and n not in EXCLUDE_FILES}
    user["ANLEITUNG.html"] = render_guide(files["INSTALLATION.md"].decode("utf-8"), tag).encode("utf-8")
    user["LIESMICH.txt"] = LIESMICH.format(version=tag).replace("\n", "\r\n").encode("utf-8-sig")
    if "DATENSCHUTZ.md" in files:
        user["DATENSCHUTZ.html"] = render_guide(files["DATENSCHUTZ.md"].decode("utf-8"), tag, "Datenschutz").encode("utf-8")

    p_user = out / USER_PACKAGE
    p_src = out / f"cortex-quorumbot-{tag}-quellcode.zip"
    write_zip(p_user, user, f"CortexQuorumBot-{tag}")
    write_zip(p_src, files, f"cortex-quorumbot-{tag}")
    result = [p_user, p_src]
    if EXE_FILE.exists():
        win = {n: files[n] for n in EXE_EXTRA if n in files}
        win["CortexQuorumBot.exe"] = EXE_FILE.read_bytes()
        win["ANLEITUNG.html"] = user["ANLEITUNG.html"]
        if "DATENSCHUTZ.html" in user:
            win["DATENSCHUTZ.html"] = user["DATENSCHUTZ.html"]
        win["LIESMICH.txt"] = LIESMICH_EXE.format(version=tag).replace("\n", "\r\n").encode("utf-8-sig")
        for name, body in EXE_BATS.items():
            win[name] = (BAT_HEAD + body + "\r\n").encode("ascii")
        p_win = out / EXE_PACKAGE
        write_zip(p_win, win, f"CortexQuorumBot-{tag}")
        result.append(p_win)
    else:
        print("Hinweis: keine exe gefunden (tools/build_exe.py) – nur Python-Pakete gebaut.")
    return result


def main():
    ap = argparse.ArgumentParser(description="Release-Pakete bauen")
    ap.add_argument("tag", help="z. B. v0.3.0")
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    for p in build(a.tag, ROOT / a.out):
        print(f"{p.name}: {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
