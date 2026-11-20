# 2. The library is a linked folder or the browser's storage, never both

Date: 2026-11-16

Partly amended by ADR 0003: a server with `LAMINA_LIBRARY` set keeps the library in its own folder.

## Context

Projects were saved as a download and opened through a file dialog. The library keeps them in the app, with a
preview of each. The projects must stay private, and the owner also wants them as files on disk.

Three designs were possible:

1. The browser's storage only.
2. The browser's storage, plus a folder that the local server reads and writes.
3. The browser's storage, plus a folder that the page itself reads and writes (File System Access API). Only
   Chrome and Edge have it.

## Decision

Design 3. All library code is in the page. The server gets no new endpoint, and no project is sent to a server
because of the library. The hosted build and the local build behave the same.

When a folder is linked, the folder is the library: the page shows what is in the folder, a file dropped in it
appears, and a file deleted from it is gone. The browser's storage is the library only when no folder is linked.
Linking a folder moves the projects out of the browser's storage into the folder. There is no mirror.

The folder is flat. One file holds one revision, in the project file format, with its preview inside. There is no
index file in the folder.

When a linked folder cannot be reached, a save fails with a message. It does not fall back to the browser's
storage.

## Consequences

- A linked folder can be put under version control, backed up, and linked at more than one address.
- In Firefox and Safari the projects are in the browser only, and are lost when the site data is cleared. The page
  says so and offers "export all".
- Each revision holds its own copy of the model, so many revisions of a large model use much disk space.
- Because there is no mirror and no fallback, there is never a question of which copy is the newest.
