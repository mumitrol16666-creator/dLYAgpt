#!/usr/bin/env bash
set -e
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.tools.migrate_unified
python -m bot.main
