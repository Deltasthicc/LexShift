#!/usr/bin/env sh
# One command for everyone (macOS, Linux, Git Bash): set the data up (first time only), clear any stale stub override, start the interface with every module real.
cd "$(dirname "$0")" || exit 1
unset LEXSHIFT_STUBS
PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/bin/python
[ -x "$PY" ] || { python -m venv .venv && PY=.venv/bin/python && "$PY" -m pip install -r requirements.txt && "$PY" -m nltk.downloader stopwords; }
export PYTHONIOENCODING=utf-8
"$PY" -m app.setup || exit 1
"$PY" -m app.server --real --open
