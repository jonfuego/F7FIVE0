# Installing F7FIVE0

## What you need

- A Windows 10 (1809 or newer) or Windows 11 PC, 64-bit, that stays on
  while people are watching.
- About 2 GB of free disk for F7FIVE0 and its tools, plus room for the
  transcode cache (it trims itself to 200 GB by default; change
  `TRANSCODE_CACHE_MAX_GB` in `.env`).
- An internet connection during setup.
- An administrator account on that PC (Setup asks to run as administrator).
- winget (Microsoft's "App Installer"). It comes with Windows 10 and 11;
  some editions (LTSC, Server, or a trimmed image) leave it out. If Setup
  says "winget is not available", install **App Installer** from the
  Microsoft Store and run Setup again.
- Optional: an NVIDIA graphics card. Setup turns on hardware transcoding
  when it finds one. Without one, the CPU handles it, which is fine for a
  couple of streams at once.

## Install with Setup.exe

1. Download the latest **F7FIVE0-Setup-x.y.z.exe** from Releases and run it.
   That one file is all you need. The `.apk` on the release is the phone
   app (it installs on a phone, not on Windows) and the `.zip` is for
   "Installing without the wizard" below. Setup is not code-signed yet, so
   Windows may show "Windows protected your PC" or warn that the app is from
   an unknown publisher; choose **More info > Run anyway**.
2. Pick an install folder (default `C:\F7FIVE0`).
3. Point it at your media folders. Leave any you don't have blank. A library
   can use more than one folder: click **Add...** again for each one.
4. Create your admin account.
5. Choose whether other devices on your home network can connect.
6. Optional extras: a TMDB API key (there's a link to get a free one) and a
   contact email. Both can be added later: the TMDB key in **Admin >
   Metadata**, which walks you through getting one.
7. Ports: keep the defaults unless another program already uses port 3001.

When you click Install, a console window shows progress while Setup
installs Python 3.12, PostgreSQL 16, Node.js, ffmpeg, and NSSM, creates the
database, and starts the three F7FIVE0 services. PostgreSQL is the slow
part (often 5-10 minutes); the window prints the elapsed time while it
works. The last page shows your addresses, whether home network access is
on, and anything that still needs doing. Then open **http://localhost:3001**.

Setup installs F7FIVE0 for use at home. To use it away from home, sign in
and go to **Admin > Remote access** (below).

Setup is safe to run again. If something fails, fix what the message says
and rerun it; it picks up where it stopped. The full log is in
`C:\F7FIVE0\logs\install-*.log`.

## Using it from other devices at home

If you ticked "Let phones, TVs, and other computers on my home network
connect", browse to `http://<this-PC's-IP>:3001` from any device. Setup
prints the address at the end.

Can't connect? Windows only opens the port on networks marked **Private**.
Setup warns at the end if your network is marked Public. Open
**Settings > Network & internet**, pick your connection, and set the
network profile to Private.

Left the box unticked? Setup's last page says "Home network access: off".
Turn it on later from an elevated PowerShell:

```powershell
& C:\F7FIVE0\installer\install.ps1 -OpenFirewall 1
```

The web app can be installed like an app (Add to Home Screen, or the install
icon in the browser's address bar) once you reach it over HTTPS, which the
remote access options below provide.

## Listening from anywhere

Set this up after install, from the web app: sign in as an admin and go to
**Admin > Remote access**. It works from any browser on your home network,
so you can do it from your phone. Pick one of the free options below, and
stay on the page while it runs: Tailscale and Cloudflare show a **Sign in**
button you click to finish. Your Account page then shows the address with a
QR code for your phone. The same page shows whether the address works,
lets you switch to another option, and turns remote access off.

| | Tailscale (recommended) | Cloudflare | Port forwarding (advanced) |
|---|---|---|---|
| Cost | Free | Free (a domain costs about $10/yr if you don't have one) | Free (DuckDNS names are free) |
| You need | A Google, Microsoft, Apple, or GitHub sign-in | A domain already on Cloudflare | Router access, plus a domain or DuckDNS name |
| Router changes | None | None | Forward ports 80 and 443 |
| Address | `https://f7five0.<tailnet>.ts.net` | `https://music.yourdomain.com` | `https://music.yourdomain.com` or `https://myname.duckdns.org` |
| Speed | **Bandwidth-limited by Tailscale.** Great for music and a video stream or two; high-bitrate video or several viewers at once may buffer. | No cap from F7FIVE0. Cloudflare's free-plan terms discourage using it mainly for heavy video. | Your full home upload speed. |
| Traffic passes through | Tailscale's relays | Cloudflare's network | Nobody: straight to your PC |
| Exposure | Only F7FIVE0, via Tailscale | Only F7FIVE0, via Cloudflare | Ports 80/443 on your PC are open to the internet |

**Tailscale.** F7FIVE0 installs Tailscale, then shows **Sign in to
Tailscale** (this creates the free account if you're new). It then turns on
Tailscale Funnel. The first time, Tailscale asks you to allow Funnel for
your account; click the button it shows.

**Cloudflare.** Enter the address you want, such as
`music.yourdomain.com`. Click **Sign in to Cloudflare**, sign in, click
your domain, and **Authorize**. Cloudflare gives you about 9 minutes; the
page counts down. F7FIVE0 creates the tunnel, the DNS record, and an
`F7FIVE0-Tunnel` service.

**Port forwarding (advanced).** For people comfortable with their router.
F7FIVE0 installs Caddy as the `F7FIVE0-Proxy` service, which gets and
renews a free HTTPS certificate (Let's Encrypt) for your address, and opens
ports 80 and 443 in Windows Firewall. You then:

1. Point your address at your home. With your own domain, create an A record
   for your home's public IP (the page's Details show it). With DuckDNS,
   create a free name at duckdns.org and enter its token; a scheduled task
   (`F7FIVE0-DuckDNS`) keeps it pointed at your home when your IP changes.
2. In your router, reserve a fixed IP for this PC and forward **TCP 80** and
   **TCP 443** to it. The page's Details show the exact IP.

Caddy keeps retrying until the certificate works, so it's fine to do the
router step afterwards. Port 80 is only used to prove you own the name and
to redirect to HTTPS; nothing is ever served unencrypted. If your internet
provider blocks ports 80/443 or uses carrier-grade NAT (common on cellular
and some fiber plans), port forwarding can't work; use Tailscale or
Cloudflare instead.

**Cloudflare tunnel token (advanced).** Already made a tunnel in the
Cloudflare dashboard? Pick this option, enter the address and the token,
and point the tunnel's public hostname at `http://localhost:3001` in the
dashboard.

How it works: Setup registers a scheduled task, `F7FIVE0-RemoteAccess`,
that runs as SYSTEM only when an admin starts it from this page. The page
hands it the request through `C:\F7FIVE0\data\remote-access\` and shows its
progress. When it finishes, F7FIVE0 restarts its API and web app to use the
new address.

Advanced and recovery: the same steps run from an elevated PowerShell.
Stay at the screen for the sign-in.

```powershell
cd C:\F7FIVE0
.\installer\remote-access.ps1 -Method tailscale
.\installer\remote-access.ps1 -Method cloudflare -PublicHost music.yourdomain.com
.\installer\remote-access.ps1 -Method portforward -PublicHost myname.duckdns.org -DuckDnsToken <token>
.\installer\remote-access.ps1 -Method token -PublicHost music.yourdomain.com -TunnelToken <token>
.\installer\remote-access.ps1 -Method off
```

## Library folders

Each library (Movies, TV shows, Music, Music videos) can use one folder or
several, for example movies split across two drives plus a NAS share. Change
them any time in **Admin > Library folders**: add or remove folders, see
which ones the server can open, and save. A scan starts right away.

- TV shows and music merge across folders: a show with seasons on two drives
  is one show, an artist in two folders is one artist.
- Movies don't merge: the same movie in two folders shows up twice (for
  example a 4K copy and a 1080p copy), each with its own file.
- A folder that's offline (a NAS asleep, a drive unplugged) is skipped; its
  movies and episodes stay in the library until it's back.
- Removing a folder takes its items out of the library. Nothing is deleted
  from the disk, watch history is kept, and adding the folder back restores
  them.

Setup writes the folders to `LIBRARY_ROOT_MOVIES`, `LIBRARY_ROOT_TV`,
`LIBRARY_ROOT_MUSIC`, and `LIBRARY_ROOT_MUSIC_VIDEOS` in `.env`, separated by
`;`. Once you save from the Admin page, the server uses the saved list and
ignores those keys.

## Media on a NAS or network drive

The services run as the built-in SYSTEM account, which can't sign in to
network shares on its own. To use `\\nas\media` paths:

1. Use UNC paths (`\\nas\media\Movies`), not mapped drive letters, for
   your media folders.
2. Enter the NAS sign-in in **Admin > Library folders**. Any folder on a
   network share shows a **Sign in** button next to it. Type the NAS
   username (`user`, `DOMAIN\user`, or `user@domain`) and password and save.
   One sign-in covers every share and folder on that server. The password is
   encrypted on the server with Windows DPAPI; it never comes back to the
   browser and is never written to `.env`. The folders turn reachable right
   away, and they reconnect on their own after a reboot. To change it later,
   use **Change sign-in**; to clear it, **Remove sign-in**.

This is the easy path and leaves the services running as SYSTEM. If you would
rather run the services as a Windows account that can open the share (no
per-server sign-in needed, useful when many shares live on different servers),
from an elevated PowerShell:

```powershell
cd C:\F7FIVE0
.\installer\install.ps1 -ServiceUser ".\youraccount"
```

It asks for that account's password and re-registers the services under it.
Your settings and data are untouched. Use this rather than changing **Log On**
in `services.msc`: Setup also gives that account access to `.env`, `data\`,
and `logs\`, which a `services.msc` change does not.

## Folder permissions

The services run code from `C:\F7FIVE0`, so Setup locks it down: only
Administrators and SYSTEM can change anything there, other accounts can read
and run the program files, and `.env`, `data\`, and `logs\` are closed to
everyone except Administrators, SYSTEM, and the `-ServiceUser` account. Run
Setup (or `install.ps1`) from an elevated PowerShell to upgrade or repair.
If you run F7FIVE0 straight from a git clone in the install folder, `git pull`
needs an elevated prompt too.

## Already have PostgreSQL?

Setup reuses it. It asks for the `postgres` account's password once, creates
a separate `f7five0` database and user, and never stores the `postgres`
password. If you've lost that password, reset it by following PostgreSQL's
documentation for `pg_hba.conf` "trust" mode, then run Setup again.

When Setup installs PostgreSQL itself, it saves the `postgres` password in
`C:\F7FIVE0\data\postgres-superuser.txt` (readable by Administrators only)
before the install starts, so it survives a failed or interrupted run. Run
Setup again after a failed install and it reuses that saved password without
asking. If PostgreSQL has a different password than the one in that file,
Setup stops with "Could not sign in to PostgreSQL"; correct or delete the file
and run Setup again.

## Optional integrations

All of these go in `C:\F7FIVE0\.env`. Restart the services afterward:

```powershell
Restart-Service F7FIVE0-API, F7FIVE0-Stream, F7FIVE0-Web
```

- **TMDB** (`TMDB_API_KEY`): free key from themoviedb.org. Make an account at
  https://www.themoviedb.org/signup, then open Settings > API. (The API page
  itself needs a sign-in, so it fails if you open it signed out.) Matches movies
  and shows by title and year and adds posters, descriptions, and cast.
  Easier: paste it in **Admin > Metadata**, which tests it with TMDB and
  needs no restart (a key saved there wins over `.env`). Admins see a
  reminder banner until a key is set.
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

Setup includes the phone app that matches your server's version and puts it
in `C:\F7FIVE0\data\downloads`. Signed-in people see **Download for Android**
on their Account page (and in the gear menu).

Each download carries your server's addresses: the remote address from
Admin > Remote access, the address the person downloaded from, and your home
network address. On first launch the app fills in whichever one answers, so
people only type their username and password. If your PC has several
network adapters and the home address comes out wrong, set `HOME_URL` in
`.env` (for example `HOME_URL=http://192.168.1.20:3001`).

Upgrading the server also upgrades the app it hands out. After sign-in the
app offers **Update** when your server has a newer version; Account shows it
too. Installing the new download updates the app in place.

Releases that include a 32-bit build show a second link for older phones and
TV boxes. The app also works with any F7FIVE0 server when installed from
GitHub: enter the same address you use in a browser.

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

Sign in as an admin and open **Admin > Updates**. It shows the version that is
installed, the newest published version, and the phone app version that comes
with your server. F7FIVE0 checks GitHub once a day, and **Check now** asks
right away. When a newer version is waiting, the Admin link in the gear menu
shows an **Update** badge.

- **Update to vX.Y.Z** downloads the Setup from GitHub, checks it against the
  checksums published with the release, and installs it. A release that
  doesn't publish checksums can't be installed this way.
- **Upload a Setup** is for a Setup you downloaded yourself. It asks for your
  admin password again, and installs the file only if it is exactly a
  published F7FIVE0 release (this server checks that with GitHub, so it needs
  internet) or carries the F7FIVE0 signature (`UPDATE_SIGNER_SUBJECT` in
  `.env`). Releases aren't signed yet, so for now only the first way applies,
  and a Setup you built yourself is refused. Anything else is refused too.

Neither ever installs the same version again or an older one.

What happens: F7FIVE0 stops for a few minutes, the database is backed up to
`C:\F7FIVE0\data\updates\backup`, the new Setup runs, and the updater checks
that the new version answers (the API with the new version number, the
streaming service, and the web app). If it doesn't come up, the updater puts
the database back from the backup and runs the Setup of the version you had,
so you are never left with old code on a newer database. The page shows each
step and keeps working while the services restart. The logs are
`C:\F7FIVE0\logs\update-<id>.log` and `update-<id>-setup.log`. Your `.env`,
data, watch history, NAS sign-ins, and TMDB key are kept either way.

Phones: updating the server updates the phone app it hands out. Phones with
the older app are offered the new one the next time they sign in.

**The first time:** a server installed before this feature needs one run of
the newer Setup.exe by hand. That Setup adds the updater and keeps a copy of
itself, which a later update goes back to if it has to. After that, use
Admin > Updates.

You can always run the newer Setup.exe by hand instead. It stops the
services, swaps in the new code, applies database changes, and starts
everything again. Your `.env`, data, and watch history are kept.

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
| "Windows protected your PC" when starting Setup | Setup is not code-signed yet. Choose **More info**, then **Run anyway**. |
| Setup stops or its console window closes | Run Setup again; it picks up where it stopped. Read the last lines of the newest `C:\F7FIVE0\logs\install-*.log` (and `setup-summary.txt` if it exists): the message there says what failed. "winget is not available" means installing **App Installer** from the Microsoft Store first. |
| Setup looks frozen and the window title starts with "Select" | A click in the window started a text selection, which pauses Setup. Press **Esc**. To bring the window forward, click its title bar, not the text. (Setup 1.0.4 and later turn this off for their own window.) |
| The zip won't extract ("access denied") | Use Setup.exe instead; the zip is only for installing without the wizard. If you do need it, extract into a folder you own (Downloads or Desktop, not Program Files) and check your antivirus didn't quarantine a file from it. |
| The `.apk` won't install on Windows | It is the Android phone app. Put it on a phone, or sign in from the phone's browser and use **Account > Download for Android**. |
| Browser can't reach localhost:3001 | `Get-Service F7FIVE0-*` should show three Running services. Check `C:\F7FIVE0\logs\F7FIVE0-Web.err.log`. |
| Sign-in page loads but sign-in fails | Check `F7FIVE0-API.err.log`. The API needs PostgreSQL running (`Get-Service postgresql*`). |
| Library stays empty | Open **Admin > Library folders**. Each folder shows whether the server can open it. Under the folders, the **Folder scan** block shows whether a scan is running, which library it is on, how many files it has seen and added, when the last one finished, and the last error. Click **Scan folders now** to start one. Movies, TV and music appear as the scan finds them (it saves every 25 items), and an empty library page says your library is being scanned while it runs. Scans also run 30 seconds after start and every 30 minutes. If the block shows an error, or `F7FIVE0-API.err.log` has "folder scan" lines, that is where to look. |
| Network share shows nothing | See "Media on a NAS" above. SYSTEM can't read shares. |
| Admin > Updates says the updater isn't installed | Run the newer Setup.exe by hand once (it registers the `F7FIVE0-Update` task and keeps a copy of itself). |
| An update ended with "Went back to the old version" | The new version didn't pass its checks, so the old version and the database from before the update were restored. Open **Details** on the page, or `C:\F7FIVE0\logs\update-<id>.log` and `update-<id>-setup.log`, and tell whoever made the release. |
| Admin > Remote access says the helper isn't installed | Run Setup again (it registers the `F7FIVE0-RemoteAccess` task), or use `installer\remote-access.ps1` from an elevated PowerShell. |
| Remote access run failed | Open **Details** on the page, or `C:\F7FIVE0\data\remote-access\run.log`. |
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
`-OpenFirewall 1`, `-TmdbKey`, `-ServiceUser`, `-NonInteractive`.
`-RemoteAccess tailscale|cloudflare|portforward|token` (with `-PublicHost`,
`-DuckDnsToken`, `-TunnelToken`) also sets up remote access from the
console at the end of the install; most people use Admin > Remote access
instead.
