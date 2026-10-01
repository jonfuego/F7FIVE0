# Installing F7FIVE0

## What you need

- A Windows 10 (1809 or newer) or Windows 11 PC, 64-bit, that stays on
  while people are watching.
- About 2 GB of free disk for F7FIVE0 and its tools, plus room for the
  transcode cache (it trims itself to 200 GB by default; change
  `TRANSCODE_CACHE_MAX_GB` in `.env`).
- An internet connection during setup.
- Optional: an NVIDIA graphics card. Setup turns on hardware transcoding
  when it finds one. Without one, the CPU handles it, which is fine for a
  couple of streams at once.

## Install with Setup.exe

1. Download the latest **F7FIVE0-Setup-x.y.z.exe** from Releases and run it.
   Windows may warn that the app is from an unknown publisher; choose
   **More info > Run anyway**.
2. Pick an install folder (default `C:\F7FIVE0`).
3. Point it at your media folders. Leave any you don't have blank.
4. Create your admin account.
5. Choose whether other devices on your home network can connect.
6. Choose how to listen from anywhere: Tailscale, Cloudflare, port
   forwarding, or home network only (compared below).
7. Optional extras: a TMDB API key and a contact email. Both can be added
   later.

When you click Install, a console window shows progress while Setup
installs Python 3.12, PostgreSQL 16, Node.js, ffmpeg, and NSSM, creates the
database, and starts the three F7FIVE0 services. Then open
**http://localhost:3001**.

Setup is safe to run again. If something fails, fix what the message says
and rerun it; it picks up where it stopped. The full log is in
`C:\F7FIVE0\logs\install-*.log`.

## Using it from other devices at home

If you ticked "Let phones, TVs, and other computers on my home network
connect", browse to `http://<this-PC's-IP>:3001` from any device. Setup
prints the address at the end.

Can't connect? Windows only opens the port on networks marked **Private**.
Open **Settings > Network & internet**, pick your connection, and set the
network profile to Private.

