# Lamina as a service:  docker run -p 8000:8000 -v lamina-jobs:/app/working-files ghcr.io/marcelfarres/lamina
# Every dependency ships a manylinux wheel, so there is nothing to compile and no apt package to install.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY LICENSE README.md ./
COPY core core
COPY web web
COPY examples examples

# jobs live under working-files/ (mount a volume there to keep them); owned by the app user so the volume is writable
RUN useradd -m lamina && install -d -o lamina /app/working-files
USER lamina

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/modes')"
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
