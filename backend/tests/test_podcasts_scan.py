"""The folder scan for the podcasts library kind."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.config import settings
from app.models.art import ArtOverride
from app.models.library import LibraryKind
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.podcast import Podcast, PodcastEpisode
from app.services import ffprobe, library_folders, scan_library, scan_status
from tests.podcast_helpers import make_episode, make_podcast


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _put(path: Path, size: int = 32) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


@pytest.fixture()
def tree(db_session, tmp_path, monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key", "tmdb_api_key"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    for k in ("movies", "tv", "music", "music_videos"):
        monkeypatch.setattr(settings, f"library_root_{k}", "")
    root = tmp_path / "podcasts"
    one = root / "Show One"
    _put(one / "2025-01-05 Pilot.mp3")
    _put(one / "2025-01-12 Second.mp3")
    (one / "cover.jpg").write_bytes(_jpeg())
    two = root / "Show Two"
    plain = _put(two / "episode_a.mp3")
    os.utime(plain, (datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp(),) * 2)
    _put(root / "Downloaded Show" / "2025-02-01 Downloaded Ep.mp3")
    library_folders.save(db_session, {"podcasts": [str(root)]})
    # The synthetic user that owns scanner art (the 0017 migration seeds it).
    from app.models.user import User
    from app.services.art import SYSTEM_USER_ID
    db_session.add(User(id=SYSTEM_USER_ID, username="system", display_name="System",
                        password_hash="!", role="system", is_active=False))
    db_session.commit()

    tags = {
        str(one / "2025-01-05 Pilot.mp3"): {"album": ["Show One Official"], "title": ["Pilot"], "date": ["2025-01-05"]},
        str(one / "2025-01-12 Second.mp3"): {"album": ["Show One Official"], "title": ["The Second"], "date": ["2025-01-12"]},
    }
    monkeypatch.setattr(scan_library, "read_tags", lambda p: tags.get(p, {}))
    monkeypatch.setattr(scan_library, "embedded_cover", lambda p: None)

    def fake_probe(path, timeout=30.0):
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(container="mp3", size_bytes=os.path.getsize(path), duration_sec=60,
                                   bitrate_kbps=64, video_codec=None, audio_codec="mp3",
                                   audio_channels=2, width=None, height=None)

    monkeypatch.setattr(ffprobe, "probe", fake_probe)
    return root


def _counts(db):
    return (
        db.scalar(select(func.count()).select_from(Podcast)),
        db.scalar(select(func.count()).select_from(PodcastEpisode)),
        db.scalar(select(func.count()).select_from(MediaFile).where(MediaFile.kind == MediaKind.podcast_episode)),
    )


def test_podcasts_is_a_library_kind_with_its_own_folders(db_session, tree):
    assert LibraryKind.podcasts.value == "podcasts"
    assert "podcasts" in library_folders.KINDS
    assert library_folders.folders(db_session, "podcasts") == [str(tree)]
    assert scan_library.podcasts_enabled(db_session) is True


def test_local_scan_builds_shows_and_episodes_from_the_tree(db_session, tree):
    stats = scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    shows = {p.title: p for p in db_session.scalars(select(Podcast))}
    assert set(shows) == {"Show One Official", "Show Two", "Downloaded Show"}
    assert all(p.source == "local" and p.feed_url is None for p in shows.values())
    assert shows["Show One Official"].folder_path == str(tree / "Show One")

    one = db_session.scalars(
        select(PodcastEpisode).where(PodcastEpisode.podcast_id == shows["Show One Official"].id)
        .order_by(PodcastEpisode.published_at)
    ).all()
    assert [e.title for e in one] == ["Pilot", "The Second"]
    assert one[0].published_at.date().isoformat() == "2025-01-05"
    assert one[0].duration_sec == 60 and one[0].media_file_id

    # No tags: title from the file name, date from mtime.
    (ep_a,) = db_session.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == shows["Show Two"].id)).all()
    assert ep_a.title == "episode_a" and ep_a.published_at.date().isoformat() == "2024-06-01"
    # No tags: date from the leading YYYY-MM-DD in the file name.
    (dled,) = db_session.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == shows["Downloaded Show"].id)).all()
    assert dled.title == "Downloaded Ep" and dled.published_at.date().isoformat() == "2025-02-01"

    assert _counts(db_session) == (3, 4, 4)
    assert stats.podcast_episodes == 4 and stats.podcasts == 3


def test_cover_jpg_becomes_the_show_art_and_a_rescan_changes_nothing(db_session, tree):
    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    show = db_session.scalars(select(Podcast).where(Podcast.title == "Show One Official")).one()
    art = db_session.get(ArtOverride, ("podcast", show.id, "cover"))
    assert art is not None and art.source_kind == "local"
    before = _counts(db_session)
    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    assert _counts(db_session) == before


def test_a_file_already_linked_to_a_download_is_not_duplicated(db_session, tree):
    path = tree / "Downloaded Show" / "2025-02-01 Downloaded Ep.mp3"
    pod = make_podcast(db_session, title="Downloaded Show", feed_url="https://feed.example/rss",
                       folder_path=str(tree / "Downloaded Show"))
    ep = make_episode(db_session, pod, title="Downloaded Ep")
    mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(path), scan_state=ScanState.ready, size_bytes=32)
    db_session.add(mf)
    db_session.flush()
    ep.media_file_id, ep.downloaded_by_f7five0 = mf.id, True
    db_session.commit()

    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    eps = db_session.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == pod.id)).all()
    assert [e.id for e in eps] == [ep.id], "the download is matched by path, not added again"
    assert db_session.get(PodcastEpisode, ep.id).downloaded_by_f7five0 is True
    assert db_session.scalar(select(func.count()).select_from(MediaFile).where(MediaFile.path == str(path))) == 1
    assert db_session.scalar(select(func.count()).select_from(Podcast).where(Podcast.title == "Downloaded Show")) == 1


def test_a_folder_named_like_a_feed_shows_folder_joins_that_show(db_session, tree):
    # The feed show's folder_path was recorded on another path form (drive vs UNC).
    pod = make_podcast(db_session, title="Show Two (feed title)", feed_url="https://two.example/rss",
                       folder_path=r"\\nas\media\podcasts\Show Two")
    db_session.commit()
    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    eps = db_session.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == pod.id)).all()
    assert [e.title for e in eps] == ["episode_a"]
    assert db_session.scalar(select(func.count()).select_from(Podcast).where(Podcast.title == "Show Two")) == 0


def test_a_removed_file_is_marked_missing_not_deleted(db_session, tree):
    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    (tree / "Show Two" / "episode_a.mp3").unlink()
    scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    mf = db_session.scalar(select(MediaFile).where(MediaFile.path == str(tree / "Show Two" / "episode_a.mp3")))
    assert mf is not None and mf.scan_state.value == "missing"


def test_one_bad_file_does_not_stop_the_library(db_session, tree, monkeypatch):
    real = scan_library.read_tags

    def flaky(path):
        if path.endswith("Second.mp3"):
            raise RuntimeError("tag reader fell over")
        return real(path)

    monkeypatch.setattr(scan_library, "read_tags", flaky)
    stats = scan_library.scan_all(db_session, only=["podcasts"])
    db_session.commit()
    assert stats.errors >= 1
    assert db_session.scalar(select(func.count()).select_from(PodcastEpisode)) >= 3


def test_scan_reports_status_for_the_podcasts_library(db_session, tree):
    seen = []

    def progress(label, state, stats, err=None):
        seen.append((label, state, stats.podcast_episodes))
        scan_status.set_library(db_session, label, state, stats, err)

    scan_status.begin(db_session, force=True, only=["podcasts"])
    scan_library.scan_all(db_session, on_progress=progress, only=["podcasts"])
    scan_status.finish(db_session)
    db_session.commit()
    status = scan_status.read(db_session)
    assert status["libraries"]["podcasts"]["state"] == "done"
    assert status["libraries"]["podcasts"]["added"] == 4
    assert {s[0] for s in seen} == {"podcasts"}
    assert seen[0][1] == "running" and seen[-1][1] == "done"


def test_podcasts_folders_are_stream_roots(db_session, tree):
    from app.stream import _allowed_roots
    norm = {os.path.normcase(str(p)) for p in _allowed_roots(db_session)}
    assert os.path.normcase(str(tree)) in norm
