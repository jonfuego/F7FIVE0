F7FIVE0 PRIVACY POLICY
======================

F7FIVE0 is a media server you run on your own Windows PC. Your library, your
accounts, your watch history and your settings stay on that PC. There is no
F7FIVE0 account, no telemetry, no analytics, no ads and no crash reporting.
Nobody who works on F7FIVE0 can see what you have or what you play.

This program does not send information to other systems unless the person who
installs or runs it asks for it. The rest of this page lists every outside
service F7FIVE0 can talk to, what it sends, and how to turn it off.


WHAT THE SERVER CONTACTS
------------------------

Library details and pictures. When F7FIVE0 finds a movie, show, album or
artist, it looks up its details and artwork. These requests carry the title,
artist name, year, or an ID from that service, plus your server's internet
address. They never carry your name, your users, or what anyone watched.

  - TMDB (themoviedb.org): movies and shows. Only when you enter a TMDB key.
  - MusicBrainz (musicbrainz.org) and Cover Art Archive: music details and
    album covers. If you give a contact email in Setup, it is sent with these
    requests, as MusicBrainz asks.
  - Wikidata and Wikipedia: artist biographies.
  - TheAudioDB, Deezer and iTunes: artist pictures, and search results in the
    art picker. Deezer and iTunes turn off with DEEZER_ENABLED=false and
    ITUNES_ENABLED=false; the background artist picture fill turns off with
    ARTIST_ART_AUTOFILL_ENABLED=false.
  - Radarr, Sonarr and Lidarr: only the ones you connect, at the address you
    give.

Podcasts. Only the podcasts you follow or search for. F7FIVE0 fetches the
feeds and episodes from the publishers, and search goes to Podcast Index (if
you enter a key) or Apple's podcast search. A publisher sees your server's
internet address, the same as any podcast app. Your phone and browser never
contact a publisher directly; the server relays the audio.

Updates. Once a day the server asks GitHub (api.github.com) whether a newer
F7FIVE0 release is out. Nothing is sent except the request itself. Clear
"Check GitHub for updates" in Setup, or set UPDATE_CHECK_ENABLED=false in the
settings file (.env), to stop it; Admin > Updates > Check now still works when
you click it. Updating is always your choice: nothing installs itself.

Remote access. Only if you set it up in Admin > Remote access, and only the
method you pick:

  - Tailscale or Cloudflare: the tunnel runs through that company's network.
  - Your own domain with HTTPS (Caddy): Caddy gets the HTTPS certificate from
    a free certificate authority (Let's Encrypt, or ZeroSSL as a backup),
    which learns your web address and, if you gave a contact email in Setup,
    that email. Setup also asks ipify (api.ipify.org) once for your home
    internet address, to check that your name points at it.
  - DuckDNS: learns your home internet address so it can point your name at
    it, and the server refreshes it every 5 minutes.

Setting up a method downloads its program (Tailscale from tailscale.com,
cloudflared and Caddy from GitHub), each checked against a fixed checksum.
Each service is covered by that company's own privacy policy.

Downloads during Setup. Setup downloads Python, Node.js, FFmpeg, PostgreSQL
and NSSM from their publishers (api.nuget.org for Python, nodejs.org, GitHub,
get.enterprisedb.com and nssm.cc), and Microsoft's Visual C++ runtime from
download.visualstudio.microsoft.com when the PC does not have it. Each file is
checked against a fixed checksum before it is used.


WHAT YOUR BROWSER OR PHONE CONTACTS
-----------------------------------

  - Your F7FIVE0 server, at the address you use.
  - Chromecast: the web app loads Google's Cast library (www.gstatic.com) and
    the Android app includes it, so the Cast button works, and a Chromecast
    loads Google's media receiver when you cast. This is how every
    Cast-enabled app works.
  - Cast and crew photos on a movie page load from TMDB (image.tmdb.org).
  - Pictures in the Admin art picker load from the service that offered them,
    so an admin's browser contacts that service while the picker is open.

Fonts and the app's own images are served by your F7FIVE0 server.


THIRD-PARTY POLICIES
--------------------

Each service above has its own privacy policy: TMDB, MusicBrainz (MetaBrainz
Foundation), Wikimedia, TheAudioDB, Deezer, Apple, Podcast Index, GitHub,
Google, Tailscale, Cloudflare, DuckDNS, Let's Encrypt, ZeroSSL and ipify.


QUESTIONS
---------

Open an issue at https://github.com/jonfuego/F7FIVE0/issues.
