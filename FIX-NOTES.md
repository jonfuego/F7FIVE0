# FIX-NOTES: fix/watch-title-queue

## Bug

Hand test (W-11 side note): on a movie's watch page (/watch/<mediaFileId>) the
title at the top left showed the current MUSIC queue item from localStorage
`f7five0.queue.v1` ("Talk About The Passion") instead of the movie ("The Kid").

## Root cause

`frontend/app/watch/[mediaFileId]/page.tsx` rendered the top bar title as

    stream?.title ?? queueCurrent?.title ?? "Loading..."

`queueCurrent` is the dock queue's current item, whatever it is. The fallback
was meant for the dock-linked audio view (no stream is started there, so the
queue item is the only title), but it applied to every file. For a video,
`stream` stays null while the "Continue watching?" prompt is up and until
`/api/stream/start` answers, so the unrelated song's title showed over the
movie for that whole time (and for good if the stream ever came back without a
title). The tester's repro was taken on the resume prompt, which is exactly
that window. `Player.tsx` and `VideoTransport.tsx` do not render a title from
the queue; the top bar in the page is the only place.

## Fix

New pure helper `frontend/lib/watch-title.ts` (`watchTitle`): use the stream's
title; fall back to the queue item only when the page is following the dock
(`useDockAudio`) or the queue item is this same file; otherwise "Loading...".
The page now calls it. No behavior change for music (dock-linked view, queue
follow, or an audio file opened directly).

## Files changed

- `frontend/app/watch/[mediaFileId]/page.tsx` (title uses `watchTitle`)
- `frontend/lib/watch-title.ts` (new, pure helper)
- `frontend/lib/watch-title.test.ts` (new, node:test)
- `FIX-NOTES.md`

## Tests

Run from `frontend/` with a junction to the main checkout's node_modules
(removed afterwards):

- `node --test lib/watch-title.test.ts`: 7 pass, 0 fail
- `npm test` (all lib tests): 377 pass, 0 fail
- `npx tsc --noEmit`: clean
- `npx eslint` on the three files: 0 errors (3 pre-existing
  `react-hooks/set-state-in-effect` warnings in page.tsx, untouched lines)

## Left for Jon

- Not checked in a browser here; worth a quick look on the VM: queue a song,
  open a movie with saved progress, the prompt and the player should say
  "Loading..." then "The Kid (1921)", never the song.
- If the title ever stays "Loading..." after the movie starts, the backend's
  `_title_for` returned null for that file (no Movie row); that would be a
  separate data issue, not this one.
