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
        Name      = "FFmpeg (gyan.dev essentials build)"
        Version   = "9.0.2"
        Url       = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip"
        Sha256    = "60F467265B1E312373DBCD92200C2618A74850F98D3D078E94296BB3FA2047BA"
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
