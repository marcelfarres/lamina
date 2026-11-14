"""Data carried through the pipeline."""
from __future__ import annotations
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from shapely.geometry import MultiPolygon

ABC = "ABCDEFGHJKLMNPQRSTUVWXYZ"        # no I or O: engraved at 4 mm they are a 1 and a 0


TAG_MAX = 4   # characters of the short name engraved before every label: room for the label itself on a small part


def short_name(name) -> str:
    """A name cut down to TAG_MAX capitals for engraving: the initials of its words (horse statue → HS, my final cube →
    MFC), or the first letters of a one-word name (bunny → BUNN). ASCII letters and digits only — the name comes from
    a file someone else chose — and I and O are allowed, since a word's initials are read as a word."""
    words = "".join(c if c.isalnum() else " " for c in str(name)).split()
    raw = "".join(w[0] for w in words) if len(words) > 1 else "".join(words)
    return "".join(c for c in raw.upper() if c.isascii() and c.isalnum())[:TAG_MAX]


def label_tag(params, model_path="") -> str:
    """What is engraved before every part label, so parts of two models cut together are never mixed up — "BUNN Z-3"
    beside "EGG Z-3": the `short_name` parameter when it is set, else the short form of the project's name when it
    has one, else of the model's (`model_name`, which the server sets from the file as it was uploaded; the path is
    the fallback for the CLI). Four characters at most, so the label still fits on a small part; the assembly key
    says which name it stands for."""
    if not params.get("labels", True) or not params.get("label_model", True):
        return ""
    given = "".join(c for c in str(params.get("short_name") or "").upper() if c.isascii() and c.isalnum())[:TAG_MAX]   # as typed, cleaned
    return given or short_name(params.get("project") or params.get("model_name") or (Path(model_path).stem if model_path else ""))


def label_codes(labels, seed: str) -> dict:
    """Puzzle mode: a two-letter code per part, in no relation to where the part goes. Seeded by the job (model +
    technique) and drawn from sorted labels, so re-slicing the same job engraves the same codes and a part cut
    yesterday still matches today's key."""
    pool = [a + b for a in ABC for b in ABC]
    rng = random.Random(zlib.crc32(seed.encode()))   # noqa: S311 — a repeatable shuffle of label codes, not a secret
    rng.shuffle(pool)
    return {lab: pool[i % len(pool)] for i, lab in enumerate(sorted(set(labels)))}


@dataclass
class Slice:
    label: str                 # Slicer-style "Axis-Index" e.g. "X-3", "Z-6", "R-2a", "C-4", "P-12" (panel), "S-7" (strip),
                               # "Z-3a" (the peg or spacer a between Z-3 and Z-4: a connector is named after its lower slice)
    group: str                 # "S" stacked, "X"/"Y" interlocked families, "R" radial half-slice, "C" core disc, "W" a plaque's back plate,
                               # "F" folded panel, "J" joint part (strip / rib), "P" alignment peg / spacer
    M: np.ndarray              # 4x4 local->world; slice lies on local z=0, local x/y are the drawing axes
    thickness: float
    clip: MultiPolygon | None = None    # local region to keep (radial half-plane, core disc)
    cuts: list = field(default_factory=list)      # shapely polygons subtracted from the profile (slots, dowel holes)
    links: list = field(default_factory=list)     # (other label, cut polygon, world point) — a physical connection through that cut
    engages: list = field(default_factory=list)   # labels of slices this one is slotted onto
    slot_dirs: dict = field(default_factory=dict)  # other label → world direction its slot opens toward (the way it slides in)
    raw: MultiPolygon | None = None     # section ∩ clip, before cuts. Modes may set it directly (synthetic parts)
    profile: MultiPolygon | None = None # raw − cuts (what gets cut out), before kerf
    lines: list = field(default_factory=list)     # [(style, LineString)] score / fold lines (local): "mountain" | "valley"
    marks: list = field(default_factory=list)     # [(x, y, text) or (x, y, text, rot)] small engraved marks (local): seam and dowel numbers, rot = turned to read along an edge
    facets: list | None = None          # [(M, MultiPolygon)] for the 3D view when the part is not one flat slice (folded panels)
    pieces: list = field(default_factory=list)    # Piece objects when split
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    fixes: list = field(default_factory=list)     # [{"error", "options": [{"title", "set"}]}] one-click fixes (checks.suggest_fixes)
    note: str = ""                      # extra text shown with the label (e.g. rib angle)
    # what a technique keeps on its own slices while it builds them
    pair: int = 0                       # stacked peg / spacer: the pair of layers it sits between (assembly order)
    cutkeys: dict = field(default_factory=dict)   # stacked: (x, y, angle) → the cut there, so an aligned dowel is cut once
    cutnames: dict = field(default_factory=dict)  # stacked: the same key → its dowel's name (Z-3a), so a rod carried up keeps its name
    inner: MultiPolygon | None = None   # stacked: raw eroded by min_feature, where a cut keeps a full wall (cached)
    dowel_room: list = field(default_factory=list)  # stacked: where a rod through this slice and a neighbour can go (checks)
    radial: np.ndarray | None = None    # radial half-slice: the way it points out from the axis
    lobe: int = 0                       # radial: which axis's lobe the part belongs to
    pn: object = None                   # folded: the Panel this slice is cut from
    additions: list = field(default_factory=list)   # folded: tabs added to the panel's outline
    skipped: dict = field(default_factory=dict)     # folded: what → seams whose joint found no room
    room: MultiPolygon | None = None    # folded: the panel with its tabs so far, a hair in, where a seam number may go (cached)
    room_tabs: int = -1                 # … and how many tabs it had when that was last worked out
    mark_boxes: list = field(default_factory=list)  # folded: the room each of `marks` takes, boxed once (cached)
    reduced: int = 0                    # folded: joints made smaller than asked
    tab_facets: list = field(default_factory=list)  # folded: the tabs as the 3D view shows them, folded onto their panel

    @property
    def bbox(self):
        return self.profile.bounds if self.profile is not None and not self.profile.is_empty else (0, 0, 0, 0)


@dataclass
class Piece:
    label: str                 # "X-3-1", "X-3-2" (Slicer: Axis-Slice-Part)
    geom: MultiPolygon         # final local 2D geometry (before kerf)
    parent: Slice
    lines: list = field(default_factory=list)     # [(style, LineString)] local
    marks: list = field(default_factory=list)     # [(x, y, text)] local
    place: tuple | None = None  # (sheet, x, y, rot) set by pack(); rot in degrees
    kerfed: MultiPolygon | None = None
    nest_shape: MultiPolygon | None = None  # what the nester keeps clear: the kerfed outline, plus the room for a label beside a part too small to carry one
    placed: MultiPolygon | None = None      # kerf-compensated, on the sheet
    placed_lines: list = field(default_factory=list)
    placed_marks: list = field(default_factory=list)
    label_pos: tuple | None = None          # (x, y, rotation) of the label text on the sheet
    label_size: float | None = None         # the label's capital height: the job's font, or smaller where that was all that fit
    label_short: bool = False               # the label engraved without the model's short name: all a small part had room for
    leader: tuple | None = None             # ((x0, y0), (x1, y1)) label → part
    crowded: bool = False                   # the label sits on the part only because no free spot beside it was found
    same: list = field(default_factory=list)     # labels of the pieces cut from this same outline (mark_identical)
    flipped: list = field(default_factory=list)  # … and of those that are its mirror image: same file, turned over

    @property
    def bbox(self):
        return self.geom.bounds

    @property
    def facets(self):
        return self.parent.facets if self.parent.facets is not None else [(self.parent.M, self.geom)]
