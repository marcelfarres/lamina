# 1. Plaque is one technique, built on Stacked

Date: 2026-11-13

## Context

A plaque is slices that stand on a back plate. The same plate can hold parallel slices, a radial fan, or two crossed
families. Stacked, Radial and Interlocked already arrange slices in these three ways.

Two designs were possible:

1. A "back plate" switch inside each of the three techniques.
2. One new technique, Plaque, with a `layout` setting.

## Decision

Plaque is one technique. Its plate settings (back, sink, plate thickness, plate outline, teeth) are the same for
every layout. It reuses the code of the existing techniques and does not copy it:

- `Plaque` is a subclass of `Stacked`. The plane positions come from `Stacked.planes`, and the spacers for floating
  pieces come from `Stacked.connect`, through three hooks: `islands`, `seeds` and `side_step`.
- The plate is a part in a group of its own, `W`. `B` was not free: the page uses it for Radial's boundary planes.
- A tooth is a link between a slice and the plate, not a cut. The checks count a link as a hold.

## A floating piece that nothing can hold is left out

In every other technique, auto-fix never removes a part of the model: a part that cannot be held stays, with its
error. In Plaque, with `floating` = `join` (the default), a floating piece that no slice beside it can hold is left
out, and the notes name it. The owner asked for this on 2026-11-13: a plaque is a display piece, and a fragment that
hangs in the air is not wanted. `floating` = `keep` gives the usual behaviour.

## Consequences

- A change to how Stacked places its planes or its connectors also changes Plaque.
- A user finds every plate setting in one place.
- The exception to "never delete" is limited to this technique and is visible in the notes of every job.
