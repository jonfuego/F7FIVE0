# F7FIVE0 backend

FastAPI. Two services share this codebase:

- `app.main:app`: the API (auth, library, admin, scanning, webhooks)
- `app.stream:app`: the stream gateway (signed URLs, direct play, HLS).
  Always run it as a single worker; the transcoder session registry lives
  in-process.

## Local dev

```powershell
# From backend\
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy ..\.env.example ..\.env   # then fill in DATABASE_URL and the secrets
$env:PYTHONPATH = "."
Push-Location ..; python -m alembic upgrade head; Pop-Location   # alembic.ini lives at the repo root
python -m app.cli create-admin --username admin --name "Admin"
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
# second terminal:
uvicorn app.stream:app --host 127.0.0.1 --port 8002 --reload
```

Or run `..\scripts\dev-backend.ps1` to open both.

Health checks: http://127.0.0.1:8001/api/health and
http://127.0.0.1:8002/stream/health

## Tests

```powershell
python -m pip install pytest
python -m pytest -q
```

Tests run against in-memory SQLite; no PostgreSQL needed.

## Layout

```
app/
  main.py            API entry point
  stream.py          Stream gateway entry point
  config.py          Settings, loaded from ..\.env
  cli.py             create-admin, backfills, audio analysis
  scheduler.py       Background jobs (sync, folder scan, enrichment)
  api/               Route modules
  models/            SQLAlchemy models (migrations in alembic\versions)
  services/
    scan_library.py  Folder scanner for movies / TV / music (no *arr needed)
    scan_music_videos.py
    sync.py          Radarr / Sonarr / Lidarr sync (when configured)
    transcoder.py    ffmpeg HLS + NVENC
    metadata/        TMDB, MusicBrainz, Wikipedia enrichment
```
