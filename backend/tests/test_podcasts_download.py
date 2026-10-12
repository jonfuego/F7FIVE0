"""Server downloads: .part then rename, Windows-safe names, the media row, the
no-folder answer, and the admin delete that only touches F7FIVE0's own files."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app import scheduler
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.podcast import PodcastEpisode
from app.services import ffprobe, library_folders, podcasts as _pkg  # noqa: F401
from app.services.podcasts import download as dl
from tests.podcast_helpers import (
    Api, install_dns, install_transport, make_episode, make_podcast, make_user, subscribe,
)

AUDIO = b"ID3" + b"\x00" * 600


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    install_dns(monkeypatch)
    monkeypatch.setattr(scheduler, "queue_podcast_download", lambda *a, **k: True)

    def fake_probe(path, timeout=30.0):
        return ffprobe.ProbeResult(
            container="mp3", size_bytes=os.path.getsize(path), duration_sec=123,
            bitrate_kbps=64, video_codec=None, audio_codec="mp3", audio_channels=2,
            width=None, height=None,
        )

    monkeypatch.setattr(ffprobe, "probe", fake_probe)


@pytest.fixture()
def api(db_session):
    a = Api(db_session)
    yield a
    a.close()


@pytest.fixture()
def pod_root(db_session, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    root = tmp_path / "podcasts"
    root.mkdir()
    library_folders.save(db_session, {"podcasts": [str(root)]})
    db_session.commit()
    return root


# ---------------------------------------------------------------------------
# Safe names
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    'Show: "The" <Best> | ?*', "CON", "con", "NUL.txt", "COM1", "LPT9", "Trailing dots...", "Trailing space   ",
    "a" * 400, "", "   ", "..", "back\\slash/and/fwd", "tab\tand\nnewline", "Ünïcödé – ok",
])
def test_safe_name_is_windows_safe(raw):
    name = dl.safe_name(raw, max_len=80)
    assert name and len(name) <= 80
    assert not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
    assert not name.endswith((" ", "."))
    assert name.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    assert name not in (".", "..")


def test_file_name_has_date_title_and_extension():
    ep = type("E", (), {"title": "Ep 1: Hello?", "published_at": datetime(2025, 3, 1, tzinfo=timezone.utc),
                        "enclosure_url": "https://cdn.example/a/b/file.m4a?x=1", "enclosure_type": "audio/mp4"})()
    name = dl.episode_file_name(ep)
    assert name.startswith("2025-03-01 Ep 1") and name.endswith(".m4a")
    ep.enclosure_url = "https://cdn.example/stream"
    ep.enclosure_type = "audio/mpeg"
    assert dl.episode_file_name(ep).endswith(".mp3")


# ---------------------------------------------------------------------------
# The download job
# ---------------------------------------------------------------------------
def test_download_writes_part_then_the_final_name_and_creates_the_media_row(db_session, pod_root, monkeypatch):
    pod = make_podcast(db_session, title='Weird: Show? "One"')
    ep = make_episode(db_session, pod, title="Ep 1: Hello", published=datetime(2025, 3, 1, tzinfo=timezone.utc))
    ep.enclosure_url = "https://cdn.example/ep1.mp3"
    seen: dict = {}

    def body():
        yield AUDIO[:300]
        seen["during"] = sorted(p.name for p in (pod_root / dl.safe_name(pod.title)).iterdir())
        yield AUDIO[300:]

    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=body()))
    mf = dl.download_episode(db_session, ep)
    db_session.commit()

    show_dir = pod_root / dl.safe_name(pod.title)
    final = show_dir / "2025-03-01 Ep 1 Hello.mp3"
    assert [n for n in seen["during"] if n.endswith(".part")], "bytes are streamed into a .part file first"
    assert final.is_file() and final.read_bytes() == AUDIO
    assert sorted(p.name for p in show_dir.iterdir()) == [final.name], "no .part left behind"
    assert mf.kind == MediaKind.podcast_episode and mf.ref_id == ep.id
    assert mf.path == str(final) and mf.size_bytes == len(AUDIO)
    assert mf.duration_sec == 123 and mf.scan_state == ScanState.ready
    assert ep.media_file_id == mf.id and ep.downloaded_by_f7five0 is True
    assert pod.folder_path == str(show_dir)


def test_a_failed_download_leaves_nothing_behind(db_session, pod_root, monkeypatch):
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod)
    install_transport(monkeypatch, lambda r: httpx.Response(500))
    with pytest.raises(dl.DownloadError):
        dl.download_episode(db_session, ep)
    assert list(pod_root.rglob("*.*")) == []
    assert ep.media_file_id is None and ep.downloaded_by_f7five0 is False


def test_a_download_that_is_not_audio_is_refused(db_session, pod_root, monkeypatch):
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod)
    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"))
    with pytest.raises(dl.DownloadError):
        dl.download_episode(db_session, ep)
    assert list(pod_root.rglob("*.*")) == []


def test_download_to_a_private_host_is_refused(db_session, pod_root, monkeypatch):
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod, enclosure_url="http://10.0.0.5/ep.mp3")
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg"}))
    with pytest.raises(dl.DownloadError):
        dl.download_episode(db_session, ep)
    assert len(calls) == 0


def test_download_uses_the_first_reachable_podcasts_folder(db_session, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    gone, here = tmp_path / "gone", tmp_path / "here"
    here.mkdir()
    library_folders.save(db_session, {"podcasts": [str(gone), str(here)]})
    db_session.commit()
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod)
    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=AUDIO))
    mf = dl.download_episode(db_session, ep)
    assert mf.path.startswith(str(here))


def test_second_download_of_the_same_episode_is_a_no_op(db_session, pod_root, monkeypatch):
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod)
    calls = install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=AUDIO))
    first = dl.download_episode(db_session, ep)
    second = dl.download_episode(db_session, ep)
    assert first.id == second.id and len(calls) == 1


# ---------------------------------------------------------------------------
# The endpoints
# ---------------------------------------------------------------------------
def test_download_without_a_podcasts_folder_answers_409(api, db_session):
    u = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod)
    subscribe(db_session, u, pod)
    r = api.as_user(u).post(f"/api/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 409 and r.json()["detail"] == "no_podcast_folder"


def test_download_endpoint_queues_for_a_subscriber_only(api, db_session, pod_root, monkeypatch):
    queued: list = []
    monkeypatch.setattr(scheduler, "queue_podcast_download", lambda eid: queued.append(eid) or True)
    a, b = make_user(db_session), make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod)
    subscribe(db_session, a, pod)
    r = api.as_user(b).post(f"/api/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 403 and r.json()["detail"] == "not_subscribed"
    assert queued == []
    r = api.as_user(a).post(f"/api/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 202 and queued == [ep.id]


def test_download_endpoint_says_so_when_the_file_is_already_there(api, db_session, pod_root, monkeypatch):
    queued: list = []
    monkeypatch.setattr(scheduler, "queue_podcast_download", lambda eid: queued.append(eid) or True)
    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=AUDIO))
    a = make_user(db_session)
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod)
    subscribe(db_session, a, pod)
    dl.download_episode(db_session, ep)
    db_session.commit()
    r = api.as_user(a).post(f"/api/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 200 and r.json()["already_downloaded"] is True and queued == []


# ---------------------------------------------------------------------------
# Admin delete
# ---------------------------------------------------------------------------
def test_admin_delete_removes_an_f7five0_download(api, db_session, pod_root, monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=AUDIO))
    admin = make_user(db_session, role="admin")
    pod = make_podcast(db_session, title="Show")
    ep = make_episode(db_session, pod)
    mf = dl.download_episode(db_session, ep)
    db_session.commit()
    path = mf.path
    assert os.path.exists(path)
    r = api.as_user(admin).delete(f"/api/admin/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 204
    assert not os.path.exists(path)
    assert db_session.get(PodcastEpisode, ep.id).media_file_id is None
    assert db_session.get(PodcastEpisode, ep.id).downloaded_by_f7five0 is False
    assert db_session.scalar(select(MediaFile).where(MediaFile.path == path)) is None


def test_admin_delete_refuses_files_f7five0_did_not_download(api, db_session, pod_root):
    admin = make_user(db_session, role="admin")
    pod = make_podcast(db_session, title="Mine", feed_url=None, source="local")
    ep = make_episode(db_session, pod, enclosure_url=None)
    f = pod_root / "Mine" / "own.mp3"
    f.parent.mkdir()
    f.write_bytes(AUDIO)
    mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(f), scan_state=ScanState.ready)
    db_session.add(mf)
    db_session.flush()
    ep.media_file_id = mf.id
    db_session.commit()
    r = api.as_user(admin).delete(f"/api/admin/podcasts/episodes/{ep.id}/download")
    assert r.status_code == 409
    assert f.exists() and db_session.get(PodcastEpisode, ep.id).media_file_id == mf.id
    # And an episode with no file at all.
    bare = make_episode(db_session, pod, enclosure_url=None)
    assert api.as_user(admin).delete(f"/api/admin/podcasts/episodes/{bare.id}/download").status_code == 409


def test_admin_delete_will_not_leave_the_library_roots(api, db_session, pod_root, tmp_path):
    admin = make_user(db_session, role="admin")
    pod = make_podcast(db_session)
    ep = make_episode(db_session, pod)
    outside = tmp_path / "elsewhere.mp3"
    outside.write_bytes(AUDIO)
    mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(outside), scan_state=ScanState.ready)
    db_session.add(mf)
    db_session.flush()
    ep.media_file_id, ep.downloaded_by_f7five0 = mf.id, True
    db_session.commit()
    r = api.as_user(admin).delete(f"/api/admin/podcasts/episodes/{ep.id}/download")
    assert r.status_code in (403, 409)
    assert outside.exists()
