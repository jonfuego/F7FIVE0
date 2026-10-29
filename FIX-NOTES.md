# fix/organizer-libraries

Hand test L-10: Admin > Organizer always said "No music, movies, or TV libraries
found." even with Movies, TV, Music, Music videos and Podcasts libraries scanned.

## What was wrong

`frontend/app/admin/organizer/page.tsx` called `GET /api/library/libraries` and read
`r.libraries`. The backend (`backend/app/api/library.py::list_libraries`, served as
`GET /api/libraries`) answers a bare array `[{id, name, kind, sort_order}]`, so
`r.libraries` was undefined, `?? []` made it empty, and the page showed the empty
message every time. The bug report was right.

## Which side changed, and why

The frontend. The bare array is the documented shape (docstring), the web's shared
helper `frontend/lib/libraries.ts` already parses it as an array, and the backend
tests (`test_library_access_sweep.py`) iterate it as a list. The phone and TV app
have no caller of this endpoint (only the pure `mobile/src/state/libraryNav.ts`
rules). Changing the backend would have broken the existing helper and tests for no gain.

## The fix

- `frontend/lib/libraries.ts`: the array parsing moved out of `loadLibraries` into
  `parseLibraries(data)` (same behavior), plus `organizerLibraries(libs)` (movies,
  TV, music only, the filter the page already had).
- `frontend/app/admin/organizer/page.tsx`: fetches `LIBRARIES_PATH` (`/api/libraries`,
  the dedicated BFF route; the old `/api/library/libraries` catch-all path reached the
  same backend route) and uses `organizerLibraries(parseLibraries(r))`. A fetch failure
  still shows the page's error, as before.

## Files changed

- `frontend/app/admin/organizer/page.tsx`
- `frontend/lib/libraries.ts`
- `frontend/lib/libraries.test.ts` (new, 6 tests: bare array parses, a wrapped object
  gives [], bad entries dropped, Organizer filter keeps movies/TV/music, loader path,
  loader failure)
- `backend/tests/api/test_library_access_sweep.py` (new
  `test_libraries_endpoint_is_a_bare_list` pinning the response shape)

## Tests run

- `node --test lib/libraries.test.ts` (frontend): 6 passed, 0 failed.
- `npm test` (frontend): 376 passed, 0 failed.
- `npm run lint` (frontend): 0 errors (73 warnings, existing).
- `npm run build` (frontend): ok.
- `python -m pytest -q` (backend, main checkout venv): 1426 passed, 10 skipped, 0 failed.

node_modules came from a junction to the main checkout, removed afterwards.

## Left for Jon

- Not hand tested in a browser. Re-run L-10 on the VM: the library picker should now
  list Movies, TV and Music (music videos and podcasts are left out on purpose, as the
  page always intended). That unblocks L-11 to L-15.
- The rest of L-10 (ownership toggle only on *arr libraries, the Radarr/Lidarr rename
  warning, presets) could not be seen before this fix and was not checked here.
