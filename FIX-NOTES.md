# fix/album-artist-radio (W-10)

## What was wrong

The album page's Artist radio button (`frontend/app/music/[id]/page.tsx`) handed
the radio tracks to the shared helper `startArtistRadio` (`lib/artist-radio.ts`),
which always queued them with `playNextBlock`. In the queue reducer
(`lib/queue-state.ts`) `playNextBlock` only starts playback when the queue is
empty; with any queue already loaded it splices the block in after the current
track and leaves `currentIndex` and `playing` alone. So with a paused player
nothing changed track (no `/api/stream/start`), and with music playing the
queue grew but the current track kept playing. That matches the hand test.

The artist page (`app/music/artists/[artistId]/page.tsx`, `ArtistMixActions`)
calls `playAlbum(items, { shuffle: false })`, which replaces the queue, sets
index 0 and `playing: true`, so the player starts the stream at once.

## The fix

- `lib/artist-radio.ts`: the helper's queue action is now a generic `play`
  dependency instead of being hard-wired to `playNextBlock`.
- `app/music/[id]/page.tsx`: the album page passes
  `play: (items) => playAlbum(items, { shuffle: false })`, the same queue action
  as the artist page.
- `components/PlayerTrackMenu.tsx`: still passes `playNextBlock` (unchanged
  behavior; "Artist radio" from the player menu slots in after the current track).

## Tests

- `lib/artist-radio.test.ts`: updated for the `play` dependency.
- `lib/queue-state.test.ts`: new test that `playAlbum` on a restored, paused
  queue replaces it and marks it playing at index 0, while `playNextBlock` on
  the same queue leaves the current track and `playing: false` (the old bug).

Run in `frontend/` with node_modules junctioned from the main checkout:

- `node --test lib/artist-radio.test.ts lib/queue-state.test.ts lib/play-next.test.ts`: 16 pass, 0 fail
- `npm test`: 371 pass, 0 fail
- `npx tsc --noEmit`: exit 0, no errors

## Left for Jon

- Not hand-tested in a browser here; re-run W-10 on the VM (paused and playing).
- The album page fetches the radio without `?limit=100` (backend default, 12
  tracks in the hand test); the artist page asks for 100. Left as is to keep the
  fix small; say if the album page should ask for 100 too.
