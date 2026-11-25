"""Labels and marks: the room an engraved text takes, where it fits on a part, and where every part's label goes
on its sheet — on the part, or beside it with a leader line."""
from __future__ import annotations
import functools
import math
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree
from .geometry import as_multi, min_rect_angle, robust



# A printed part with no room for its number carries it on a tag beside it (core/solid.py, print_tag): a chip one layer
# high with the number raised on it, joined to the part by a thin line, to read and snap off. A printed job is nested
# with room for the tag where it will go (core/nest.py).
TAG_FONT = 4.0      # mm, the least a tag's letters are: bold strokes 0.64 mm, wider than one line of a 0.4 mm nozzle
TAG_PAD = 1.0       # mm of chip round the letters
TAG_CLEAR = 1.5     # mm from a tag to every part but its own: its line is that long at least, and PETG does not fuse across it
PRINT_MARK = 5.0    # mm, a seam number on a printed panel: bold strokes 1.0 mm wide (0.75 at 4 mm), two lines of a 0.4 mm nozzle
TURNED = str.maketrans("69", "96")   # 0, 1 and 8 turned upside down are themselves, in the stroke font and in Arial Bold


def seam_text(j) -> str:
    """A seam number as engraved: a dot after it when, turned upside down along its edge, it reads as another number
    (6 and 9, 16 and 91, 68 and 89, 18 and 81), as Pepakura marks them. 69, 96, 88 and 8 read the same both ways, and
    60 turned reads 09, which no seam is: none of these gets a dot."""
    s = str(j); t = s[::-1].translate(TURNED)
    return s + "." if set(s) <= set("01689") and t != s and t[0] != "0" else s


def tag_room(text, font):
    """The room a printed tag takes with its clearance, (w, h) upright. The stroke font's label box is wider than the
    bold printed letters at the same height (X-20 at 4 mm: 18.4 against 11.2 mm), so it holds the tag's letters too."""
    f = max(font, TAG_FONT)
    return label_box(text, f)[0] + 2 * TAG_CLEAR, f + 2 * (TAG_PAD + TAG_CLEAR)


def label_box(text, font):
    """The room an engraved label takes at `font` mm (the height of a capital): (w, h) — the stroke font's own width
    with a millimetre either side, never under 6 mm, and 1.4 capitals, which holds the descenders. The sheet
    placement and the per-piece export size a label the same way through this."""
    from .font import width
    return max(6.0, width(text, font) + 2), font * 1.4


def mark_box(x, y, text, font, rot=0.0):
    """The room a small engraved mark (a seam or dowel number, at 0.6 of the font) takes, centred on (x, y) and turned
    `rot` degrees — the mark's own turn in its part's frame; a mark on a nested part is turned by the placement too."""
    # boxed once and kept, by the numbers' own bits (0.0 and -0.0 are two keys): a slice's marks are boxed again for
    # every new mark placed on it (core/modes/connectors.py), tens of thousands of boxes on a stacked model
    return _mark_box(float(x).hex(), float(y).hex(), text, float(font).hex(), float(rot).hex())


@functools.lru_cache(maxsize=4096)
def _mark_box(x, y, text, font, rot):
    from .font import width
    x, y, font, rot = map(float.fromhex, (x, y, font, rot))
    s = font * 0.6
    b = box(x - (width(text, s) + 0.6) / 2, y - s * 0.7, x + (width(text, s) + 0.6) / 2, y + s * 0.7)
    return shapely.affinity.rotate(b, rot, origin=(x, y)) if rot else b


def mark_rot(m):
    """A mark's own turn, 0 for the three-value marks."""
    return float(m[3]) if len(m) > 3 else 0.0


def mark_size(m, font):
    """A mark's own font size: a seam number shrunk to fit a short edge carries it as a fifth value; `font` else."""
    return float(m[4]) if len(m) > 4 else font


def label_rect(x, y, rot, w, h):
    """A w × h label's box, centred on (x, y) and turned `rot` degrees, as the sheet carries it."""
    return shapely.affinity.rotate(box(x - w / 2, y - h / 2, x + w / 2, y + h / 2), rot, origin=(x, y))


def fit_block(region, w, h, angles=(0, 90)):
    """Centre and turn of a w × h block lying wholly inside `region` (holes respected), or None. For each turn the
    region is laid flat along it and eroded by the block — the region overlapped with itself moved by each corner and
    each edge middle of the block, a quick stand-in for the exact erosion — and the roomiest spot of what is left
    (the centre of its largest inscribed circle) is checked exactly."""
    return _fit_block(as_multi(region), {}, w, h, angles)


