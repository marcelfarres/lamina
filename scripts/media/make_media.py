"""Turn the raw captures in working-files/shots into the landing page's media (docs/media). Run by record.py.

The captures are 2x device pixels of a 1574 x 907 layout (capture.mjs). Stills are cropped to the interesting region
and scaled; UI renders go out as JPEG without chroma subsampling (thin coloured outlines smear at 4:2:0), joint
closeups as PNG (line art). Clips are encoded to mp4 (h264) with ffmpeg, each with a poster frame.
"""
import pathlib, shutil, subprocess
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "working-files" / "shots"        # raw frames: scratch, never committed
OUT = ROOT / "docs" / "media"
OUT.mkdir(parents=True, exist_ok=True)

S = 2                                 # device pixels per CSS px in the captures
VIEW = (400, 44, 1570, 528)          # the 3D viewport (CSS px)
FULL = (0, 0, 1574, 907)             # whole window
LEFT_MSG = (0, 44, 1570, 800)        # side panel plus the report
SHEETS = (400, 40, 1570, 545)        # the cut sheets area

STILLS = {                            # name: (crop, width)
    "hero": (FULL, 2400),
    "model": (FULL, 2200),
    "folded_rib": (VIEW, 1800),
    "sheets": (SHEETS, 2000),
    "checks": (LEFT_MSG, 2000),
    "export": (LEFT_MSG, 2000),
}
JOINT = (1400, 1050)                  # every joint closeup on the same 4:3 canvas, so the gallery does not jump
VIEW3D = (400, 44, 1570, 900)        # the viewport in "3D only" mode, which fills the height
VIEW43 = (414, 44, 1555, 900)        # the same, cropped to 4:3 for the technique cards (1141 x 856)
CLIPS = {                             # name: (crop, width, fps)
    "orbit": (VIEW3D, 1000, 24),
    "assembly": (VIEW3D, 1000, 20),
    "edit": (FULL, 1200, 16),
    "stacked": (VIEW43, 1100, 18),    # the technique cards: an orbit, then the parameters that matter
    "interlocked": (VIEW43, 1100, 18),
    "radial": (VIEW43, 1100, 18),
    "curve": (VIEW43, 1100, 18),
    "folded": (VIEW43, 1100, 18),
    "axes": (VIEW43, 1100, 18),       # radial with an axis per lobe: the dumbbell, its neck plane moved and tilted
    "lobes": (FULL, 1200, 16),        # the plane between two lobes selected, its sliders in frame
}


def px(crop):
    return tuple(v * S for v in crop)


def save(img, path, width):
    if img.width != width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    img = img.convert("RGB")
    if path.suffix == ".png":
        img.save(path, optimize=True)
    else:
        img.save(path, quality=90, optimize=True, subsampling=0)
    return path


for name, (crop, width) in STILLS.items():
    src = SRC / f"{name}.png"
    if not src.exists():
        print("missing", src.name); continue
    im = Image.open(src).crop(px(crop))
    p = save(im, OUT / f"{name}.jpg", width)
    print(f"{p.name:18s} {im.width}x{im.height} -> {p.stat().st_size // 1024} KB")

for src in sorted(SRC.glob("joint_*.png")):    # captured around the panel: fit it on the canvas, sheet colour around
    im = Image.open(src).convert("RGB")
    k = min(JOINT[0] / im.width, JOINT[1] / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    canvas = Image.new("RGB", JOINT, (0x1d, 0x1f, 0x24))
    canvas.paste(im, ((JOINT[0] - im.width) // 2, (JOINT[1] - im.height) // 2))
    p = save(canvas, OUT / f"{src.stem}.png", JOINT[0])
    print(f"{p.name:18s} -> {p.stat().st_size // 1024} KB")

ffmpeg = shutil.which("ffmpeg")
for name, (crop, width, fps) in CLIPS.items():
    frames = sorted((SRC / name).glob("*.png"))
    if not frames:
        print("missing clip", name); continue
    tmp = SRC / f"{name}_crop"; tmp.mkdir(exist_ok=True)
    for i, f in enumerate(frames):
        im = Image.open(f).crop(px(crop))
        w = width - width % 2
        im = im.resize((w, (round(im.height * w / im.width)) // 2 * 2), Image.LANCZOS)
        im.convert("RGB").save(tmp / f"{i:03d}.png")
    save(Image.open(tmp / "000.png"), OUT / f"{name}_poster.jpg", width)
    if not ffmpeg:
        print("no ffmpeg, skipping", name); continue
    out = OUT / f"{name}.mp4"                     # the page plays mp4 only (h264 plays everywhere)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "%03d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print(f"{out.name:18s} {len(frames)} frames -> {out.stat().st_size // 1024} KB")
    shutil.rmtree(tmp, ignore_errors=True)
print("total media:", sum(f.stat().st_size for f in OUT.iterdir()) // 1024, "KB")
