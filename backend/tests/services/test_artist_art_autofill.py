"""Artist art auto-fill (batch 7 item 2): artists with no thumb get one from
TheAudioDB or Deezer, saved with their own `source_kind` (`artist_auto`), and
any other art is never overwritten. All HTTP is mocked, including the image
download.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

from app import scheduler
from app.config import settings
from app.models.art import (
    ArtOverride, ENTITY_ARTIST, ROLE_THUMB, SOURCE_ARTIST_AUTO,
)
from app.models.music import Artist
from app.models.user import User
from app.services import app_settings, artist_art_autofill as autofill
from app.services import art as art_service
from app.services import scan_library
from app.services.artist_art_autofill import autofill_artist_art


def _png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def _deezer_hit(id_, name, fans, hash_):
    base = f"https://cdn-images.dzcdn.net/images/artist/{hash_}"
    return {
        "id": id_, "name": name, "nb_fan": fans,
        "picture_medium": f"{base}/250x250-000000-80-0-0.jpg",
        "picture_xl": f"{base}/1000x1000-000000-80-0-0.jpg",
    }


class FakeWeb:
    """Mocked Deezer, TheAudioDB and image CDNs. `deezer_data` maps a search
    name to the list of Deezer hits; `audiodb_data` maps an MBID or a name to
    a `strArtistThumb`."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.deezer_data: dict[str, list] = {}
        self.audiodb_data: dict[str, str] = {}
        self.deezer_status = 200
        self.images_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host = request.url.host
        if host == "api.deezer.com":
            if self.deezer_status != 200:
                return httpx.Response(self.deezer_status, text="busy")
            q = request.url.params["q"]
            return httpx.Response(200, json={"data": self.deezer_data.get(q, [])})
        if host == "www.theaudiodb.com":
            term = request.url.params.get("i") or request.url.params.get("s")
            thumb = self.audiodb_data.get(term)
            if thumb is None:
                return httpx.Response(200, json={"artists": None})
            return httpx.Response(200, json={"artists": [{
                "strArtist": request.url.params.get("s") or "by musicbrainz id",
                "strArtistThumb": thumb,
            }]})
        if host in ("cdn-images.dzcdn.net", "r2.theaudiodb.com"):
            if self.images_status != 200:
                return httpx.Response(self.images_status)
            return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    def to(self, host: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.host == host]


@pytest.fixture()
def web(monkeypatch, tmp_path, db_session):
    # The synthetic user the migrations seed; art rows point at it.
    db_session.add(User(
        id=art_service.SYSTEM_USER_ID, username="system", display_name="System",
        password_hash="x", role="member", is_active=False,
    ))
    db_session.commit()
    fake = FakeWeb()
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    monkeypatch.setattr(settings, "art_root", tmp_path)
    monkeypatch.setattr(settings, "deezer_enabled", True)
    monkeypatch.setattr(settings, "audiodb_api_key", "")
    monkeypatch.setattr(settings, "artist_art_autofill_enabled", True)
    # The SSRF guard does a real DNS lookup; the mocked hosts are fixed.
    monkeypatch.setattr(art_service, "_assert_public_host", lambda url: None)
    return fake


def _artist(db, name, mbid=None):
    a = Artist(name=name, mbid=mbid)
    db.add(a)
    db.commit()
    return a


def _thumb(db, artist):
    db.expire_all()
    return db.get(ArtOverride, (ENTITY_ARTIST, artist.id, ROLE_THUMB))


def _run(db, **kw):
    kw.setdefault("pause_sec", 0)
    return autofill_artist_art(db, **kw)


