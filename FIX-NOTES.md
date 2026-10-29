# FIX-NOTES: fix/library-health-counts (hand test L-05)

## What was wrong

- Admin > Library health never drew the `unmatched` and `missing_art` counts.
  The backend (`backend/app/api/admin_library_health.py::get_health`) returns
  both per-kind maps (`movie`, `series`, `artist`, `album`) and the page's
  `HealthCounts` type had them, but `frontend/app/admin/library-health/page.tsx`
  only rendered four `CountCard`s (missing files, eligible for cleanup, probe
  errors, unreachable folders). A frontend-only gap; the API was right.
- The missing-files list does exist on the page ("Eligible missing files", from
  `GET /api/admin/library/health/missing-files`). It showed nothing on the test
  VM by design: it lists only files missing 7 or more days whose library folder
  is reachable (the cleanup candidates), and the tester's 4 podcast mp3s were
  deleted the same day. The page then said "No missing files eligible for
  cleanup." beside "Missing files 4", which read like a bug.

## The fix

- Two new cards, "Unmatched" and "Missing art": the total of the map plus a
  per-kind line such as "1 movie, 1 TV show, 5 artists, 3 albums" (zero kinds
  left out). The header line names them too.
- The empty-list text now explains itself: "4 files are missing, none eligible
  for cleanup yet. A missing file is listed here once it has been missing for 7
  days and its library folder is reachable." (or "No missing files." at zero).
- No backend change, no new endpoint or screen. The wording lives in the pure
  helper `frontend/lib/library-health.ts`.

## Files changed

- `frontend/app/admin/library-health/page.tsx`
- `frontend/lib/library-health.ts` (new)
- `frontend/lib/library-health.test.ts` (new)
- `backend/tests/api/test_library_health.py` (new test
  `test_health_unmatched_and_missing_art_per_kind`, pins the two maps' shape)

## Tests run

- `cd backend; C:/Users/fuego/Documents/GitHub/F7FIVE0/backend/.venv/Scripts/python.exe -m pytest -q -p no:warnings`:
  1426 passed, 10 skipped.
- `cd frontend; npm test`: 375 passed, 0 failed (5 new in `library-health.test.ts`).
- `cd frontend; npm run lint`: 0 errors, 73 warnings (the one on this page,
  `set-state-in-effect` at `load()`, was there before).
- `cd frontend; npx tsc --noEmit -p tsconfig.json`: clean. `npm run build`: ok.
- node_modules was a junction to the main checkout, removed afterwards.

## Left for Jon

- Not checked in a browser; a look at Admin > Library health on the VM (6 cards,
  the per-kind lines, the empty-list text) would close L-05.
- Product call, not done here: there is no list of WHICH files are missing
  before the 7-day mark. If the hand test wants one, it is a behavior change
  (for example a `?all=1` on `/health/missing-files` and a second section).
- Also returned by the API and still not drawn on this page: duplicate movie
  and episode versions, music duplicates and organizer flip-flop warnings. The
  admin overview's Needs attention lists them, so they were left alone.
- The counts are of rows, not of what is visible: `missing_art` counts items
  with no `art_overrides` row for the main role, so an item whose art comes only
  from `poster_path` / `image_path` / `cover_path` may still count. Not verified on real data.
