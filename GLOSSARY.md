# Glossary

The words Lamina uses for its parts. One word for one thing.

## Plaque

- **Plaque**: the technique. The model is cut off at a flat plate and its slices stand on edge on that plate.
- **Plate**: the flat part behind the model. All slices stand on it. It has its own material thickness and its own
  outline. Not a *sheet*, which is the stock that parts are cut from.
- **Back**: the side of the model that goes against the plate.
- **Sink**: how far the model goes into the plate, measured from the rearmost point of the model. What is behind the
  front face of the plate is left out.
- **Slice**: a flat part cut from one section of the model. In a plaque, a slice stands square to the plate.
- **Tooth**: the part of a slice that goes through the plate. A tooth is as long as the plate is thick.
- **Plate slot**: the opening in the plate that one tooth goes into.
- **Stretch**: one unbroken length where a slice stands on the plate. A slice can have more than one. Each stretch
  has its own teeth.
- **Floating piece**: a piece of a slice that does not reach the plate.
- **Spacer**: the small flat part that joins a floating piece to the slice beside it. It has a tooth at each end and a
  body as long as the gap between the two slices. Its flat face stands square to the plate.
- **Chord**: in a fan, the straight line between two neighbour slices at one distance from the centre. A fan spacer is as long as its chord.
- **Fan**: the slices of the radial layout. Each is a half-slice: it starts at the hole in the middle and points outward.
- **Layout**: how the slices are arranged on the plate: parallel, radial, or crossed.

## Folded panels

- **Folded panels**: the technique. The surface of the model is unfolded into flat panels that fold back into its shape.
- **Face**: one flat triangle of the surface. Several faces in one plane make one flat piece.
- **Panel**: a group of faces cut as one part. Its flat shape is its **net**.
- **Fold**: an edge between two faces of one panel. The panel bends there. Its **bend** is the angle the panel turns
  through at that edge.
- **Mountain fold**, **valley fold**: a fold as seen from the face that is up on the cutter. A mountain fold bends
  away from you, a valley fold toward you. The same fold is a mountain from one face and a valley from the other.
- **Seam**: an edge between two faces that are cut apart. A **joint** holds a seam together. An **outward seam** is on
  an outside corner of the model, an **inward seam** on an inside corner.
- **Chosen seam**: a seam the user put on an edge. The unfolder never folds there. Every other seam is the
  program's: the unfolder decides it.
- **Score**: a line cut part of the way through, where a panel folds. Not a *cut*, which goes through.
- **Score side**: the face of the sheet that is up on the cutter. It carries the scores and the seam numbers.
- **Groove**: the V cut along a fold of a printed panel. Its two walls meet when the fold reaches its bend.
- **Skin**: the thin layer left under a groove. It is the hinge of a printed fold. The setting is *hinge*.
- **Mitre**: the half of a groove on a seam edge of a printed panel. Two mitred edges meet face to face.
- **Smallest face** (`min_face`): the least height a face may have, in mm. A smaller face is merged into its
  neighbours; the rest of the model stays as it is. 0 keeps every face.
- **Fold stop**: where a printed fold stops, in degrees past or short of its bend.
- **Edge fit**: where two panels of stiff sheet meet at an outward seam. *Inner*: each edge is cut back, the inside
  edges meet. *Through*: one panel runs to the model's edge, the other is cut back to butt against it. *Outer*: both
  edges are on the model's edge.
- **Cut-back**: the strip taken off a seam edge so that stiff panels do not occupy the same corner.
- **Window**: an opening cut in a face, the shape of the face. The **frame** is what is left round it.
- **Removed face**: a face the user took off the surface. It is not cut and belongs to no panel. A removed face stays
  removed when the faces are made again. Used to keep part of the surface, for example a mask from a head.
  Not a *window*, which opens a face and leaves its frame.
- **Rim**: the free edge round removed faces, or round an opening the model has itself. It is a plain cut edge: not a
  seam, and it has no joint.
- **Tab**: a flap on a seam edge that is glued to the next panel. On a printed panel a tab is only as thick as the skin.

## Library

- **Model**: the 3D shape that is uploaded or picked from the examples. Not a *project*.
- **Project**: a model together with the technique, all settings, a name and a revision. One model can be in many
  projects.
- **Revision**: one saved state of a project, numbered `1.0`, `1.1`, `2.0`. A project keeps every revision until it
  is deleted.
- **Library**: the page that shows your projects and the examples, each with a preview.
- **Example**: a model that comes with Lamina. An example is read-only. When you save it, it becomes a project of
  yours.
- **Linked folder**: a folder on your computer that holds the library as files, one file for each revision.
- **Server folder**: a folder that Lamina's server keeps the library in (`LAMINA_LIBRARY`, a Docker volume), one
  file for each revision, for every browser that opens the page. While there is one, it is the library.
