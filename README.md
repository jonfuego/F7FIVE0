<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/f7five0_banner-dark_v1.svg">
    <img src="docs/readme/f7five0_banner-light_v1.svg" width="100%" alt="F7FIVE0">
  </picture>
</p>

<p align="center">
  <b>Your movies, TV, music, music videos, and podcasts. Your server. Every screen.</b><br>
  A free, self-hosted media server for Windows.
</p>

<p align="center">
  <a href="../../releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/jonfuego/F7FIVE0?style=flat-square&label=release&labelColor=000000&color=9C0404"></a>
  <a href="../../releases"><img alt="Setup downloads" src="https://img.shields.io/github/downloads/jonfuego/F7FIVE0/latest/F7FIVE0-Setup-1.0.18.exe?style=flat-square&label=Setup%20downloads&labelColor=000000&color=333333"></a>
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/server-Windows%2010%20%7C%2011-333333?style=flat-square&labelColor=000000">
  <img alt="Android, Android TV, Android Auto" src="https://img.shields.io/badge/app-Android%20%7C%20TV%20%7C%20Auto-333333?style=flat-square&labelColor=000000">
  <a href="LICENSE"><img alt="License: Unlicense" src="https://img.shields.io/badge/license-Unlicense-333333?style=flat-square&labelColor=000000"></a>
</p>

<p align="center">
  <a href="../../releases/latest"><b>Download</b></a> ·
  <a href="INSTALL.md">Install guide</a> ·
  <a href="#features">Features</a> ·
  <a href="#updating">Updating</a> ·
  <a href="#for-developers">For developers</a>
</p>

---

F7FIVE0 runs on a Windows PC and streams your own media to any browser, your
phone, and your TV. It's built for one household plus the friends and family
you invite.

No subscription. No ads. No account with anyone but you.

<!-- Screenshots: drop PNGs into docs/screenshots/ with these names, then remove
     this comment's opening and closing lines to show the section.
## Screenshots

<p align="center">
  <img src="docs/screenshots/web-home.png" width="100%" alt="Home in the web app">
</p>

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/web-detail.png" alt="A movie's detail page"></td>
    <td width="50%"><img src="docs/screenshots/tv-home.png" alt="Home on Android TV"></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshots/phone-home.png" width="260" alt="Home on the phone app"></td>
    <td align="center"><img src="docs/screenshots/phone-now-playing.png" width="260" alt="Now playing on the phone app"></td>
  </tr>
</table>
-->

## Quick start

> **You need:** Windows 10 or 11 (64-bit) and a folder of media.

1. **Download** `F7FIVE0-Setup-x.y.z.exe` from [Releases](../../releases/latest).
2. **Run it.** Pick your media folders and set an admin password. Setup
   installs everything else. Allow 5 to 15 minutes on a fresh PC. Setup is
   not code-signed yet: if Windows says "Windows protected your PC", choose
   **More info**, then **Run anyway**.
3. **Open** <http://localhost:3001> and sign in.

Your library fills in over the next few minutes and stays up to date on its
own. Your Account page has a QR code to open F7FIVE0 on your phone.

