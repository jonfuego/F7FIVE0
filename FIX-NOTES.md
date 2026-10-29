# FIX-NOTES: fix/movie-versions-merge (hand test L-08)

## What was wrong

Two copies of one movie in two folders of the SAME library showed as two
movies with no Version picker.

Root cause, three parts:

1. **The scan never attached a copy from another folder.**
   `scan_library._match_movie` reused an existing movie only when it had a file
   in the *same folder* (root index). A match in another folder became a new
   "twin" Movie row that copied the first one's details (the 2026-10-03 rule,
   from before named libraries existed).
2. **`movie_versions.merge_twins()` was never called.** libmgmt-3 (`cb2653e`)
   added it with unit tests, but the plan's wiring was not built: its handoff
   (vault `projects/f7five0/handoffs/f7five0-libmgmt-3-bulk-dupes-collections_task_v2.md`)
   says the scan should attach a same-library match as another `media_files`
   row, and the scheduler should run `merge_twins` after each folder scan.
   Neither happened.
3. **The web picker ignored the admin pin.** The API sends `is_preferred`, but
   the page and `lib/types.ts` read `is_preferred_version` (always undefined),
   so a pinned version was never the default and "(preferred)" never showed.
   Other clients (home hero, phone, TV) play `media_files[0]`, which came in
   database order, not best-version order.

No product decision was needed. The 2026-10-18 decision (same library = versions,
different libraries = separate entries; in the handoff and in the
`movie_versions.py` docstring) replaces the 2026-10-03 "two entries" rule for
the same-library case. The cross-library "stay separate" rule is kept and tested.

## The fix

- `scan_library._match_movie`: a match with a file in the same library (by
  `media_files.library_id`) is reused, so the new file becomes a second version.
  A match in another library still makes a separate entry that copies details and art.
- `scan_library._scan_movies_root`: a sidecar poster/backdrop from one version's
  folder is not replaced by the other folder's (`_art_from_other_folder`).
  Without this, two folders with posters would swap art on every scan.
- `scheduler._scan_folders`: runs `movie_versions.merge_twins` after the scan
  commits (inside try/except: a failure is logged and rolled back, and the scan
  still finishes). This folds the twins 1.0.18 and older already made, on the
  first scan after the update (the boot scan runs 30 s after start).
- `movie_versions.merge_twins`: buckets by (library, normalized title, year)
  instead of comparing every pair (it now runs after every scan). It skips
  movies with no files or no year. Keeper order: Radarr-owned, then has TMDB
  id, then oldest. Besides files, locks, art and collection items, it now also
  moves `watch_history.ref_id` (relink key), merges `overrides` keys (the
  keeper's win), keeps one pinned version, and avoids a duplicate collection item.
- `version_pick.sort_versions` + `api/library.py`: `/api/movies` and
  `/api/movies/{id}` list `media_files` ready first, then best version
  (pin, height, bitrate, codec). A client that plays `media_files[0]` now
  plays the default version.
- Web: the picker logic moved to `frontend/lib/movie-versions.ts`
  (`readyVersions`, `bestVersion`, `chosenVersion`, `versionLabels`), reads
  `is_preferred`, and labels two same-looking files with their file name.
  The picked version is the one Play opens; with no pick, the best one plays.
- Text: Library folders hint now reads "The same movie in two folders shows up
  once, with a Version picker." Also updated: INSTALL.md, the
  scan_library docstring, and the CLAUDE.md Library folders rule (not the
  session log).

No migration (no schema or data step), so the PostgreSQL migration rules don't apply.

## Files changed

- backend/app/services/scan_library.py
- backend/app/services/movie_versions.py
- backend/app/services/version_pick.py
- backend/app/scheduler.py
- backend/app/api/library.py
- backend/tests/services/test_scan_library.py (two "show twice" tests now
  expect one movie; the cross-library cases use two named libraries)
- backend/tests/services/test_movie_versions_wiring.py (new)
- frontend/lib/movie-versions.ts, frontend/lib/movie-versions.test.ts (new)
- frontend/app/movies/[id]/page.tsx, frontend/lib/types.ts
- frontend/app/admin/LibraryFoldersSection.tsx, INSTALL.md, CLAUDE.md

## Tests run

- Backend, full suite (from `backend/`, with PYTHONPATH unset so the Hermes
  venv doesn't leak in):
  `C:/Users/fuego/Documents/GitHub/F7FIVE0/backend/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -W ignore`
  gave **1433 passed, 10 skipped**.
- With `app/` stashed (the old code), the new tests fail as expected: 6 failed,
  including the L-08 scan test and the scheduler merge test.
- New backend coverage: the L-08 flow (second folder added to the Movies
  library, no TMDB key: one movie, two ready files, API lists 1080p before
  720p, a pin moves the 720p copy first); the folder scan job folds old twins;
  a failing merge doesn't fail the scan; the merge keeps watch history,
  progress, overrides, locks and collections; two libraries stay two entries;
  a rescan is stable (no re-probe, no art re-import).
- Frontend (node_modules junction to the main checkout, removed afterwards):
  `tsc --noEmit -p .` clean; `npm test` **375 pass** (5 new);
  `npm run lint` 0 errors (73 warnings, all already there); `npm run build` ok.

## Left for Jon

- Re-run L-08 on the VM: after the update the first scan merges the existing
  twin The Kid entries. Check that the Version picker shows "1080p ..." and
  "720p ...", and that both versions play.
- The phone app has no Version picker (the libmgmt-3 plan listed one; it never
  landed, so this would be a new feature, not part of this fix). With the new
  API order the phone and TV play the default version.
- Admins can pin a version only through the API
  (`POST /api/admin/library/movies/{id}/versions/{file_id}/prefer`); no web
  button calls it.
- If a merged movie had two different sidecar posters, the keeper's stays. The
  other folder's poster isn't imported while the keeper's file exists.
- Optional: the opt-in PostgreSQL tests weren't run (no migration here), but
  `merge_twins` now runs on every scan, so an upgrade rehearsal on a real
  database with twins would confirm it on PostgreSQL.