def _fit_block(region, laid, w, h, angles):
    """fit_block on a MultiPolygon, its turns kept in `laid` ({angle: (turned region, its bounds)}) for the next size."""
    if region.is_empty:
        return None
    for ang in angles:
        if ang not in laid:
            R = shapely.affinity.rotate(region, -ang, origin=(0, 0)) if ang else region
            laid[ang] = R, R.bounds
        R, (x0, y0, x1, y1) = laid[ang]
        if x1 - x0 < w - 1e-6 or y1 - y0 < h - 1e-6:
            continue        # narrower or lower than the block this way: by the third overlap below it comes out empty
        E = R
        for dx, dy in ((w / 2, h / 2), (-w / 2, h / 2), (w / 2, -h / 2), (-w / 2, -h / 2), (w / 2, 0), (-w / 2, 0), (0, h / 2), (0, -h / 2)):
            E = robust(lambda a, b: a.intersection(b), E, shapely.affinity.translate(R, dx, dy))
            if E is None or E.is_empty:
                break
        if E is None:
            continue
        for piece in sorted(as_multi(E).geoms, key=lambda q: -q.area):
            disc = robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), piece)
            for cx, cy in ([disc.coords[0]] if disc is not None else []) + [piece.representative_point().coords[0]]:
                if R.covers(box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)):
                    x, y = shapely.affinity.rotate(Point(cx, cy), ang, origin=(0, 0)).coords[0] if ang else (cx, cy)
                    return (float(x), float(y), float(ang))
    return None


def fit_on_part(region, cover, w, h, marks=(), angles=(0, 90), room=0.0):
    """Where a w × h label fits whole on a part's material with `room` to spare all round — only inside `cover` when
    the part has one (a stacked layer: under the layer glued on top, which hides it) — clear of its holes and of the
    marks and arrows (boxes) already engraved on it, at the first of `angles` that holds it. None when it fits
    nowhere: a label crammed against the edge of a small part is better off beside it."""
    return _fitter(region, cover, marks, angles)(w, h, room)


def _fitter(region, cover, marks=(), angles=(0, 90)):
    """fit_on_part on one part for label after label, as fit(w, h, room): what may carry a label (the material inside
    the cover, clear of the marks) and its turns are worked out for the first and kept for the rest — place_labels
    tries up to six sizes on a part. Kept apart for the region as given and for the precision-snapped copy robust()
    tries when the geometry engine throws on it, and only once whole, so a size fails or retries as it did alone."""
    kept = {}
    def fit(r, w, h):
        k = r is region
        if k not in kept:
            on = as_multi(r if cover is None else r.intersection(cover))
            if marks:
                on = robust(lambda a, b: as_multi(a.difference(b)), on, unary_union([m.buffer(0.5) for m in marks]), default=on)
            kept[k] = on, {}
        return _fit_block(*kept[k], w, h, angles)
    return lambda w, h, room=0.0: robust(lambda r: fit(r, w + 2 * room, h + 2 * room), region, default=None)


def widest_spot(region):
    return robust(lambda r: _widest_spot(r), region, default=(0.0, 0.0, 0.0))


def _widest_spot(region):
    """The spot on a part with the most clearance all round — the centre of its largest inscribed circle: where a
    label that fits nowhere whole is still put, overrunning the outline, for the maker to trim rather than left off."""
    region = as_multi(region)
    if region.is_empty:
        return (0.0, 0.0, 0.0)
    discs = [d for d in (robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), g) for g in region.geoms) if d is not None]
    if not discs:
        return (0.0, 0.0, 0.0)
    best = max(discs, key=lambda c: c.length)
    return (float(best.coords[0][0]), float(best.coords[0][1]), 0.0)


def orient_arrows(region, longest=8.0, keep=()):
    return robust(lambda r: _orient_arrows(r, longest, keep), region, default=[])


