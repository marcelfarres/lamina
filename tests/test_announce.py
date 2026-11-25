"""scripts/announce.py posts a release's Discord message: the text, mentions off, and every file it names."""
import email.parser
import http.server
import json
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import announce  # noqa: E402

PIC = "web/static/news/0.4.0-lamp.jpg"


def message(tmp_path, body, files=(PIC,)):
    p = tmp_path / "0.0.0.md"
    p.write_text(f"---\nfiles: {', '.join(files)}\n---\n{body}\n", encoding="utf-8")
    return p


def test_the_message_reaches_the_webhook_with_its_files(tmp_path):
    got = {}

    class Discord(http.server.BaseHTTPRequestHandler):            # stands in for the webhook: keeps what it gets
        def do_POST(self):
            got["path"] = self.path
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            msg = email.parser.BytesParser().parsebytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw)
            got["parts"] = {p.get_param("name", header="content-disposition"): p for p in msg.get_payload()}
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"id": "1"}')

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Discord)
    threading.Thread(target=server.handle_request, daemon=True).start()
    body = "**Lamina 0.0.0 is out!** @everyone should not be pinged."
    # the script refuses a webhook that is not https; the stand-in is plain http on this machine
    req = announce.request(f"http://127.0.0.1:{server.server_port}/api/webhooks/1/x", *announce.read(message(tmp_path, body)))
    with announce.urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — the stand-in on this machine
        assert json.load(r)["id"] == "1"
    server.server_close()

    assert got["path"].endswith("?wait=true")                     # Discord answers with the message it made
    payload = json.loads(got["parts"]["payload_json"].get_payload(decode=True))
    assert payload == {"content": body, "allowed_mentions": {"parse": []}}
    sent = got["parts"]["files[0]"]
    assert sent.get_filename() == "0.4.0-lamp.jpg"
    assert sent.get_payload(decode=True) == (ROOT / PIC).read_bytes()


def test_a_message_discord_would_refuse_is_stopped_before_sending(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK", raising=False)
    with pytest.raises(SystemExit, match="Discord takes 2000"):
        announce.read(message(tmp_path, "x" * 2001))
    with pytest.raises(SystemExit, match="no such file"):
        announce.read(message(tmp_path, "hello", files=("web/static/news/none.jpg",)))
    with pytest.raises(SystemExit, match="DISCORD_WEBHOOK is not set"):
        announce.main(message(tmp_path, "hello"), send=True)
    with pytest.raises(SystemExit, match="no message: write"):     # 0.4.1's run: a traceback at "No such file"
        announce.read(tmp_path / "9.9.9.md")


@pytest.mark.parametrize("path", sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / ".github/announce").glob("*.md")))
def test_every_release_message_would_post(path):
    """What the announce run checks, on every message in the repo (release_gate.py checks the release's own one)."""
    body, files = announce.read(ROOT / path)
    assert body.startswith(f"**Lamina {pathlib.Path(path).stem} is out!**") and files
