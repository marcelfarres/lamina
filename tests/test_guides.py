"""The site's guides (docs/<slug>/index.html) as they are written: no build, no browser. What the built site serves is
tests/test_e2e_site.py's; that the pictures show the running app is scripts/media/guides.py's, which makes them."""
import pathlib
import re

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = {p.parent.name: p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*/index.html"))}
block = lambda html, label: re.search(rf'<nav aria-label="{label}">(.*?)</nav>', html, re.S).group(1).replace(' aria-current="page"', "")


def test_every_guide_has_the_same_way_round():
    """One header and one footer: the same links in the same order on every page, the page you are on marked. The
    comparison with Slicer for Fusion 360 is no guide (Marcel, 2026-11-25): the footer links to it, the header's guide
    list does not."""
    for label in ("Guides", "All guides"):
        navs = {slug: block(html, label) for slug, html in PAGES.items()}
        assert len(set(navs.values())) == 1, {s for s, n in navs.items() if n != navs["stacked-slices"]}
    header = block(PAGES["stacked-slices"], "Guides")
    assert "fusion" not in header
    listed = re.findall(r'href="\.\./([^/"]+)/"', header)
    assert sorted(listed) == sorted(set(PAGES) - {"slicer-for-fusion-360-alternative"}), listed
    for slug in listed:                                         # the page it is on, said to a screen reader too
        assert f'href="../{slug}/" aria-current="page"' in PAGES[slug], slug


def test_a_guide_shows_one_model():
    """Every link of a guide that opens the app on an example names the same one, and every picture made for the
    guides is that guide's own: a guide that opens the horse shows the horse in every step."""
    for slug, html in PAGES.items():
        examples = set(re.findall(r'app/index\.html#\w+/(\w+)"', html))
        assert len(examples) <= 1, (slug, examples)
        for other in re.findall(r'media/guides/([a-z0-9-]+?)-\w+\.jpg', html):
            assert other == slug, f"{slug} shows a picture of the {other} guide"


def test_every_guide_picture_is_used_and_sized():
    """A picture made for the guides is in a page (no leftover from a step that went), and every picture of a page has
    the width and height of its file, so the text under it does not jump when it loads."""
    used = set()
    for slug, html in PAGES.items():
        for tag in re.findall(r"<img [^>]*>", html):
            src = re.search(r'src="([^"]+)"', tag).group(1)
            if "favicon" in src:
                continue
            f = (DOCS / slug / src).resolve()
            if src.startswith("../app/static/"):               # the built site serves web/ as app/
                f = ROOT / "web" / src[len("../app/"):]
            assert f.is_file(), (slug, src)
            used.add(f)
            w, h = Image.open(f).size
            assert f'width="{w}" height="{h}"' in tag, (slug, src, w, h)
    landing = (DOCS / "index.html").read_text(encoding="utf-8")
    used |= {(DOCS / s).resolve() for s in re.findall(r'src="(media/guides/[^"]+)"', landing)}
    left = sorted(f.name for f in (DOCS / "media" / "guides").glob("*.jpg") if f.resolve() not in used)
    assert not left, left