# ---------------------------------------------------------------------------
# Fills artists with no thumb
# ---------------------------------------------------------------------------
def test_artist_with_no_thumb_gets_one_from_deezer(db_session, web):
    web.deezer_data["Modest Mouse"] = [
        _deezer_hit(414435842, "Modest Mouse", 0, ""),       # empty stub
        _deezer_hit(1237, "Modest Mouse", 181864, "ffff"),
    ]
    artist = _artist(db_session, "Modest Mouse")

    assert _run(db_session) == 1

    row = _thumb(db_session, artist)
    assert row is not None
    assert row.source_kind == SOURCE_ARTIST_AUTO == "artist_auto"
    assert row.source_ref.endswith("/ffff/1000x1000-000000-80-0-0.jpg")
    assert (settings.art_root / row.local_path).is_file()
    # The normal art save ran: the size copies exist too.
    assert list((settings.art_root / row.local_path).parent.glob("*.webp"))


def test_audiodb_is_used_first_by_musicbrainz_id(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "audiodb_api_key", "123")
    mbid = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
    web.audiodb_data[mbid] = "https://r2.theaudiodb.com/images/media/artist/thumb/x.jpg"
    artist = _artist(db_session, "Coldplay", mbid=mbid)

    assert _run(db_session) == 1

    row = _thumb(db_session, artist)
    assert row.source_kind == "artist_auto"
    assert row.source_ref == "https://r2.theaudiodb.com/images/media/artist/thumb/x.jpg"
    assert web.to("api.deezer.com") == []  # AudioDB answered, no second source


def test_falls_back_to_deezer_when_audiodb_has_nothing(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "audiodb_api_key", "123")
    web.deezer_data["Edward Ka-Spel"] = [_deezer_hit(60610, "Edward Ka-Spel", 832, "abab")]
    artist = _artist(db_session, "Edward KaSpel")  # spelled differently
    web.deezer_data["Edward KaSpel"] = web.deezer_data["Edward Ka-Spel"]

    assert _run(db_session) == 1

    assert _thumb(db_session, artist).source_ref.endswith("/abab/1000x1000-000000-80-0-0.jpg")
    assert len(web.to("www.theaudiodb.com")) == 1


def test_name_must_match_closely(db_session, web):
    web.deezer_data["New Order"] = [
        _deezer_hit(11416926, "New Beat Order", 2598, "c1"),
        _deezer_hit(1, "Karaoke - New Order", 6, "c2"),
    ]
    artist = _artist(db_session, "New Order")

    assert _run(db_session) == 0
    assert _thumb(db_session, artist) is None


def test_various_artists_is_not_looked_up(db_session, web):
    _artist(db_session, "Various Artists")

    assert _run(db_session) == 0
    assert web.calls == []


def test_off_switch(db_session, web, monkeypatch):
    monkeypatch.setattr(settings, "artist_art_autofill_enabled", False)
    _artist(db_session, "Modest Mouse")

    assert _run(db_session) == 0
    assert web.calls == []


# ---------------------------------------------------------------------------
# Never overwrites existing art
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", [
    "upload", "url", "local", "lidarr", "tmdb", "audiodb", "deezer", "musicbrainz",
    "frame", "itunes",
])
def test_existing_art_of_any_other_kind_is_kept(db_session, web, kind):
    web.deezer_data["Modest Mouse"] = [_deezer_hit(1237, "Modest Mouse", 10, "ffff")]
    artist = _artist(db_session, "Modest Mouse")
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id, role=ROLE_THUMB,
        data=_png((1, 2, 3)), set_by_user_id=art_service.SYSTEM_USER_ID,
        source_kind=kind, source_ref="keep-me",
    )
    db_session.commit()
    before = _thumb(db_session, artist)
    path_before = before.local_path
    bytes_before = (settings.art_root / path_before).read_bytes()

    assert _run(db_session) == 0

    after = _thumb(db_session, artist)
    assert after.source_kind == kind
    assert after.source_ref == "keep-me"
    assert after.local_path == path_before
    assert (settings.art_root / after.local_path).read_bytes() == bytes_before
    assert web.calls == []  # an artist with art is not even looked up