def _orient_arrows(region, longest=8.0, keep=()):
    """Two arrows at a part's widest spot, on the LABEL layer: one up its frame's y, one shorter to the right along
    x, so every part of a model carries the same two directions and the engraved face is known to be the front. As
    (style, LineString) lines, shaft and head each, sized to the clearance there, clear of `keep` (the marks already
    engraved, as boxes); none on a part too small to hold a legible pair."""
    region = as_multi(region)
    if keep:
        region = robust(lambda a, b: as_multi(a.difference(b)), region, unary_union([k.buffer(0.6) for k in keep]), default=region)
    if region.is_empty:
        return []
    discs = [d for d in (robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), g) for g in region.geoms) if d is not None]
    if not discs:
        return []
    disc = max(discs, key=lambda c: c.length)
    (cx, cy), r = disc.coords[0], disc.length
    L = min(longest, 0.6 * r)                   # well inside the clearance: on a small part the arrows must not read as its edge
    if L < 3.0:
        return []
    out = []
    for dx, dy, length in ((0, 1, L), (1, 0, 0.65 * L)):
        tx, ty = cx + dx * length, cy + dy * length                      # the tip
        h = 0.3 * length; px, py = -dy, dx                                  # the head's half-width, across the shaft
        out.append(("orient", LineString([(cx, cy), (tx, ty)])))
        out.append(("orient", LineString([(tx - dx * h - px * h * 0.6, ty - dy * h - py * h * 0.6), (tx, ty), (tx - dx * h + px * h * 0.6, ty - dy * h + py * h * 0.6)])))
    return out


def label_angles(region):
    """The turns to try a label on a part at: upright, a quarter turn, and along the part's long side and across it
    when that side is not already square to the sheet."""
    long = -min_rect_angle(region) % 180
    if long > 90:
        long -= 180                                           # never upside down
    return (0, 90) if min(abs(long) % 90, 90 - abs(long) % 90) < 5 else (0, 90, round(long, 1), round(long + 90 if long < 0 else long - 90, 1))


def place_labels(sh, font, tag="", place="part"):
    """Every part's label. `place` = "part": on the part itself where the whole label fits on its material — on a
    stacked layer only where the layer glued on top hides it (`placed_cover`) — upright or turned along the part,
    clear of its marks and arrows, else beside the part in free space, with a leader line to its outline; "beside":
    always beside; "on": always on the part, but for a stacked layer with nothing over it (the top layer). Free space is space
    inside the sheet margin that no part (at the nesting gap), no earlier label and no leader line crosses, searched
    outward from the part's outline, above it first. A label with no room at the job's font is tried smaller, down to
    half, before it is put on the part's widest spot anyway, past its outline if it must, for the maker to trim in the
    laser software — counted (`crowded`) so the plan can say so. The one thing that never happens is a part coming
    out with no label at all."""
    text = lambda pc, short=False: f"{tag} {pc.label}" if tag and not short else pc.label   # `tag`: the model's short name first
    for g in sh.placed:
        shapely.prepare(g)
    tree = STRtree(sh.placed)
    taken = []
    for k, pc in enumerate(sh.pieces):
        keep = [mark_box(*m[:3], mark_size(m, font), mark_rot(m) + pc.place[3]) for m in pc.placed_marks] \
            + [ln.buffer(0.8) for s, ln in pc.placed_lines if s == "orient"]
        angles = label_angles(pc.placed) if place != "beside" else ()
        pc.crowded = False
        sizes = [font * sc for sc in (1.0, 0.8, 0.65)]
        # what may be engraved, best first: the full label at the font or a little under, then — a small part — the
        # part's name alone, without the model's short name, which the assembly key allows for
        forms = [(size, False) for size in sizes[:2]] + ([(size, True) for size in sizes[:2]] if tag else []) + [(sizes[2], False)] + ([(sizes[2], True)] if tag else [])
        spot = None
        if place != "beside":                                       # on the part
            fit = _fitter(pc.placed, pc.placed_cover, keep, angles)
            for size, short in forms:                             # down to two thirds of the font: a peg's name along the peg
                w, h = label_box(text(pc, short), size)
                spot = fit(w, h, room=0.0 if place == "on" else min(2.0, 0.3 * size))
                if spot:
                    break
        if spot is None and place == "on":                           # the widest spot of what may be engraved
            on = pc.placed if pc.placed_cover is None else as_multi(pc.placed.intersection(pc.placed_cover))
            if not on.is_empty:
                size, short = forms[-1]; spot = widest_spot(on)
        if spot:
            pc.label_pos, pc.leader, pc.label_size, pc.label_short = spot, None, size, short
            taken.append(label_rect(*spot, *label_box(text(pc, short), size)))
            continue
        # beside the part: the nearest free spot wins, a smaller or shorter label close by over a full one far away;
        # then free space anywhere on the sheet with a line across whatever lies between, rather than on a part the
        # label would overrun, where it reads as part of the cut
        boxes = [(size, short, *label_box(text(pc, short), size)) for size, short in forms]
        found = beside(k, pc, boxes, sh, tree, taken) or beside(k, pc, boxes[2:], sh, tree, taken, across=True)
        if found:
            (pc.label_pos, pc.leader, rect), (pc.label_size, pc.label_short) = found[:3], found[3]
            taken.append(rect)
        else:                                                       # nowhere at all: the widest spot, counted
            size, short = forms[-1]
            pc.label_pos, pc.leader, pc.label_size, pc.label_short, pc.crowded = widest_spot(pc.placed), None, size, short, True
            taken.append(label_rect(*pc.label_pos, *label_box(text(pc, short), size)))


