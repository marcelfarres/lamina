"""Data carried through the pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from shapely.geometry import MultiPolygon


@dataclass
class Slice:
    label: str                 # Slicer-style "Axis-Index" e.g. "X-3", "Z-6", "R-2a", "C-4", "P-12" (panel), "S-7" (strip)
    group: str                 # "S" stacked, "X"/"Y" interlocked families, "R" radial half-slice, "C" core disc,
                               # "F" folded panel, "J" joint part (strip / rib), "P" alignment peg
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
    marks: list = field(default_factory=list)     # [(x, y, text)] small engraved marks (local), e.g. seam numbers
    facets: list | None = None          # [(M, MultiPolygon)] for the 3D view when the part is not one flat slice (folded panels)
    pieces: list = field(default_factory=list)    # Piece objects when split
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    note: str = ""                      # extra text shown with the label (e.g. rib angle)

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
    placed: MultiPolygon | None = None      # kerf-compensated, on the sheet
    placed_lines: list = field(default_factory=list)
    placed_marks: list = field(default_factory=list)
    label_pos: tuple | None = None          # (x, y, rotation) of the label text on the sheet
    leader: tuple | None = None             # ((x0, y0), (x1, y1)) label → part
    same: list = field(default_factory=list)     # labels of the pieces cut from this same outline (mark_identical)
    flipped: list = field(default_factory=list)  # … and of those that are its mirror image: same file, turned over

    @property
    def bbox(self):
        return self.geom.bounds

    @property
    def facets(self):
        return self.parent.facets if self.parent.facets is not None else [(self.parent.M, self.geom)]