def test_art_set_while_downloading_wins(db_session, web, monkeypatch):
    """An admin saves art between the lookup and the save: it stays."""
    web.deezer_data["Modest Mouse"] = [_deezer_hit(1237, "Modest Mouse", 10, "ffff")]
    artist = _artist(db_session, "Modest Mouse")
    real_fetch = autofill.fetch_url_bytes

    def fetch_then_admin_sets_art(url):
        data = real_fetch(url)
        art_service.save_upload_bytes(
            db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id,
            role=ROLE_THUMB, data=_png((9, 9, 9)),
            set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="upload",
        )
        return data

    monkeypatch.setattr(autofill, "fetch_url_bytes", fetch_then_admin_sets_art)

    assert _run(db_session) == 0
    assert _thumb(db_session, artist).source_kind == "upload"


# ---------------------------------------------------------------------------
# Safe to rerun
# ---------------------------------------------------------------------------
def test_second_run_creates_nothing_new(db_session, web):
    web.deezer_data["Modest Mouse"] = [_deezer_hit(1237, "Modest Mouse", 10, "ffff")]
    got = _artist(db_session, "Modest Mouse")
    nothing = _artist(db_session, "Nobody Known")  # no Deezer hit

    assert _run(db_session) == 1
    calls_after_first = len(web.calls)
    first_row = _thumb(db_session, got)
    set_at = first_row.set_at

    assert _run(db_session) == 0

    assert len(web.calls) == calls_after_first  # not asked again
    assert _thumb(db_session, got).set_at == set_at
    assert _thumb(db_session, nothing) is None
    rows = db_session.query(ArtOverride).count()
    assert rows == 1


def test_a_miss_is_retried_after_the_retry_window(db_session, web):
    artist = _artist(db_session, "Nobody Known")
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)

    _run(db_session, now=now)
    asked = len(web.to("api.deezer.com"))
    _run(db_session, now=now + timedelta(days=5))
    assert len(web.to("api.deezer.com")) == asked

    web.deezer_data["Nobody Known"] = [_deezer_hit(5, "Nobody Known", 3, "9999")]
    assert _run(db_session, now=now + timedelta(days=31)) == 1
    assert _thumb(db_session, artist).source_kind == "artist_auto"


def test_a_renamed_artist_is_looked_up_again(db_session, web):
    artist = _artist(db_session, "Nobody Known")
    _run(db_session)
    web.deezer_data["Somebody Known"] = [_deezer_hit(5, "Somebody Known", 3, "9999")]
    artist.name = "Somebody Known"
    db_session.commit()

    assert _run(db_session) == 1


def test_service_errors_are_not_remembered_and_stop_the_run(db_session, web):
    web.deezer_status = 500
    for i in range(8):
        _artist(db_session, f"Band {i}")

    assert _run(db_session) == 0

    assert len(web.to("api.deezer.com")) == autofill.MAX_CONSECUTIVE_ERRORS
    assert (app_settings.get(db_session, autofill.MISSES_KEY) or {}) == {}
    # Deezer comes back: the next run fills the artists the first one skipped.
    web.deezer_status = 200
    for i in range(8):
        web.deezer_data[f"Band {i}"] = [_deezer_hit(i + 100, f"Band {i}", 5, f"{i:04d}")]
    assert _run(db_session) == 8


def test_runs_in_batches_and_paces_requests(db_session, web):
    for i in range(7):
        name = f"Band {i}"
        web.deezer_data[name] = [_deezer_hit(i + 100, name, 5, f"{i:04d}")]
        _artist(db_session, name)
    pauses: list[float] = []

    assert _run(db_session, batch_size=3, pause_sec=1.5, sleep=pauses.append) == 7

    assert pauses == [1.5] * 7


def test_unusable_image_is_skipped_without_raising(db_session, web):
    web.deezer_data["Modest Mouse"] = [_deezer_hit(1237, "Modest Mouse", 10, "ffff")]
    web.images_status = 404
    artist = _artist(db_session, "Modest Mouse")

    assert _run(db_session) == 0
    assert _thumb(db_session, artist) is None


