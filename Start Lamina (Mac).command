#!/bin/sh
# Double-click this to run Lamina on this Mac. It fetches what it needs the first time (a few minutes) and a new
# version whenever one is released, then opens http://localhost:8000 in your browser. Closing this Terminal window
# stops Lamina. Nothing leaves your machine.
#
# If macOS says the file cannot be opened: right-click it and choose Open, or run  chmod +x "Start Lamina (Mac).command"
cd "$(dirname "$0")" || exit 1

if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"                 # a uv installed earlier but never added to the PATH
fi
if ! command -v uv >/dev/null 2>&1; then
  echo
  echo 'Lamina needs "uv" — a small tool from the makers of Ruff that fetches Python'
  echo 'and the libraries for you. It installs into your own home folder.'
  echo
  printf 'Install uv now? [y/N] '
  read -r yn
  case "$yn" in
    [Yy]*) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    *) echo 'Nothing was installed. You can install uv yourself from https://docs.astral.sh/uv/'; exit 1 ;;
  esac
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo 'uv could not be installed — see https://docs.astral.sh/uv/'; exit 1; }
fi

echo 'Getting Lamina ready — the first time downloads Python and the libraries, so give it a few minutes.'
echo 'After that it only downloads something when a new version of Lamina is out.'
uv tool install --upgrade lamina3d || echo 'Could not check for a new version — starting the one already on this Mac.'

echo
echo 'Lamina is starting at http://localhost:8000 — your browser will open in a moment.'
echo 'Leave this window open while you use it; close it (or press Control-C) to stop Lamina.'
echo
uv tool run lamina3d || {
  echo
  echo 'Lamina has stopped. If that was not you and the lines above show an error, copy them into a bug report:'
  echo 'https://github.com/marcelfarres/lamina/issues/new?template=bug_report.yml'
}
