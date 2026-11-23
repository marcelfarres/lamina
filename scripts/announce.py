"""Post a release's Discord message, with its files, to the channel of a webhook.

    python scripts/announce.py .github/announce/0.4.0.md            what would be sent (the preview)
    DISCORD_WEBHOOK=… python scripts/announce.py .github/announce/0.4.0.md --send

The message file is the text as Discord shows it, under a front block that names the files to attach (repo paths):

    ---
    files: docs/media/bands_build.mp4, web/static/news/0.4.0-mask.jpg
    ---
    **Lamina 0.4.0 is out!** …

.github/workflows/announce.yml runs it when Marcel presses Run workflow, after he read the message on the launch
board; it never runs on its own. Mentions are switched off, so a stray @everyone in the text pings no one.
Standard library only: the workflow needs no install.
"""
import json
import pathlib
import sys
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIMIT_TEXT, LIMIT_FILE = 2000, 20 * 1024 * 1024    # Discord: characters in a message, bytes in a free upload


def read(path):
    text = pathlib.Path(path).read_text(encoding="utf-8").replace("\r", "")
    _, front, body = text.split("---\n", 2)
    files = [f.strip() for f in front.split("files:", 1)[1].split(",") if f.strip()] if "files:" in front else []
    body = body.strip()
    if len(body) > LIMIT_TEXT:
        raise SystemExit(f"{len(body)} characters: Discord takes {LIMIT_TEXT}")
    for f in files:
        if not (ROOT / f).is_file():
            raise SystemExit(f"no such file: {f}")
        if (ROOT / f).stat().st_size > LIMIT_FILE:
            raise SystemExit(f"{f}: over Discord's 20 MB")
    return body, files


def request(webhook, body, files):
    """The multipart request Discord's webhook takes: payload_json, then files[0], files[1], …"""
    edge = uuid.uuid4().hex
    payload = json.dumps({"content": body, "allowed_mentions": {"parse": []}})
    parts = [f'--{edge}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             f"Content-Type: application/json\r\n\r\n{payload}\r\n".encode()]
    for i, f in enumerate(files):
        p = ROOT / f
        parts.append(f'--{edge}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{p.name}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + p.read_bytes() + b"\r\n")
    parts.append(f"--{edge}--\r\n".encode())
    return urllib.request.Request(webhook + ("&" if "?" in webhook else "?") + "wait=true", data=b"".join(parts),  # noqa: S310 — main() takes https only
                                  method="POST", headers={"Content-Type": f"multipart/form-data; boundary={edge}",
                                                          "User-Agent": "lamina-announce"})


def main(path, send=False):
    body, files = read(path)
    print(body, "\n\nfiles:", ", ".join(files) or "none", f"\n{len(body)} characters")
    if not send:
        return
    import os
    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    if not webhook.startswith("https://"):
        raise SystemExit("DISCORD_WEBHOOK is not set (the repo secret, or the environment)")
    with urllib.request.urlopen(request(webhook, body, files), timeout=60) as r:  # noqa: S310 — https checked above
        print("posted:", json.load(r).get("id"))


if __name__ == "__main__":
    main(sys.argv[1], "--send" in sys.argv[2:])
