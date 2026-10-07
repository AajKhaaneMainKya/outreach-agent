#!/bin/zsh
cd -- "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m gtm.server
else
  exec python3 -m gtm.server
fi
