# FIX-NOTES: fix/back-keeps-place (W-06 Back keeps your place)

## What was wrong

Two separate causes, both in the web app's scroll memory
(`frontend/lib/scroll-memory.ts`, `frontend/lib/scroll-restoration.tsx`,
`frontend/components/BackButton.tsx`).

1. In-app Back arrow lost the place (always 0 on Songs). The arrow was a plain
   `<Link>` push to a fixed parent href plus a "restore this URL" mark. On an
   artist page that href is `/music`, not the list you came from. From Songs:
   `/music` mounted, used up the mark (it was for `/music`), then its saved
   browse tab redirected (`router.replace`) to `/music/songs`, which mounted with
   no mark and started at the top. The same happens from Albums (`/music/{id}`
   goes back to `/music`). Albums also never called `useScrollRestoration`, so
   it had no saved place at all.
2. Browser Back restored only sometimes (384 vs 600). The mark was set by a
   bubbling `popstate` listener added after the Next router's own. React 19
   renders a transition started inside a `popstate` event synchronously
   (`shouldAttemptEagerTransition`) and flushes its effects, so when the page
   was in the router cache the list mounted (and checked the mark) before our
   listener ran: no restore, and Chromium's own restore clamped to the short
   page (384). When the render suspended (not cached) the mark was in time
   (600). The late mark was also left behind for a later plain visit.

## The fix

- The list hook records the hop when a list is left for another URL
  (`recordLeave`: from, to, `history.length`). The Back arrow
  (`backToList` / `backTarget`) goes `router.back()` when this page is the one
  the list was left for and history has not grown since; it marks the list so
  it restores. Otherwise (direct link, reload with nothing recorded, deeper
  pages, same URL pushed again) it does what it did before: follow its href and
  mark it. Ctrl/Cmd/Shift/middle clicks keep the plain link.
- The popstate listener is registered in the capture phase (runs before the
  Next router's), BackButton registers it too (so a detail page loaded first in
  the tab works), and the mount also restores when it runs inside the popstate
  event itself (`shouldRestore` checks `window.event.type`).
- If a list unmounts mid-restore on the same URL (Suspense remount), the mark
  is put back so the next mount finishes the restore.
- Music > Albums now calls `useScrollRestoration()` like the other lists.

No new features; the arrow's fallback is the old behavior.

## Files changed

- `frontend/lib/scroll-memory.ts`: `shouldRestore`, `recordLeave`, `clearLeave`, `backTarget` (pure).
- `frontend/lib/scroll-restoration.tsx`: capture-phase popstate, `hookPopstate` exported, `backToList`, leave record and remount re-mark in the hook cleanup.
- `frontend/components/BackButton.tsx`: back in history to the list when possible.
- `frontend/app/music/albums/page.tsx`: `useScrollRestoration()`.
- `frontend/lib/scroll-memory.test.ts`: 4 new tests (arrow goes back to the list, falls back to href, junk/same-URL records, mount inside popstate).

## Tests run (frontend, node_modules junctioned from the main checkout)

- `node --test lib/scroll-memory.test.ts`: 11 pass, 0 fail.
- `npm test`: 374 pass, 0 fail.
- `npx tsc --noEmit`: clean.
- `npm run build`: ok.
- `npm run lint`: 0 errors (73 warnings, none in the changed files).

## Left for Jon

- Not tested in a real browser: I had no running server with a library here.
  Rerun W-06 on a library big enough to scroll (Movies, Music Artists / Albums /
  Songs, TV, Music Videos): scroll, open an item, Back with the arrow, and with
  the browser, a few times each. The test library on f750 is too small for
  everything except Songs.
- Behavior to know: the arrow now means "back to where you came from" when you
  came from a list. From an artist opened on Songs it returns to Songs (before
  it went to `/music`). Opened from a direct link or deeper (artist > album >
  arrow), it still goes to its fixed parent page.
