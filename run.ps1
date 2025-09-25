python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bot.tools.migrate_unified
python -m bot.main
