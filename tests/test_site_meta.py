"""Every page search engines read keeps to what Google's results and Bing's site scan expect: one title of at most 70
characters, one meta description of 50 to 160 (Google cuts a longer one, Bing's live test calls it an error) and one
h1. The landing page, every guide under docs/ and the app."""
import html
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "docs").glob("**/index.html")) + [ROOT / "web/static/index.html"]


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_page_fits_search_results(path):
    page = path.read_text(encoding="utf-8")
    titles = [html.unescape(t) for t in re.findall(r"<title>(.*?)</title>", page, re.S)]
    descriptions = [html.unescape(d) for d in re.findall(r'<meta name="description" content="([^"]*)"', page)]
    assert len(titles) == 1 and len(titles[0]) <= 70, titles
    assert len(descriptions) == 1 and 50 <= len(descriptions[0]) <= 160, [(len(d), d) for d in descriptions]
    assert len(re.findall(r"<h1\b", page)) == 1
