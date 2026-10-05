"""Tests for the automatic audio-analysis backfill.

Covers the shared engine the `analyze-audio` CLI and the scheduler job both use
(`app.services.audio_analysis`) plus the admin start/progress endpoints:

- the working set contains ONLY tracks with no analysis row yet;
- a scheduler step processes exactly ONE track and leaves the rest pending;
- the progress counts (analyzed / total) are correct and climb as steps run.

The heavy ffmpeg work (`measure_loudness`, `compute_waveform`) is stubbed so the
tests are fast and deterministic and need no ffmpeg on PATH, following the
monkeypatch style in test_audio_analysis_endpoints.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.audio_analysis import TrackAudioAnalysis
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track
from app.services import audio_analysis as aa


@pytest.fixture()
def library(db_session, tmp_path):
    """One artist/album with three tracks, each a ready media file."""
    artist = Artist(name="Aphex Twin", genres=["electronic"])
    db_session.add(artist)
    db_session.flush()
    album = Album(artist_id=artist.id, title="Selected Ambient Works", genres=["electronic"])
    db_session.add(album)
    db_session.flush()

    tracks = []
    for i in range(3):
        t = Track(album_id=album.id, title=f"Track {i}", track_number=i + 1,
                  duration_sec=180)
        db_session.add(t)
        db_session.flush()
        p = tmp_path / f"track{i}.flac"
        p.write_bytes(b"not real audio")
        mf = MediaFile(
            kind=MediaKind.track, ref_id=t.id, path=str(p),
            container="flac", scan_state=ScanState.ready, duration_sec=180,
        )
        db_session.add(mf)
        db_session.flush()
        tracks.append(t)
    db_session.commit()
    return {"artist": artist, "album": album, "tracks": tracks}


@pytest.fixture()
def stub_ffmpeg(monkeypatch):
    """Make the analysis engine deterministic without ffmpeg.

    measure_loudness returns a fixed LUFS; compute_waveform a fixed envelope.
    Records how many tracks were measured so a test can assert 'one at a time'.
    """
    calls = {"loudness": 0, "waveform": 0}

    def _loud(_path, timeout=120.0):
        calls["loudness"] += 1
        return -14.0

    def _wave(_path, buckets=aa.DEFAULT_WAVEFORM_BUCKETS, timeout=120.0):
        calls["waveform"] += 1
        return [10, 50, 90, 40, 5]

    monkeypatch.setattr(aa, "measure_loudness", _loud)
    monkeypatch.setattr(aa, "compute_waveform", _wave)
    return calls


# ---------------------------------------------------------------------------
# tracks_needing_analysis: only tracks without a stamped analysis row
# ---------------------------------------------------------------------------
def test_working_set_only_unanalyzed(db_session, library):
    t0, t1, t2 = library["tracks"]
    # t1 already has a stamped analysis row; t2 has an unstamped (failed) row.
    db_session.add(TrackAudioAnalysis(
        track_id=t1.id, integrated_lufs=-13.0,
        analyzed_at=datetime.now(timezone.utc),
    ))
    db_session.add(TrackAudioAnalysis(track_id=t2.id))  # analyzed_at is NULL
    db_session.commit()

    pending = aa.tracks_needing_analysis(db_session)
    assert t1.id not in pending            # already analyzed -> excluded
    assert t0.id in pending                # no row -> included
    assert t2.id in pending                # half-written row -> included


def test_working_set_empty_when_all_analyzed(db_session, library):
    for t in library["tracks"]:
        db_session.add(TrackAudioAnalysis(
            track_id=t.id, analyzed_at=datetime.now(timezone.utc),
        ))
    db_session.commit()
    assert aa.tracks_needing_analysis(db_session) == []


# ---------------------------------------------------------------------------
# analyze_track: one track, correct status, stamps a row
# ---------------------------------------------------------------------------
def test_analyze_track_stamps_row(db_session, library, stub_ffmpeg):
    t0 = library["tracks"][0]
    status = aa.analyze_track(db_session, t0.id)
    db_session.commit()
    assert status == aa.STATUS_ANALYZED
    assert stub_ffmpeg["loudness"] == 1  # exactly one track measured
    row = db_session.query(TrackAudioAnalysis).filter_by(track_id=t0.id).one()
    assert row.analyzed_at is not None
    assert row.integrated_lufs == -14.0
    assert row.waveform_peaks == [10, 50, 90, 40, 5]


def test_analyze_track_skips_already_analyzed(db_session, library, stub_ffmpeg):
    t0 = library["tracks"][0]
    db_session.add(TrackAudioAnalysis(
        track_id=t0.id, analyzed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    status = aa.analyze_track(db_session, t0.id)
    assert status == aa.STATUS_SKIPPED
    assert stub_ffmpeg["loudness"] == 0  # no ffmpeg work for a skipped track


def test_analyze_track_no_file(db_session, library, stub_ffmpeg):
    # A track with no ready media file reports no_file, not a crash.
    orphan = Track(album_id=library["album"].id, title="Orphan",
                   track_number=99, duration_sec=100)
    db_session.add(orphan)
    db_session.commit()
    assert aa.analyze_track(db_session, orphan.id) == aa.STATUS_NO_FILE


# ---------------------------------------------------------------------------
# scheduler step: processes exactly one track per run
# ---------------------------------------------------------------------------
def test_scheduler_step_one_track_at_a_time(db_session, library, stub_ffmpeg, monkeypatch):
    from app import scheduler

    # Route the scheduler's own-session helper to the test session, and don't
    # actually reschedule (the scheduler isn't running under the test).
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield db_session

    monkeypatch.setattr(scheduler, "db_session", _fake_session)
    monkeypatch.setattr(scheduler, "_kick_audio_analysis", lambda delay_sec=0: None)

    # Three tracks pending. One step should analyze exactly one of them.
    assert len(aa.tracks_needing_analysis(db_session)) == 3
    scheduler._run_audio_analysis_step()
    assert stub_ffmpeg["loudness"] == 1
    assert len(aa.tracks_needing_analysis(db_session)) == 2

    # A second step takes the next one.
    scheduler._run_audio_analysis_step()
    assert stub_ffmpeg["loudness"] == 2
    assert len(aa.tracks_needing_analysis(db_session)) == 1


# ---------------------------------------------------------------------------
# progress counts
# ---------------------------------------------------------------------------
def test_progress_counts(db_session, library, stub_ffmpeg):
    prog = aa.analysis_progress(db_session)
    assert prog == {"analyzed": 0, "total": 3}

    aa.analyze_track(db_session, library["tracks"][0].id)
    db_session.commit()
    prog = aa.analysis_progress(db_session)
    assert prog == {"analyzed": 1, "total": 3}

    aa.analyze_track(db_session, library["tracks"][1].id)
    db_session.commit()
    assert aa.analysis_progress(db_session) == {"analyzed": 2, "total": 3}


# ---------------------------------------------------------------------------
# admin endpoints
# ---------------------------------------------------------------------------
def test_admin_progress_endpoint(client, db_session, library):
    db_session.add(TrackAudioAnalysis(
        track_id=library["tracks"][0].id, analyzed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    resp = client.get("/api/admin/audio/progress")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"analyzed": 1, "total": 3, "pending": 2}


def test_admin_analyze_now_endpoint(client, library, monkeypatch):
    # The endpoint reports pending/total and asks the scheduler to start. The
    # scheduler isn't running under tests, so trigger is a no-op; we just assert
    # it was called and the response shape is right.
    from app import scheduler

    called = {"n": 0}
    monkeypatch.setattr(
        scheduler, "trigger_audio_analysis_now",
        lambda: called.__setitem__("n", called["n"] + 1),
    )
    resp = client.post("/api/admin/audio/analyze", json={})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "enqueued"
    assert body["total"] == 3
    assert body["pending"] == 3
    assert called["n"] == 1
