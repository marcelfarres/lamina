"""Assemble the static site in _site/: the landing page (docs/) plus app/ — the UI and everything its Python needs to
run in the browser (core + web zipped, the bundled models, the pure-Python packages pinned to uv.lock). Publish it
anywhere that serves files: GitHub Pages, a Hugging Face static Space, `python -m http.server`."""
import json, os, pathlib, re, shutil, subprocess, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
site = ROOT / "_site"; shutil.rmtree(site, ignore_errors=True)
shutil.copytree(ROOT / "docs", site)
app = site / "app"
shutil.copytree(ROOT / "web" / "static", app / "static")
shutil.move(app / "static" / "index.html", app / "index.html")        # app/index.html + app/static/… = the server's layout
py = app / "static" / "py"; py.mkdir()

with zipfile.ZipFile(py / "core.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in [*ROOT.glob("core/**/*.py"), *ROOT.glob("web/*.py")]:
        z.write(f, f.relative_to(ROOT))

ex = py / "examples"; ex.mkdir()
for f in ROOT.glob("examples/*.stl"):
    shutil.copy(f, ex)
(ex / "index.json").write_text(json.dumps(sorted(f.stem for f in ex.glob("*.stl"))))
shutil.copy(ROOT / "examples" / "presets.json", ex)          # what each example opens with

# the packages Pyodide does not ship, at the versions the tests ran; rectpack has no wheel on PyPI, so build one
lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
ver = lambda n: re.search(rf'^name = "{n}"\nversion = "([^"]+)"', lock, re.M).group(1)
subprocess.run(["uv", "run", "--no-project", "--with", "pip", "python", "-m", "pip", "wheel", f"rectpack=={ver('rectpack')}", "--no-deps", "-q", "-w", str(py)], check=True)
reqs = [f"{n}=={ver(n)}" for n in ("trimesh", "ezdxf", "reportlab", "python-multipart")] + [next(py.glob("rectpack-*.whl")).name]
(py / "requirements.txt").write_text("\n".join(reqs) + "\n")

# Counting visits to the published landing page only — never in the app people self-host, and never in the app at
# all unless its reader opts in (web/static/index.html asks first and defaults to off).
#
# GoatCounter sets no cookies, keeps no IP address and builds no cross-site profile, so under GDPR/ePrivacy it
# needs no consent banner: there is nothing stored on the reader's device to ask permission for. That matters here
# beyond the law — a consent banner on a page whose pitch is "your models never leave your machine" would be its
# own contradiction. The footer discloses what is counted anyway, because transparency is owed either way.
#
# Set COUNT_URL to the endpoint (https://<code>.goatcounter.com/count). Unset = no counting anywhere.
if count := os.environ.get("COUNT_URL"):
    # Worth pinning to a versioned script with Subresource Integrity once set up — GoatCounter publishes
    # count.vN.js with a published hash for exactly that. Do not guess the hash: a wrong one blocks the script.
    tag = f'<script data-goatcounter="{count}" async src="//gc.zgo.at/count.js"></script>'
    (site / "index.html").write_text(
        (site / "index.html").read_text(encoding="utf-8").replace("</head>", tag + "</head>", 1), encoding="utf-8")
    # The app gets the endpoint but not the script: browser.js loads it only after an explicit opt-in.
    (app / "index.html").write_text(
        (app / "index.html").read_text(encoding="utf-8")
        .replace("</head>", f'<meta name="count-url" content="{count}"></head>', 1), encoding="utf-8")

(site / "README.md").write_text("---\ntitle: Lamina\nemoji: 🪚\nsdk: static\napp_file: index.html\nlicense: agpl-3.0\n"
                                "short_description: Turn a 3D model into flat parts you can cut\n---\n", encoding="utf-8")   # Hugging Face static Space
print(f"_site: {sum(f.stat().st_size for f in site.rglob('*') if f.is_file()) / 1e6:.1f} MB, app/static/py: {reqs}")