def beside(k, pc, boxes, sh, tree, taken, across=False, toward=None):
    """A free spot for a label beside part k, at the first of `boxes` — (size, short, w, h), best first — that has one
    on the nearest ring: ((x, y, rot), leader, rect, (size, short)) or None. Candidates lie on rings round the part's nested
    outline at growing distances, above the part first, the label upright or on its side, its near edge on the ring;
    a candidate is free when its box lies inside the sheet margin and touches no part, no label placed before it,
    and the leader from it to the part's own outline crosses no other part — unless `across`, the last resort, which
    lets the leader run over other parts and searches the whole sheet. `toward`, a point: the candidates nearest it
    first instead (a printed seam number's tag beside its seam, core.solid)."""
    part = pc.placed.simplify(0.5)                          # the real outline: the nesting one may hold the room reserved for this label
    W, H, m = sh.W, sh.H, sh.margin
    x0, y0, x1, y1 = pc.placed.bounds; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for d in (0.8, 2.0, 3.5, 6.0, 10.0, 15.0, 22.0, 32.0, 45.0, 60.0, 85.0, 120.0) + ((170.0, 240.0, 340.0) if across else ()):
        pts = []
        for ring in (g.exterior for g in as_multi(part.buffer(d, join_style=1)).geoms):
            n = max(12, int(ring.length / max(4.0, min(h for *_, h in boxes) / 2)))
            pts += [ring.interpolate(i / n, normalized=True) for i in range(n)]
        pts.sort(key=lambda q: abs((math.degrees(math.atan2(q.y - cy, q.x - cx)) - 90 + 180) % 360 - 180))   # above first, below last
        if toward is not None:
            pts.sort(key=toward.distance)
        for size, short, w, h in boxes:
            for p in pts:
                q = nearest_points(pc.placed, p)[0]                                   # where the leader lands: the part's own outline
                nx, ny = p.x - q.x, p.y - q.y; L = math.hypot(nx, ny)
                if L < 1e-6:
                    continue
                nx, ny = nx / L, ny / L
                for rot in (0, 90):
                    bw, bh = (w, h) if rot == 0 else (h, w)
                    reach = abs(nx) * bw / 2 + abs(ny) * bh / 2                     # the box's near edge sits on the ring
                    lx, ly = p.x + nx * reach, p.y + ny * reach
                    rect = box(lx - bw / 2, ly - bh / 2, lx + bw / 2, ly + bh / 2)
                    rx0, ry0, rx1, ry1 = rect.bounds
                    mm = 0.0 if across else m                       # the last resort may use the margin band, as the title does
                    if rx0 < mm or ry0 < mm or rx1 > W - mm or ry1 > H - mm:
                        continue
                    if rect.intersects(pc.placed) or any(i != k and sh.placed[i].intersects(rect) for i in tree.query(rect)) or any(rect.intersects(t) for t in taken):
                        continue
                    line = LineString([(lx, ly), (q.x, q.y)])
                    if not across and any(i != k and sh.placed[i].intersects(line) for i in tree.query(line)):
                        continue
                    start = rect.exterior.intersection(line)                           # the leader leaves the label at its edge
                    start = start.geoms[0] if start.geom_type.startswith("Multi") else start
                    sx, sy = start.coords[0] if not start.is_empty else (lx, ly)
                    return (lx, ly, rot), ((sx, sy), (q.x, q.y)), rect, (size, short)
    return None
