@echo off
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
if not exist config.yaml (
  echo config.yaml fehlt - kopiere config.example.yaml und fuelle sie aus.
  pause
  exit /b 1
)
python bot.py config.yaml
pause
