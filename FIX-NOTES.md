# FIX-NOTES: fix/art-modal-refresh

Hand-test items A-07 (art dialog), A-12 (File info), A-05 (Fix Match), F7FIVE0 1.0.18.

## 1. Art dialog showed a raw `token_expired` (fixed)

Cause: `frontend/components/ArtOverrideModal.tsx` called `fetch()` directly for all
five calls (search, upload, paste URL, pick from search, remove). The BFF route
(`app/api/admin/art/[...path]/route.ts`) correctly answers 401 when the access token
is gone or expired, but nothing in the dialog refreshed the session, so the 401
detail went straight on screen and every retry failed until a page reload.

Fix: the dialog now uses `apiGet` / `apiPost` / `apiDelete` from `lib/client-api.ts`,
so a 401 waits on the one shared refresh and retries once, like the rest of the web
app. `apiPost` now accepts a `FormData` body and hands it to `fetch` as is (no JSON
`content-type`), so the browser writes the multipart boundary and streams the file;
the BFF route is unchanged and still streams the raw body to the API. The retry
resends the same `FormData`. A 404 on remove still counts as done.

## 2. "Remove override" left the artist at "No art" (real, not fixed: needs a decision)

What happens: since the local-first art change, `art_overrides` is the only source of
art (`services/art.py::resolve_art`). The picture R.E.M. had before (700 px is the
TheAudioDB thumb size, so most likely the `artist_auto` auto-fill, or a folder-scan
sidecar) was itself the one `artist/<id>/thumb` row. An admin upload or URL replaces
that row in place (`save_upload_bytes` overwrites the file, or deletes it when the
extension changes), so the earlier picture is gone from the database and disk.
`clear_override` then deletes the row, and there is nothing to fall back to. The art
comes back only when something re-derives it: the auto-fill job (after boot and after
each music / music videos scan), the folder scan's sidecar import, or the *arr sync.
The `models/art.py` docstring ("removing an override cleanly restores whatever the
sync had picked") is stale.

Also note the dialog offers "Remove override" for any art row, including art an admin
never set (the frontend decides with `canonical.poster_path` starting `/api/art/`).

Why not fixed here: a real fallback is a behavior change Jon should pick. Options:
- (a) Keep the replaced non-admin image (a `previous_*` copy or a second row) when an
  admin writes, and restore it on remove. Schema change, most faithful.
- (b) After remove, re-derive at once: for an artist thumb queue
  `scheduler.trigger_artist_art_autofill()`; for others rely on the next scan/sync.
  Small, but the dialog would still show "No art" until the job finishes and the page
  reloads, and it does nothing for movies / series without TMDB.
- (c) Leave it and relabel the button "Remove image" with a hint that the scan or
  sync will fill it again. Copy change only.

## 3. Display polish (fixed)

- A-12 File info path in upper case. The movie page renders the File info sheet
  inside `.detail .info .kicker`, which is `text-transform: uppercase`, wide tracking,
  bold and red, and the sheet inherited all of it. `.detail .ep-info-scrim` (the
  sheet root) now resets text-transform, letter-spacing, weight and color. The copy
  text was already right.
- A-05 Fix Match refusal began with `already_matched:`. The API puts a machine code in
  front of the sentence and backend tests and clients match on it, so the API is
  unchanged. New `lib/error-detail.ts::detailText` drops a leading `snake_case: ` code
  when a sentence follows (a bare code like `override_not_found`, or a sentence with a
  colon later, is left alone). `EditOverridesModal`'s `extractError` uses it, and the
  art dialog's errors go through `errorText` from the same file.

## Files changed

- `frontend/lib/client-api.ts`: `FormData` body passes through untouched.
- `frontend/components/ArtOverrideModal.tsx`: all calls through client-api; local
  `extractError` removed.
- `frontend/lib/error-detail.ts` (new): `detailText`, `errorText`.
- `frontend/components/EditOverridesModal.tsx`: `extractError` strips the code prefix.
- `frontend/app/globals.css`: File info sheet typography reset.
- Tests: `frontend/lib/client-api.test.ts` (FormData upload resent after one refresh
  with no JSON content-type; JSON body unchanged; delete refreshes and resolves on 204),
  `frontend/lib/error-detail.test.ts` (new; prefix stripping, errorText, CSS reset).

## Tests run (frontend, node_modules junction to the main checkout)

- `npm test` (node --test lib/*.test.ts *.test.js): 377 passed, 0 failed (7 new).
- `npx tsc --noEmit`: clean.
- `npx eslint` on the changed files: 0 errors; the 3 warnings
  (react-hooks/set-state-in-effect) are the same ones as on main.
- Backend not touched, so pytest not run. `npm run build` not run.

## Left for Jon

- Decide item 2 (options above).
- Hand check on a real install: let the access token expire (15 min) with the art
  dialog open, then Upload, Paste URL and Remove each work without a reload; File
  info path shows real case on the movie page; the Fix Match refusal starts with
  the artist name.
- Out of scope but same pattern: `EditOverridesModal.tsx` (Fix Match search/apply,
  save, refresh) and the podcasts OPML import still use plain `fetch()` and will show
  a raw 401 after expiry (OPML reloads the page). Worth the same treatment later.
