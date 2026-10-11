"""Admin > Arr: save / clear / Test / pickers / webhook token. All HTTP is mocked
(httpx.MockTransport under the *arr clients); nothing here touches a network."""
from __future__ import annotations

import base64
import uuid

import httpx
import pytest

from app import scheduler
from app.config import settings
from app.services import arr_settings
from app.services.arr import _base

SECRET_KEY = "abcd1234efgh5678SECRET"


class FakeArr:
    """Stand-in for one *arr app, shared by the clients the endpoints build."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.system = {"appName": "Radarr", "version": "5.2.1.8"}
        self.profiles = [{"id": 4, "name": "HD-1080p"}, {"id": 6, "name": "Any"}]
        self.folders = [{"id": 1, "path": "D:\\Movies", "freeSpace": 1000}]
        self.unreachable = False
        self.html = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.unreachable:
            raise httpx.ConnectError("refused", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if self.html:
            return httpx.Response(200, text="<html>login</html>")
        path = request.url.path
        if path.endswith("/system/status"):
            return httpx.Response(200, json=self.system)
        if path.endswith("/qualityprofile"):
            return httpx.Response(200, json=self.profiles)
        if path.endswith("/rootfolder"):
            return httpx.Response(200, json=self.folders)
        return httpx.Response(404, json={})


@pytest.fixture()
def arr(monkeypatch):
    fake = FakeArr()
    real_client = httpx.Client

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(_base.httpx, "Client", make_client)
    for app in arr_settings.APPS:
        monkeypatch.setattr(settings, f"{app}_api_key", "")
    monkeypatch.setattr(settings, "arr_webhook_secret", "")
    monkeypatch.setattr(settings, "radarr_quality_profile_id", 0)
    monkeypatch.setattr(settings, "radarr_root_folder", "")
    synced = {"n": 0}
    monkeypatch.setattr(scheduler, "trigger_full_sync_now", lambda: synced.__setitem__("n", synced["n"] + 1))
    fake.synced = synced  # type: ignore[attr-defined]
    return fake


def _app(data: dict, name: str) -> dict:
    return next(a for a in data["apps"] if a["app"] == name)


def test_get_lists_all_three_apps_with_no_key(client, arr):
    r = client.get("/api/admin/arr")
    assert r.status_code == 200
    apps = {a["app"]: a for a in r.json()["apps"]}
    assert set(apps) == {"radarr", "sonarr", "lidarr"}
    assert apps["radarr"] == {
        "app": "radarr", "label": "Radarr", "configured": False, "key_source": None,
        "has_key": False, "masked": None, "url": "http://127.0.0.1:7878", "url_source": "env",
        "supports_requests": True, "quality_profile_id": None, "quality_profile_source": None,
        "root_folder": None, "root_folder_source": None,
    }
    assert apps["lidarr"]["supports_requests"] is False and apps["lidarr"]["quality_profile_id"] is None


def test_save_shows_masked_tail_never_the_key(client, arr):
    r = client.put("/api/admin/arr/radarr", json={
        "url": "http://nas:7878/", "api_key": SECRET_KEY, "quality_profile_id": 4, "root_folder": "D:\\Movies",
    })
    assert r.status_code == 200, r.text
    assert SECRET_KEY not in r.text
    radarr = _app(r.json(), "radarr")
    assert radarr["configured"] and radarr["key_source"] == "admin" and radarr["has_key"]
    assert radarr["masked"].endswith(SECRET_KEY[-4:]) and SECRET_KEY[:8] not in radarr["masked"]
    assert radarr["url"] == "http://nas:7878" and radarr["url_source"] == "admin"
    assert radarr["quality_profile_id"] == 4 and radarr["root_folder"] == "D:\\Movies"
    assert arr.synced["n"] == 1  # a key appeared: the library moves to the app now
    # Every other admin response is clean too.
    for path in ("/api/admin/arr", "/api/admin/arr/radarr/options"):
        assert SECRET_KEY not in client.get(path).text
    t = client.post("/api/admin/arr/radarr/test", json={})
    assert t.status_code == 200 and SECRET_KEY not in t.text


def test_blank_key_on_resave_keeps_the_saved_key(client, arr):
    client.put("/api/admin/arr/radarr", json={"api_key": SECRET_KEY})
    r = client.put("/api/admin/arr/radarr", json={"api_key": "", "root_folder": "E:\\Films"})
    radarr = _app(r.json(), "radarr")
    assert radarr["has_key"] and radarr["root_folder"] == "E:\\Films"
    assert arr_settings.api_key("radarr") == SECRET_KEY


def test_remove_key_falls_back_to_env(client, arr, monkeypatch):
    client.put("/api/admin/arr/sonarr", json={"api_key": SECRET_KEY})
    r = client.delete("/api/admin/arr/sonarr/key")
    assert r.status_code == 200 and not _app(r.json(), "sonarr")["configured"]
    monkeypatch.setattr(settings, "sonarr_api_key", "envkey")
    assert _app(client.get("/api/admin/arr").json(), "sonarr")["key_source"] == "env"
    client.put("/api/admin/arr/sonarr", json={"api_key": SECRET_KEY})
    r = client.delete("/api/admin/arr/sonarr")
    sonarr = _app(r.json(), "sonarr")
    assert sonarr["key_source"] == "env" and sonarr["url_source"] == "env"


def test_features_and_scan_guard_follow_a_saved_key_with_no_restart(client, arr, monkeypatch, tmp_path):
    from app.services import library_folders, scan_library
    monkeypatch.setattr(settings, "library_root_movies", str(tmp_path))
    monkeypatch.setattr(settings, "library_root_tv", "")
    assert client.get("/api/client/features").json()["arr"] == {"radarr": False, "sonarr": False, "lidarr": False}
    assert scan_library.movies_enabled()

    client.put("/api/admin/arr/radarr", json={"api_key": SECRET_KEY})
    feats = client.get("/api/client/features").json()
    assert feats["arr"]["radarr"] is True and feats["requests"]["movie"] is True
    assert not scan_library.movies_enabled() and library_folders.arr_managed("movies")

    client.delete("/api/admin/arr/radarr/key")
    assert client.get("/api/client/features").json()["arr"]["radarr"] is False
    assert scan_library.movies_enabled() and not library_folders.arr_managed("movies")


def test_bad_values_are_refused(client, arr):
    assert client.put("/api/admin/arr/radarr", json={"url": "nas:7878"}).status_code == 422
    assert client.put("/api/admin/arr/radarr", json={"url": "http://u:p@nas:7878"}).status_code == 422
    assert client.put("/api/admin/arr/lidarr", json={"root_folder": "D:\\Music"}).status_code == 422
    assert client.put("/api/admin/arr/bazarr", json={}).status_code == 422


# -- Test button ----------------------------------------------------------------
def test_test_ok_returns_version_and_pickers(client, arr):
    r = client.post("/api/admin/arr/radarr/test", json={"url": "http://nas:7878", "api_key": SECRET_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["version"] == "5.2.1.8" and "5.2.1.8" in body["message"]
    assert body["options"]["profiles"] == [{"id": 4, "name": "HD-1080p"}, {"id": 6, "name": "Any"}]
    assert body["options"]["root_folders"] == [{"path": "D:\\Movies", "free_space": 1000}]
    first = arr.calls[0]
    assert first.headers["x-api-key"] == SECRET_KEY and first.url.host == "nas"
    assert first.url.path == "/api/v3/system/status"
    # Nothing was saved by testing.
    assert not _app(client.get("/api/admin/arr").json(), "radarr")["has_key"]


def test_test_uses_the_saved_key_when_none_is_typed(client, arr):
    client.put("/api/admin/arr/radarr", json={"api_key": SECRET_KEY, "url": "http://saved:7878"})
    r = client.post("/api/admin/arr/radarr/test", json={})
    assert r.json()["ok"]
    assert arr.calls[-1].headers["x-api-key"] == SECRET_KEY and arr.calls[-1].url.host == "saved"


def test_test_wrong_key_says_so(client, arr):
    arr.status = 401
    r = client.post("/api/admin/arr/radarr/test", json={"api_key": "nope"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and "API key is wrong" in r.json()["message"]
    assert r.json()["options"] is None


def test_test_unreachable_says_so(client, arr):
    arr.unreachable = True
    r = client.post("/api/admin/arr/sonarr/test", json={"url": "http://nowhere:8989", "api_key": "k"})
    assert r.json()["ok"] is False and "Can't reach Sonarr" in r.json()["message"]


def test_test_wrong_app_or_not_an_arr(client, arr):
    arr.system = {"appName": "Sonarr", "version": "4.0.0"}
    r = client.post("/api/admin/arr/radarr/test", json={"api_key": "k"})
    assert not r.json()["ok"] and "Sonarr, not Radarr" in r.json()["message"]
    arr.system = {"appName": "Radarr", "version": "5.0"}
    arr.html = True
    r = client.post("/api/admin/arr/radarr/test", json={"api_key": "k"})
    assert not r.json()["ok"] and "does not look like Radarr" in r.json()["message"]
    arr.html, arr.status = False, 404
    assert "does not look like Radarr" in client.post("/api/admin/arr/radarr/test", json={"api_key": "k"}).json()["message"]


def test_test_needs_a_key_and_a_good_url(client, arr):
    r = client.post("/api/admin/arr/radarr/test", json={})
    assert not r.json()["ok"] and "API key" in r.json()["message"]
    r = client.post("/api/admin/arr/radarr/test", json={"url": "radarr", "api_key": "k"})
    assert not r.json()["ok"] and arr.calls == []


def test_lidarr_test_has_no_pickers(client, arr):
    arr.system = {"appName": "Lidarr", "version": "2.1"}
    r = client.post("/api/admin/arr/lidarr/test", json={"api_key": "k"})
    assert r.json()["ok"] and r.json()["options"] == {"profiles": [], "root_folders": [], "error": None}
    assert [c.url.path for c in arr.calls] == ["/api/v1/system/status"]


def test_options_from_the_saved_key(client, arr):
    r = client.get("/api/admin/arr/radarr/options")
    assert r.json()["profiles"] == [] and "No Radarr API key" in r.json()["error"]
    client.put("/api/admin/arr/radarr", json={"api_key": SECRET_KEY})
    r = client.get("/api/admin/arr/radarr/options")
    assert [p["id"] for p in r.json()["profiles"]] == [4, 6] and r.json()["root_folders"][0]["path"] == "D:\\Movies"
    arr.status = 401
    assert "API key is wrong" in client.get("/api/admin/arr/radarr/options").json()["error"]


# -- webhook token ----------------------------------------------------------------
def test_webhook_generate_and_rotate(client, arr, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://media.example.com")
    r = client.get("/api/admin/arr/webhook")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["has_token"] is False and r.json()["token"] is None
    assert r.json()["paths"] == {a: f"/api/webhooks/{a}" for a in ("radarr", "sonarr", "lidarr")}
    assert {"label": "Public address", "url": "https://media.example.com"} in r.json()["base_urls"]

    g = client.post("/api/admin/arr/webhook/generate", json={})
    assert g.status_code == 200 and g.json()["source"] == "admin"
    token = g.json()["token"]
    assert len(token) >= 32 and arr_settings.webhook_secret() == token

    again = client.post("/api/admin/arr/webhook/generate", json={})
    assert again.status_code == 409 and arr_settings.webhook_secret() == token
    rotated = client.post("/api/admin/arr/webhook/generate", json={"rotate": True})
    assert rotated.json()["token"] != token and arr_settings.webhook_secret() == rotated.json()["token"]


def test_webhook_save_custom_and_clear(client, arr, monkeypatch):
    assert client.put("/api/admin/arr/webhook", json={"token": "short"}).status_code == 422
    assert client.put("/api/admin/arr/webhook", json={"token": "has spaces in it 123456"}).status_code == 422
    r = client.put("/api/admin/arr/webhook", json={"token": "my-own-token-0123456789"})
    assert r.json()["token"] == "my-own-token-0123456789"
    monkeypatch.setattr(settings, "arr_webhook_secret", "envsecret-0123456789")
    r = client.delete("/api/admin/arr/webhook")
    assert r.json()["source"] == "env" and r.json()["token"] == "envsecret-0123456789"


def test_webhook_receiver_uses_the_saved_token(client, arr):
    body = {"eventType": "Test"}
    assert client.post("/api/webhooks/radarr", json=body).status_code == 503  # no token anywhere
    token = client.post("/api/admin/arr/webhook/generate", json={}).json()["token"]
    assert client.post("/api/webhooks/radarr", json=body, headers={"X-Arr-Webhook-Token": "wrong"}).status_code == 401
    ok = client.post("/api/webhooks/radarr", json=body, headers={"X-Arr-Webhook-Token": token})
    assert ok.status_code == 200 and ok.json()["refreshed"] is False
    basic = base64.b64encode(f"f7:{token}".encode()).decode()
    ok = client.post("/api/webhooks/lidarr", json=body, headers={"Authorization": f"Basic {basic}"})
    assert ok.status_code == 200


# -- admin only ------------------------------------------------------------------
def test_members_get_403_everywhere(client, arr, db_session):
    from app.api.deps import current_user, require_admin
    from app.main import app
    from app.models.user import User

    member = User(id=uuid.uuid4(), username="member", display_name="M", password_hash="x", role="member", is_active=True)
    db_session.add(member)
    db_session.flush()
    app.dependency_overrides.pop(require_admin, None)  # the real admin check runs again
    app.dependency_overrides[current_user] = lambda: member
    calls = [
        ("get", "/api/admin/arr", None),
        ("put", "/api/admin/arr/radarr", {"api_key": "k"}),
        ("delete", "/api/admin/arr/radarr/key", None),
        ("delete", "/api/admin/arr/radarr", None),
        ("post", "/api/admin/arr/radarr/test", {}),
        ("get", "/api/admin/arr/radarr/options", None),
        ("get", "/api/admin/arr/webhook", None),
        ("post", "/api/admin/arr/webhook/generate", {}),
        ("put", "/api/admin/arr/webhook", {"token": "x" * 20}),
        ("delete", "/api/admin/arr/webhook", None),
    ]
    for method, path, body in calls:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, path, r.status_code)
    assert arr.calls == [] and not arr_settings.configured("radarr")
