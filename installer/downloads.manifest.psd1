# F7FIVE0 pinned installer downloads (SEC-P0-2).
#
# Every file Setup downloads by a direct URL is pinned here to an exact
# version, an immutable download URL (never a "latest" or rolling URL), and
# the expected SHA-256. install.ps1 and remote-access.ps1 read this file with
# Import-PowerShellDataFile and pass Url + Sha256 to the Download helper in
# common.ps1, which refuses any file whose hash does not match.
#
# Signed binaries also carry Publisher: the expected Authenticode subject
# (matched as a substring of Get-AuthenticodeSignature's SignerCertificate
# Subject). A blank or missing Publisher means "no Authenticode check" (the
# file is a zip or an unsigned binary; the SHA-256 is the guarantee).
#
# To bump a pinned version, see "Refreshing a pinned download" in CLAUDE.md.
# ASCII only. PowerShell 5.1 compatible.
@{
    node = @{
        Name      = "Node.js (win-x64 zip)"
        Version   = "22.14.0"
        Url       = "https://nodejs.org/dist/v22.14.0/node-v22.14.0-win-x64.zip"
        Sha256    = "55B639295920B219BB2ACBCFA00F90393A2789095B7323F79475C9F34795F217"
        Publisher = ""
    }
    ffmpeg = @{
        # 8.1.1 is the newest gyan.dev build whose NVENC works on the 580 driver
        # branch (GeForce 10-series stays there). 8.1.2 and 9.x need driver 610+.
        # Tested on a GTX 1060, driver 582.28, 2026-10-26. gyan.dev keeps only the
        # latest patch, so the URL is GyanD's tagged GitHub release of the same build.
        Name      = "FFmpeg (gyan.dev essentials build)"
        Version   = "8.1.1"
        Url       = "https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-essentials_build.zip"
        Sha256    = "6F58CE889F59C311410F7D2B18895B33C03456463486F3B1EBC93D97A0F54541"
        Publisher = ""
    }
    cloudflared = @{
        Name      = "cloudflared (windows amd64)"
        Version   = "2026.10.0"
        Url       = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.0/cloudflared-windows-amd64.exe"
        Sha256    = "86AEE4017B26625CEE8484C113558F48EFFA4CD47F7AA05FCF425604E5D2B23C"
        Publisher = "CN=`"Cloudflare, Inc.`""
    }
    caddy = @{
        Name      = "Caddy (windows amd64 zip)"
        Version   = "2.11.7"
        Url       = "https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_windows_amd64.zip"
        Sha256    = "0A1EDC0B799512051C57071CE0E798D3F2CF67DC98171366F1D2B326072E3B06"
        Publisher = ""
    }
    tailscale = @{
        Name      = "Tailscale (windows amd64 MSI)"
        Version   = "1.102.4"
        Url       = "https://pkgs.tailscale.com/stable/tailscale-setup-1.102.4-amd64.msi"
        Sha256    = "80EB007E39DFEBE17299FA1A09C79A8E1D934F76E0246C0817EBE3AF675B7EF6"
        Publisher = "CN=Tailscale Inc."
    }
}
