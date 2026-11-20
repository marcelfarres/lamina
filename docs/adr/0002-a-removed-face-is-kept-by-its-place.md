# 2. A removed face is kept by its place, a seam is not

Date: 2026-11-17

## Context

In Folded panels the user marks two things on the model: seams (an edge that must be cut apart) and removed faces
(a face that is not cut, to keep only a part of the surface, for example a mask from a head).

The faces of a folded model are made again each time the facet size, the smallest face, the model's size or its
rotation changes. A face or an edge has no number that stays the same. The owner asked that removed faces stay
removed after such a change, so that he does not have to remove them again.

Three designs were possible:

1. Keep the number of each face or edge. Every change of the facet size loses the marks.
2. Keep the two ends of an edge, or the corners of a face, and find the exact same edge or face again. The marks
   are lost when the faces are made again, and the plan says so. Seams work this way since they were added.
3. Keep the place: the triangle of each removed face, and remove whatever face is at that place afterwards.

## Decision

A removed face is kept by its place (design 3). A seam stays as it is (design 2).

- The setting `removed` holds the triangle of each removed face in the coordinates of the model file. The plan
  gives the matrix from the file's coordinates to the plan's millimetres (`frame`). So the places follow the model
  when its size or its rotation changes.
- A face is removed when the line through its middle, along its own normal, meets a stored triangle that faces the
  same way (`faces_at` in `core/unfold.py`). The far side of a thin wall is not removed.
- A seam is not kept by its place. A removed region has an area, and "the faces in this area" has a clear meaning
  on any set of faces. A seam is a line along edges, and a new set of faces has no edges on that line.
- The two work together in one direction. The user paints a seam loop, selects one side and removes it. After
  that, the removed faces hold the shape. The seams on the rim are left out without a warning.

## Consequences

- After a change of facet size the rim moves by one triangle at most, and it follows the edges of the triangles.
  A smooth rim along a drawn line is a different feature.
- A change of the model's form (smooth, remesh) removes whatever surface is at the stored places.
- The stored list grows when the user removes more faces after a change of facet size. It holds triangles of
  both sizes. To put a face back, its stored triangle is taken out of the list.
- Seams the user chose are still lost when the faces are made again, with the warning that exists.
- `removed` is in the file's coordinates and `seams` is in the plan's millimetres. A reader must not assume that
  the two settings use the same coordinates.