Want to watch away from home? See [Remote access](#remote-access).

## Features

| Feature | What you get |
|---|---|
| **Movies and TV** | Continue Watching, On Deck, next episode, skip intro and credits |
| **Music** | Gapless playback, loudness leveling, lyrics, artist radio, mixes, a queue that follows you between devices |
| **Music videos** | Organized by artist and release |
| **Podcasts** | Search and follow shows (or import an OPML list), stream, download to the server or your phone, chapters, speed, skip back 15 and forward 30 seconds, and pick up where you left off on any device |
| **Plays anywhere** | Streams files as-is when your device can play them, converts them on the fly when it can't (uses an NVIDIA GPU if you have one) |
| **Web app** | Installs like an app on phones and desktops, with Chromecast |
| **Android app** | Phone, Android TV, and Android Auto, with downloads for offline play |
| **Private by design** | You create every account. There's no public sign-up. Passkeys supported. |
| **Artwork and details** | From your own folders, plus TMDB and MusicBrainz if you want them |
| **NAS friendly** | Library folders can live on a network share |
| **Radarr, Sonarr, Lidarr** | Optional. Connect them to manage the library and let people request titles |

## Organizing your media

F7FIVE0 reads the same folder layout as Plex and Jellyfin:

```
Movies\The Matrix (1999)\The Matrix (1999).mkv
TV\Some Show (2020)\Season 01\Some Show - S01E01 - Pilot.mkv
Music\Artist\Album (2001)\01 - Song.flac
Music Videos\Artist\Release\01 - Video.mp4
Podcasts\Show name\2025-01-05 Episode title.mp3
```

Artwork next to your files (`poster.jpg`, `fanart.jpg`, `cover.jpg`) is
picked up automatically. Add a free TMDB key in **Admin > Metadata** to fill
in anything missing.

## Remote access

Go to **Admin > Remote access** and pick one. All are free, and all use HTTPS.

| Option | Best for | You need |
|---|---|---|
| **Tailscale** (recommended) | Most people | A Google, Microsoft, Apple, or GitHub sign-in |
| **Cloudflare** | People who own a domain | A domain on Cloudflare |
| **Port forwarding** (advanced) | Router tinkerers | Router access, plus a domain or a free DuckDNS name |

Details in [INSTALL.md](INSTALL.md#listening-from-anywhere).

## Updating

Open **Admin > Updates**. F7FIVE0 checks for new releases once a day, and the
Admin link shows a badge when one is ready. Click **Update** and it:

1. Verifies the download against the release checksums
2. Backs up your database
3. Installs the new version
4. Checks that everything came back up, and **rolls back** if it didn't

Your settings, accounts, and watch history are kept. Updating the server also
updates the phone app it hands out. More in [INSTALL.md](INSTALL.md#updating).

## Help

[INSTALL.md](INSTALL.md) covers:

- [Other devices at home](INSTALL.md#using-it-from-other-devices-at-home)
- [Media on a NAS or network drive](INSTALL.md#media-on-a-nas-or-network-drive)
- [The Android app](INSTALL.md#the-android-app)
- [Adding people](INSTALL.md#adding-people) and [passkeys](INSTALL.md#passkeys)
- [Backups](INSTALL.md#backups)
- [Troubleshooting](INSTALL.md#troubleshooting)

## For developers

<details>
<summary><b>What's in the repo</b></summary>

| Folder | What | Stack |
|---|---|---|
| `backend/` | API and stream gateway | Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL |
| `frontend/` | Web app | Next.js 16, React 19, TypeScript, Tailwind |
| `mobile/` | Android phone, TV, and Auto app | Expo SDK 54, React Native (tvOS fork) |
| `installer/` | Setup.exe and install scripts | PowerShell 5.1, Inno Setup 6 |
| `scripts/` | Dev helpers, deploy from source, backups | PowerShell |
| `design/` | Design tokens and logos | Exported from the F7FIVE0 design system |

</details>

<details>
<summary><b>Build, run, and test</b></summary>

**Install from a clone** (elevated PowerShell, repo root). Builds the web app
and installs to `C:\F7FIVE0`:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
```

**Build Setup.exe** (needs Node.js and Inno Setup 6). Pushing a `v*` tag does
the same on GitHub Actions and attaches it to a release:

```powershell
.\installer\build-dist.ps1 -Version 1.0.0
```

**Develop:**

```powershell
.\scripts\dev-backend.ps1
.\scripts\dev-frontend.ps1
```

See [backend/README.md](backend/README.md) and [mobile/README.md](mobile/README.md).

**Test:**

```powershell
cd backend; python -m pytest
cd frontend; npm run build; npm run lint
cd mobile; npm run typecheck; npm test
```

</details>

<details>
<summary><b>How it fits together</b></summary>

Three Windows services start with Windows:

| Service | Address | Does |
|---|---|---|
| **F7FIVE0-Web** | port 3001 | The web app and the single front door. Forwards `/api` and `/stream`, so you only expose one port. |
| **F7FIVE0-API** | 127.0.0.1:8001 | Accounts, library, metadata, scanning |
| **F7FIVE0-Stream** | 127.0.0.1:8002 | Signed media URLs, direct play, HLS transcoding with ffmpeg |

Settings live in `C:\F7FIVE0\.env` (every key is explained in
[.env.example](.env.example)). Logs are in `C:\F7FIVE0\logs`.

</details>

## License

Public domain under [The Unlicense](LICENSE). Do whatever you want with it.