# ---------------------------------------------------------------------------
# Any other art replaces it later
# ---------------------------------------------------------------------------
def _auto_art(db, web, name="Modest Mouse"):
    web.deezer_data[name] = [_deezer_hit(1237, name, 10, "ffff")]
    artist = _artist(db, name)
    assert _run(db) == 1
    return artist


def test_a_scanned_sidecar_image_replaces_it(db_session, web, tmp_path):
    artist = _auto_art(db_session, web)
    side = tmp_path / "artist.png"
    side.write_bytes(_png((5, 200, 5)))

    scan_library._import_art_file(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id,
        role=ROLE_THUMB, image_path=str(side), stats=scan_library.FolderScanStats(),
    )

    assert _thumb(db_session, artist).source_kind == "local"


def test_a_lidarr_sync_replaces_it(db_session, web):
    artist = _auto_art(db_session, web)
    web.deezer_data.clear()

    row = art_service.download_art_on_sync(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id,
        role=ROLE_THUMB, cover_type="poster", source_kind="lidarr",
        images=[{"coverType": "poster", "remoteUrl": "https://cdn-images.dzcdn.net/images/artist/ffff/lidarr.jpg"}],
    )

    assert row is not None
    assert _thumb(db_session, artist).source_kind == "lidarr"


def test_a_lidarr_sync_still_does_not_replace_admin_art(db_session, web):
    artist = _artist(db_session, "Modest Mouse")
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id, role=ROLE_THUMB,
        data=_png(), set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="upload",
    )
    db_session.commit()

    row = art_service.download_art_on_sync(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id,
        role=ROLE_THUMB, cover_type="poster", source_kind="lidarr",
        images=[{"coverType": "poster", "remoteUrl": "https://cdn-images.dzcdn.net/x.jpg"}],
    )

    assert row is None
    assert _thumb(db_session, artist).source_kind == "upload"


def test_an_admin_pick_replaces_it(db_session, web):
    artist = _auto_art(db_session, web)

    art_service.fetch_and_save_url(
        db_session, entity_kind=ENTITY_ARTIST, entity_id=artist.id,
        role=ROLE_THUMB, url="https://cdn-images.dzcdn.net/images/artist/ffff/pick.jpg",
        set_by_user_id=art_service.SYSTEM_USER_ID, source_kind="deezer",
    )

    assert _thumb(db_session, artist).source_kind == "deezer"


# ---------------------------------------------------------------------------
# Scheduler wiring
# ---------------------------------------------------------------------------
class _FakeScheduler:
    def __init__(self):
        self.jobs: list[dict] = []

    def add_job(self, func, **kw):
        self.jobs.append({"func": func, **kw})


def test_trigger_is_a_noop_without_a_scheduler(monkeypatch):
    monkeypatch.setattr(scheduler, "_scheduler", None)
    scheduler.trigger_artist_art_autofill()  # must not raise


def test_trigger_queues_one_job_that_never_stacks(monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler, "_scheduler", fake)

    scheduler.trigger_artist_art_autofill(delay_sec=5)
    scheduler.trigger_artist_art_autofill(delay_sec=5)

    assert [j["id"] for j in fake.jobs] == [scheduler.JOB_ARTIST_ART] * 2
    for job in fake.jobs:
        assert job["func"] is scheduler._run_artist_art_autofill
        assert job["max_instances"] == 1
        assert job["coalesce"] is True
        assert job["replace_existing"] is True


def test_run_skips_while_another_run_is_going(monkeypatch):
    called = []
    monkeypatch.setattr(autofill, "autofill_artist_art", lambda db: called.append(1) or 0)
    assert scheduler._artist_art_lock.acquire(blocking=False)
    try:
        scheduler._run_artist_art_autofill()
    finally:
        scheduler._artist_art_lock.release()
    assert called == []
