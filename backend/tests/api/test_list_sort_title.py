"""The movie and series lists carry `sort_title`, so the phone app's on-device
Title sort can use the admin's override the way the server order does."""
from __future__ import annotations

import uuid

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie


def test_movie_list_carries_sort_title(client, db_session):
    m = Movie(title="The Abyss", sort_title="Abyss, The")
    plain = Movie(title="Accepted")
    db_session.add_all([m, plain])
    db_session.flush()
    for movie in (m, plain):
        db_session.add(MediaFile(
            kind=MediaKind.movie, ref_id=movie.id,
            path=f"/movies/{uuid.uuid4().hex}.mkv", scan_state=ScanState.ready,
        ))
    db_session.commit()

    r = client.get("/api/movies")
    assert r.status_code == 200
    by_title = {row["title"]: row for row in r.json()}
    assert by_title["The Abyss"]["sort_title"] == "Abyss, The"
    assert by_title["Accepted"]["sort_title"] is None


def test_series_list_has_sort_title_field(client, db_session):
    r = client.get("/api/series")
    assert r.status_code == 200
    from app.api.schemas import SeriesOut
    assert "sort_title" in SeriesOut.model_fields
