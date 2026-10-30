@echo off
rem Wichtig: Der Programmaufruf muss in EINER Zeile am Ende stehen - ein Update ersetzt diese Datei evtl. im laufenden Betrieb.
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
python konfigurator.py config.yaml %* & if errorlevel 75 (exit) else (pause)
