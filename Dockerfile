# Lamina as a service:  docker run -p 8000:8000 -v lamina-jobs:/app/working-files ghcr.io/marcelfarres/lamina
# Every dependency ships a manylinux wheel, so there is nothing to compile and no apt package to install.
# The Python the starters ask for (027), and the uv that goes with it: bump both together.
FROM ghcr.io/astral-sh/uv:0.13.9-python3.14-trixie-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project   # the libraries only; the app runs from /app

COPY LICENSE README.md CHANGELOG.md ./
COPY core core
COPY web web
COPY examples examples

# jobs live under working-files/ (mount a volume there to keep them), and the library under /library when
# LAMINA_LIBRARY=/library is set: both owned by the app user, so a named volume there is writable as it is. User 1000:
# the server's message for a host folder it cannot write (web/app.py, library_problem) names this id, as the README does
RUN useradd -m -u 1000 lamina && install -d -o lamina /app/working-files /library
USER lamina

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/modes')"
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