The web app can be installed like an app (Add to Home Screen, or the install
icon in the browser's address bar) once you reach it over HTTPS, which the
remote access options below provide.

## Listening from anywhere

Setup offers three free ways to reach F7FIVE0 away from home. Pick one on
the "Listen from anywhere" page (or later, see the end of this section).
Your Account page then shows the address with a QR code for your phone.

| | Tailscale (recommended) | Cloudflare | Port forwarding (advanced) |
|---|---|---|---|
| Cost | Free | Free (a domain costs about $10/yr if you don't have one) | Free (DuckDNS names are free) |
| You need | A Google, Microsoft, Apple, or GitHub sign-in | A domain already on Cloudflare | Router access, plus a domain or DuckDNS name |
| Router changes | None | None | Forward ports 80 and 443 |
| Address | `https://f7five0.<tailnet>.ts.net` | `https://music.yourdomain.com` | `https://music.yourdomain.com` or `https://myname.duckdns.org` |
| Speed | **Bandwidth-limited by Tailscale.** Great for music and a video stream or two; high-bitrate video or several viewers at once may buffer. | No cap from F7FIVE0. Cloudflare's free-plan terms discourage using it mainly for heavy video. | Your full home upload speed. |
| Traffic passes through | Tailscale's relays | Cloudflare's network | Nobody: straight to your PC |
| Exposure | Only F7FIVE0, via Tailscale | Only F7FIVE0, via Cloudflare | Ports 80/443 on your PC are open to the internet |

**Tailscale.** Setup installs Tailscale and opens a browser to sign in
(creating the free account if you're new). It then turns on Tailscale Funnel.
The first time, Tailscale asks you to allow Funnel for your account; click
the button it shows.

**Cloudflare.** Tell Setup the address you want, such as
`music.yourdomain.com`. A browser opens: sign in, click your domain, and
**Authorize**. Setup creates the tunnel, the DNS record, and an
`F7FIVE0-Tunnel` service.

**Port forwarding (advanced).** For people comfortable with their router.
Setup installs Caddy as the `F7FIVE0-Proxy` service, which gets and renews a
free HTTPS certificate (Let's Encrypt) for your address, and opens ports 80
and 443 in Windows Firewall. You then:

1. Point your address at your home. With your own domain, create an A record
   for your home's public IP (Setup prints it). With DuckDNS, create a free
   name at duckdns.org and give Setup the token; a scheduled task
   (`F7FIVE0-DuckDNS`) keeps it pointed at your home when your IP changes.
2. In your router, reserve a fixed IP for this PC and forward **TCP 80** and
   **TCP 443** to it. Setup prints the exact IP.

Caddy keeps retrying until the certificate works, so it's fine to do the
router step after Setup finishes. Port 80 is only used to prove you own the
name and to redirect to HTTPS; nothing is ever served unencrypted. If your
internet provider blocks ports 80/443 or uses carrier-grade NAT (common on
cellular and some fiber plans), port forwarding can't work; use Tailscale or
Cloudflare instead.

Add or change remote access later from an elevated PowerShell:

```powershell
cd C:\F7FIVE0
.\installer\install.ps1 -RemoteAccess tailscale
.\installer\install.ps1 -RemoteAccess cloudflare -PublicHost music.yourdomain.com
.\installer\install.ps1 -RemoteAccess portforward -PublicHost myname.duckdns.org -DuckDnsToken <token>
```

Already made a tunnel in the Cloudflare dashboard? Pass its token instead
(`-TunnelToken <token> -PublicHost music.yourdomain.com`) and point the
tunnel's public hostname at `http://localhost:3001`.

## Media on a NAS or network drive

The services run as the built-in SYSTEM account, which can't sign in to
network shares. To use `\\nas\media` paths:

1. Use UNC paths (`\\nas\media\Movies`), not mapped drive letters, for
   your media folders.
2. Make the services run as a Windows account that can open the share
   (save the share's credentials for that account first). From an elevated
   PowerShell:

   ```powershell
   cd C:\F7FIVE0
   .\installer\install.ps1 -ServiceUser ".\youraccount"
   ```

   It asks for that account's password and re-registers the services under
   it. Your settings and data are untouched. (You can also change **Log On** for each
   F7FIVE0 service in `services.msc`.)

## Already have PostgreSQL?

Setup reuses it. It asks for the `postgres` account's password once, creates
a separate `f7five0` database and user, and never stores the `postgres`
password. If you've lost that password, reset it by following PostgreSQL's
documentation for `pg_hba.conf` "trust" mode, then run Setup again.

## Optional integrations

All of these go in `C:\F7FIVE0\.env`. Restart the services afterward:

```powershell
Restart-Service F7FIVE0-API, F7FIVE0-Stream, F7FIVE0-Web
```

- **TMDB** (`TMDB_API_KEY`): free key from themoviedb.org. Matches movies
  and shows by title and year and adds posters, descriptions, and cast.
- **MusicBrainz** (`MUSICBRAINZ_USER_AGENT_EMAIL`): your email, sent with
  music lookups as MusicBrainz asks.
- **Radarr / Sonarr / Lidarr** (`RADARR_API_KEY`, `SONARR_API_KEY`,
  `LIDARR_API_KEY`, plus the `_URL` keys): when an API key is set, that app
  owns the matching library instead of the folder scanner. Radarr and
  Sonarr also switch on **Requests**. Set `RADARR_QUALITY_PROFILE_ID`,
  `RADARR_ROOT_FOLDER`, `SONARR_QUALITY_PROFILE_ID`, and
  `SONARR_ROOT_FOLDER` so approved requests land in the right place. For
  instant updates, add a Webhook connection in each app pointing at
  `http://<this-PC>:3001/api/webhooks/<radarr|sonarr|lidarr>` with the
  header `X-Arr-Webhook-Token: <ARR_WEBHOOK_SECRET>` (Lidarr: put the secret
  in the Password field instead).

## The Android app

The app works with any F7FIVE0 server: on first launch, enter the same
address you use in a browser (for example `192.168.1.20:3001` or
`media.yourdomain.com`).

To offer the app to your users, put an APK in `C:\F7FIVE0\data\downloads`.
Everyone then sees a **Download for Android** button on their Account page.
See [mobile/README.md](mobile/README.md) for building the APK.

## Ports

F7FIVE0 uses three ports: the web port people connect to (3001 by default,
asked during setup) and two internal ones on 127.0.0.1 (API 8001, stream
8002). If the internal defaults are taken, setup picks the next free ones
(8101, 8102, ...). If the web port is taken, setup stops and names the
program using it, so pick another. Upgrades keep the ports saved in `.env`.

Running next to another media server on the same PC:

```powershell
.\installer\install.ps1 -WebPort 3101 -ApiPort 8101 -StreamPort 8102
```

## Passkeys

People can add a passkey (fingerprint, face, or device PIN) on their Account
page and sign in with it on the web and in the Android app. Passkeys need
HTTPS, so they turn on by themselves when your away-from-home address
(`PUBLIC_URL`) starts with `https://`. A home-only install has password
sign-in only. Password sign-in always keeps working.

A passkey belongs to one address. If you change `PUBLIC_URL`, existing
passkeys stop working and people add new ones.

If you build and sign the Android app yourself, put your signing
certificate's SHA-256 in `WEBAUTHN_ANDROID_CERT_SHA256` in `.env` so the app
can use passkeys (see `.env.example`).

## Adding people

Sign in as admin, open the gear menu, then **Admin** to create accounts. There's no public sign-up.

## Backups

F7FIVE0's own data is the database plus `C:\F7FIVE0\data\art` and
`C:\F7FIVE0\data\metadata-cache`. To back those up nightly, set
`BACKUP_DEST` in `.env` (a folder or `\\nas\share` path), then from an
elevated PowerShell in the install folder:

```powershell
cd C:\F7FIVE0
.\scripts\register-backup-task.ps1
```

## Updating

Run the newer Setup.exe. It stops the services, swaps in the new code,
applies database changes, and starts everything again. Your `.env`, data,
and watch history are kept.

## Uninstalling

Use **Settings > Apps > F7FIVE0 > Uninstall**. The services are removed;
your `.env` and `data\` folder are kept in case you reinstall. To remove
those and the database too:

```powershell
C:\F7FIVE0\installer\uninstall.ps1 -RemoveData
```

PostgreSQL and Python stay installed (other software may use them). Remove
them from Settings > Apps if you don't need them.

## Troubleshooting

| Symptom | Try |
|---|---|
| Browser can't reach localhost:3001 | `Get-Service F7FIVE0-*` should show three Running services. Check `C:\F7FIVE0\logs\F7FIVE0-Web.err.log`. |
| Sign-in page loads but sign-in fails | Check `F7FIVE0-API.err.log`. The API needs PostgreSQL running (`Get-Service postgresql*`). |
| Library stays empty | Check the folder paths in `.env`, then `F7FIVE0-API.err.log` for "folder scan". Scans run 30 seconds after start and every 30 minutes. Admins can also trigger a sync from the Admin page. |
| Network share shows nothing | See "Media on a NAS" above. SYSTEM can't read shares. |
| Remote address doesn't load (port forwarding) | Check `F7FIVE0-Proxy.err.log`. Most often the router rule is missing, the address points at the wrong IP, or the provider blocks ports 80/443. |
| Remote address buffers on video (Tailscale) | That's Funnel's bandwidth limit. Use a lower quality in the player, or switch to Cloudflare or port forwarding. |
| Other devices can't connect | Network profile must be Private; the port must match `WEB_PORT`. |
| Port 3001 already in use | Change `WEB_PORT` in `.env`, then rerun `installer\install.ps1` so the service and firewall rule follow. |
| Video stutters | Without an NVIDIA GPU, transcoding uses the CPU. Direct-playable files (H.264/AAC MP4) never transcode. |

Service logs rotate at 10 MB and live in `C:\F7FIVE0\logs`.

## Installing without the wizard

From an elevated PowerShell in an unzipped release (or a clone of the repo):

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
```

It asks the same questions as Setup. Useful switches: `-InstallDir`,
`-MoviesDir`, `-TvDir`, `-MusicDir`, `-MusicVideosDir`, `-WebPort`,
`-OpenFirewall 1`, `-RemoteAccess tailscale|cloudflare|portforward|none`,
`-PublicHost`, `-DuckDnsToken`,
`-TunnelToken`, `-TmdbKey`, `-ServiceUser`, `-NonInteractive`.
