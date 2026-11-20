# 3. A server can keep the library in its own folder

Date: 2026-11-18

## Context

ADR 0002 keeps all library code in the page: the library is the browser's storage, or a folder linked in Chrome
and Edge. In Firefox and Safari the projects are in the browser only. The owner runs Lamina in Docker and wants the
library to be a folder there, the same in every browser, and easy to set up for people who have not used Docker.

## Decision

The server keeps the library in a folder when one setting names it: `LAMINA_LIBRARY=<folder>`. `docker-compose.yml`
sets it, with the host folder `./lamina-projects` mounted at `/library`. The server answers `/api/library`: list,
read, write, remove, and a remove that happens only while the file is unchanged. `api/project` names the folder.
Without the setting, and in the browser build, nothing changes: no endpoint answers, and ADR 0002 holds.

When the server keeps the library, it is the library. The page does not offer a linked folder. The projects that are
in the browser move into the server's folder by the same code as a link. When the server cannot write to its
folder, a save fails with a message that says why and how to fix it. It does not fall back to the browser.

## Consequences

- Projects go to a server only when the server's owner sets this up. There is no login: anyone who can open the
  page can read, change and delete the projects. The README and the compose file say so.
- The page has a third store with the shape of the other two. `restoreStore()` picks it; the other rules do not change.
- The folder is flat, as a linked folder is: one `<name>_v<rev>.lamina.json` file per revision.
- Every browser writes into the one folder. So a write and a delete are conditional: the page sends what it found
  when it listed the folder (no file, or a file of this size and time), and the server checks it under its lock.
  If the file changed, the server answers 412, and the page lists the folder again and asks the person again.

## Only on the server's own names

A web page on another site can point its own domain name at the address of this server (DNS rebinding). The
browser of a person who opens that page then sends requests to this server, and the page can read the answers. It
could read and delete the whole library. So `/api/library` answers only when the request's `Host` is a name of
this server:

- an IP address (IPv4 or IPv6, with or without a port),
- a name without a dot (`localhost`, or a computer name on the local network),
- a name that ends in `.local`, `.lan` or `.home.arpa`,
- a name in the setting `LAMINA_HOSTS` (names separated by commas), for example the domain of a reverse proxy.

Other names get 403, with a message that names `LAMINA_HOSTS`. The rest of the app does not check the name: a page
on another site cannot name the jobs of a tab, because each tab has a random id.
