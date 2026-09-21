#!/bin/sh
# Run Lamina on this computer: double-click it (choose "Run in Terminal" if your file manager asks) or run it from a
# terminal with  ./"Start Lamina (Linux).sh" . It fetches what it needs the first time, then opens
# http://localhost:8000. Closing the window stops Lamina. Nothing leaves your machine.
#
# If it will not start: chmod +x "Start Lamina (Linux).sh"
cd "$(dirname "$0")" || exit 1

command -v uv >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo
  echo 'Lamina needs "uv" — a small tool from the makers of Ruff that fetches Python'
  echo 'and the libraries for you. It installs into your own home folder.'
  echo
  printf 'Install uv now? [y/N] '
  read -r yn
  case "$yn" in
    [Yy]*) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    *) echo 'Nothing was installed. Your distribution may package uv, or see https://docs.astral.sh/uv/'; exit 1 ;;
  esac
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo 'uv could not be installed — see https://docs.astral.sh/uv/'; exit 1; }
fi

echo 'Getting Lamina ready — the first time downloads Python and the libraries, so give it a few minutes.'
if ! uv sync; then
  echo
  echo 'That did not work. Copy the lines above into a bug report:'
  echo 'https://github.com/marcelfarres/lamina/issues/new?template=bug_report.yml'
  exit 1
fi

echo
echo 'Lamina is starting at http://localhost:8000 — your browser will open in a moment.'
echo 'Leave this window open while you use it; close it (or press Control-C) to stop Lamina.'
echo
(sleep 6; xdg-open http://localhost:8000 >/dev/null 2>&1) &
exec uv run uvicorn web.app:app --port 8000
