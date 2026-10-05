"""Central settings. Loaded from .env at process start."""
import base64
import re
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (backend/app/config.py -> repo root).
# Anchor the .env path so it resolves the same whether the process is started
# from the repo root, backend/, or as a Windows service with its own CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _REPO_ROOT / ".env"
# Default home for runtime data (art, metadata cache, transcode cache) when
# the matching .env keys are not set. The installer points these at the
# data folder chosen during setup.
_DATA_ROOT = _REPO_ROOT / "data"

# Public project URL. Used as the contact in outbound User-Agent strings
# (MusicBrainz requires one) when no operator email is configured.
PROJECT_URL = "https://github.com/F7FIVE0/F7FIVE0"

# SHA-256 fingerprint of the certificate that signs official F7FIVE0 APKs
# (release key made 2026-10-04; scripts/release-apk.ps1 prints it as "Release
# cert SHA-256"). Passkeys trust the official app on every server by default.
# A self-signed build adds its own cert with WEBAUTHN_ANDROID_CERT_SHA256.
OFFICIAL_ANDROID_CERT_SHA256 = (
    "88:D0:1C:22:D1:48:EF:AB:79:F4:2E:15:A2:3E:62:7F:"
    "56:D9:E5:1C:64:DE:FC:A1:8E:4A:97:B9:27:85:A0:F7"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str

    # Auth
    jwt_secret: str
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    stream_hmac_secret: str
    stream_url_ttl_hours: int = 8

    # WebAuthn / passkeys. Passkeys only work over HTTPS, so they are on only
    # when an RP id resolves: WEBAUTHN_RP_ID if set, otherwise the host of an
    # https PUBLIC_URL. A home-only install (plain http on the LAN) has no
    # passkeys; password sign-in always works. Passkeys are bound to the RP
    # id, so changing the public address orphans existing passkeys.
    #
    # WEBAUTHN_ORIGINS: comma list of accepted web origins. Blank means
    # https://<rp id>. Entries already in `android:apk-key-hash:` form are
    # accepted as-is.
    # WEBAUTHN_ANDROID_CERT_SHA256: comma list of SHA-256 fingerprints (hex,
    # colons optional, as printed by keytool or scripts/release-apk.ps1) of the
    # certificates that sign the F7FIVE0 app (`webauthn_android_package`).
    # Each one becomes an accepted `android:apk-key-hash:` origin and an
    # assetlinks.json entry. Blank means the official release certificate.
    # WEBAUTHN_EXTRA_ANDROID_APPS: other Android apps allowed to use this
    # server's passkeys, as `package=FINGERPRINT[|FINGERPRINT]` pairs separated
    # by semicolons (for example a self-built fork, or an older app during a
    # switchover).
    webauthn_rp_id: str = ""
    webauthn_origins: str = ""
    webauthn_android_package: str = "com.f7five0.app"
    webauthn_android_cert_sha256: str = ""
    webauthn_extra_android_apps: str = ""
    # Passkey relying-party display name (shown by the platform prompt).
    webauthn_rp_name: str = "F7FIVE0"
    # Challenge lifetime. A registration/authentication ceremony must complete
    # within this many seconds; challenges are single-use and live in the DB.
    webauthn_challenge_ttl_seconds: int = 300

    # Minimum supported native app version per platform, surfaced by
    # GET /api/client/min-version so an older build shows an "update required"
    # screen instead of failing unpredictably. Read from .env keys
    # MIN_CLIENT_VERSION_ANDROID / _IOS / _ANDROID_TV / _TVOS. Default 0.0.0
    # means "no floor" (every build passes) until the operator raises it.
    min_client_version_android: str = "0.0.0"
    min_client_version_ios: str = "0.0.0"
    min_client_version_android_tv: str = "0.0.0"
    min_client_version_tvos: str = "0.0.0"

    # *arr (all optional). Leave an API key blank to disable that integration;
    # the matching library is then scanned straight off LIBRARY_ROOT_*.
    radarr_url: str = "http://127.0.0.1:7878"
    radarr_api_key: str = ""
    sonarr_url: str = "http://127.0.0.1:8989"
    sonarr_api_key: str = ""
    lidarr_url: str = "http://127.0.0.1:8686"
    lidarr_api_key: str = ""
    arr_webhook_secret: str = ""

    # Request flow: where approved requests get added in Radarr / Sonarr.
    # Get the real profile ids from each *arr: GET /api/v3/qualityprofile.
    # Root folders must match an existing root configured in the *arr.
    # Approve fails loudly (422) if the relevant pair is unset, so a
    # misconfigured deploy can't silently drop a request on the floor.
    radarr_quality_profile_id: int = 0
    radarr_root_folder: str = ""
    sonarr_quality_profile_id: int = 0
    sonarr_root_folder: str = ""

    # External art sources. Used by the Edit-art modal's Search tab as
    # fallbacks when the *arr stack returns no usable candidates.
    # iTunes Search API needs no key. TMDB requires a free v3 API key;
    # leaving it blank disables the TMDB source cleanly. TheAudioDB
    # accepts the public test key "2" for low-volume personal use; bump
    # to a paid key (Patreon supporters get one) if rate-limited.
    itunes_enabled: bool = True
    tmdb_api_key: str = ""
    audiodb_api_key: str = "2"

    # Transcoder
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    transcode_cache_dir: Path = _DATA_ROOT / "transcode-cache"
    transcode_cache_max_gb: int = 200
    # NVIDIA hardware encoding. The installer turns this on only when it
    # detects an NVIDIA GPU; ffmpeg falls back to libx264 when off.
    nvenc_enabled: bool = False

    # Offline download of non-direct-play video needs a server-side MP4
    # (H.264/AAC) transcode. That is an unbounded ffmpeg job on the request
    # path, so it is OFF by default: the download route returns 409
    # not_available_offline for such files until an operator opts in. Audio and
    # already-direct-playable video download the original regardless of this
    # flag. See app/api/media_files.py and transcoder.build_download_mp4.
    download_transcode_enabled: bool = False

    # Admin art overrides. One image per (entity, role) lives under this
    # root at <kind>/<uuid>/<role>.<ext>.
    art_root: Path = _DATA_ROOT / "art"

    # Throttle between art downloads during a full *arr sync. Lidarr,
    # Radarr, and Sonarr's metadata CDNs (and their upstream sources like
    # images.lidarr.audio) will rate-limit a tight loop. 200ms is gentle
    # enough that a full backfill of ~2000 entities still finishes in a
    # few minutes. Webhook-triggered single-entity syncs ignore this.
    art_download_delay_ms: int = 200

    # External metadata enrichment (TMDB / MusicBrainz / Wikipedia).
    # `tmdb_api_key` lives above with the other external art sources.
    # MusicBrainz requires a contact in the User-Agent per their ToS. Set
    # this to an email you read; when blank the project URL is used.
    # The disk cache lives next to the art root so backups scoop both.
    musicbrainz_user_agent_email: str = ""
    metadata_ttl_days: int = 30
    metadata_cache_root: Path = _DATA_ROOT / "metadata-cache"

    # Library folders. Blank means "not configured". Several folders per
    # library are separated by `;` (D:\Movies;\\nas\media\Movies). UNC
    # paths work as long as the service account can read them. Once folders
    # are saved in Admin > Library folders, the database is used instead of
    # these keys (app/services/library_folders.py).
    library_root_movies: str = ""
    library_root_tv: str = ""
    library_root_music: str = ""
    library_root_music_videos: str = ""

    # How often the folder scanner walks libraries that have no *arr
    # (see app/services/scan_library.py). The walk is incremental: only new
    # or changed files are probed.
    folder_scan_interval_minutes: int = 30

    # Stream Gateway path allow-list.
    # Semicolon-delimited list of absolute paths that media_files.path values
    # are allowed to live under. Defense-in-depth on top of HMAC signing and
    # the DB lookup: if a signed URL somehow points at an unexpected path,
    # the gateway refuses to read it. Empty string disables the check.
    # Example:
    #   STREAM_ALLOWED_ROOTS=D:\\Media;\\\\nas\\media
    stream_allowed_roots: str = ""

    # Path rewriting at sync ingress.
    # Semicolon-delimited pairs of `SRC=DST`. Used to translate *arr-reported
    # drive letters (mapped only in user sessions) to UNC paths that service
    # accounts can resolve. See app/services/path_map.py.
    # Example: `N:=\\nas\media` rewrites `N:\Movies\...` to
    # `\\nas\media\Movies\...`.
    path_rewrite_rules: str = ""

    # Address people use away from home (Tailscale Funnel or Cloudflare
    # Tunnel), written by setup. Shown on the Account page as a QR code.
    public_url: str = ""

    # Address on the home network, stamped into Android app downloads next to
    # PUBLIC_URL. Blank: http://<this machine's LAN IP>:<WEB_PORT>.
    home_url: str = ""

    # Folder setup copies the official Android APK into. The download is
    # stamped with this server's addresses. Blank: <install folder>/data/downloads.
    f7five0_downloads_dir: str = ""

    # Ports
    api_port: int = 8001
    stream_port: int = 8002
    web_port: int = 3001

    # Admin > Remote access. The web app hands requests to a SYSTEM scheduled
    # task through files in this folder (installer/remote-access.ps1). Blank
    # means <install folder>/data/remote-access.
    remote_access_dir: str = ""
    remote_access_task: str = "F7FIVE0-RemoteAccess"

    # Cloudflare
    cloudflare_tunnel_name: str = "f7five0"
    cloudflare_tunnel_uuid: str = ""

    # ---- WebAuthn derived values -------------------------------------------
    @property
    def webauthn_rp_id_effective(self) -> str:
        """The RP id passkeys are scoped to, or "" when passkeys are off."""
        explicit = self.webauthn_rp_id.strip().lower()
        if explicit:
            return explicit
        parsed = urlsplit(self.public_url.strip())
        if parsed.scheme == "https" and parsed.hostname:
            return parsed.hostname.lower()
        return ""

    @property
    def passkeys_enabled(self) -> bool:
        return bool(self.webauthn_rp_id_effective)

    @property
    def webauthn_android_apps(self) -> list[tuple[str, list[str]]]:
        """(package, [fingerprint as AA:BB:..]) for every Android app that may
        use this server's passkeys. Invalid fingerprints are skipped."""
        apps: list[tuple[str, list[str]]] = []
        # Blank (including a blank line in .env) means the official cert.
        own_raw = self.webauthn_android_cert_sha256.strip() or OFFICIAL_ANDROID_CERT_SHA256
        own = [f for f in (_norm_fp(x) for x in own_raw.split(",")) if f]
        package = self.webauthn_android_package.strip() or "com.f7five0.app"
        if own:
            apps.append((package, own))
        for pair in self.webauthn_extra_android_apps.split(";"):
            if "=" not in pair:
                continue
            pkg, fps = pair.split("=", 1)
            certs = [f for f in (_norm_fp(x) for x in fps.split("|")) if f]
            if pkg.strip() and certs:
                apps.append((pkg.strip(), certs))
        return apps

    @property
    def webauthn_origins_list(self) -> list[str]:
        """Origins accepted in clientDataJSON: the web origin(s) plus one
        `android:apk-key-hash:` origin per allowed app certificate."""
        rp = self.webauthn_rp_id_effective
        if not rp:
            return []
        origins = [o.strip().rstrip("/") for o in self.webauthn_origins.split(",") if o.strip()]
        if not any(not o.startswith("android:") for o in origins):
            origins.insert(0, _web_origin(rp, self.public_url))
        for _pkg, certs in self.webauthn_android_apps:
            for fp in certs:
                origins.append(apk_key_hash_origin(fp))
        seen: set[str] = set()
        return [o for o in origins if not (o in seen or seen.add(o))]


def _norm_fp(value: str) -> str:
    """Normalize a SHA-256 fingerprint to upper-case colon form, or ""."""
    hexs = re.sub(r"[^0-9A-Fa-f]", "", value or "")
    if len(hexs) != 64:
        return ""
    hexs = hexs.upper()
    return ":".join(hexs[i:i + 2] for i in range(0, 64, 2))


def apk_key_hash_origin(fingerprint: str) -> str:
    """`android:apk-key-hash:<base64url, no padding, of the raw SHA-256>`."""
    raw = bytes.fromhex(fingerprint.replace(":", ""))
    return "android:apk-key-hash:" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _web_origin(rp_id: str, public_url: str) -> str:
    """https://<rp id>, keeping PUBLIC_URL's port when its host is the RP id."""
    parsed = urlsplit(public_url.strip())
    if parsed.hostname and parsed.hostname.lower() == rp_id and parsed.port and parsed.port != 443:
        return f"https://{rp_id}:{parsed.port}"
    return f"https://{rp_id}"


settings = Settings()
