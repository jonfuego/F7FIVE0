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
    # Python is the official NuGet "python" package: a plain zip of a full
    # CPython (venv and pip included), unpacked into runtime\python like Node.
    # No installer, nothing installed for the whole PC, about 1 s to unpack.
    # The python.org installer it replaces took minutes and once sat on
    # winget's "Cancelling operation" for 29 minutes. The .nupkg itself carries
    # no Authenticode signature, so InnerPublisher is checked on InnerFile
    # (python.exe) after it is unpacked.
    python = @{
        Name           = "Python (NuGet python package, x64)"
        Version        = "3.12.10"
        Url            = "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"
        Sha256         = "0EB85C2DFCCCCF1B17352DE4C397F69194035B7D37149EACC16F1147D93DE3B8"
        Publisher      = ""
        InnerFile      = "python.exe"
        InnerPublisher = "Python Software Foundation"
    }
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
    # PostgreSQL and NSSM used to come through winget. Under `winget install
    # jonfuego.F7FIVE0` that deadlocked: winget runs one install at a time, so
    # Setup's own `winget install PostgreSQL...` waited forever for the outer
    # winget, which waited for Setup (FuegoTest VM, 1.0.22).
    #
    # PostgreSQL is EnterpriseDB's "binaries" zip of the same 16.16-2 build, not
    # its installer: the installer spent about 14 minutes unpacking itself
    # (pgAdmin, StackBuilder, docs) and 15 to 30 minutes in all. install.ps1
    # unpacks only pgsql/bin, pgsql/lib and pgsql/share (1,636 of 21,979 files,
    # about 2 s) into runtime\pgsql, runs initdb and registers F7FIVE0's own
    # database service. The zip is not Authenticode-signed; the SHA-256 is the
    # guarantee (checked against the downloaded file on 2026-11-22).
    postgresql = @{
        Name      = "PostgreSQL 16 (EnterpriseDB Windows binaries zip, x64)"
        Version   = "16.16-2"
        Url       = "https://get.enterprisedb.com/postgresql/postgresql-16.16-2-windows-x64-binaries.zip"
        Sha256    = "ADD1DE261B150E6923266ABEE293F05050795E73F5356158AEE4221A2170C073"
        Publisher = ""
    }
    # The Visual C++ runtime the PostgreSQL binaries need (msvcp140,
    # vcruntime140, vcruntime140_1); the EnterpriseDB installer used to install
    # it. The URL is the versioned download the winget-pkgs manifest for
    # Microsoft.VCRedist.2015+.x64 14.52.37029.0 pins. install.ps1 runs it only
    # when the runtime is missing or older than MinVersion.
    vcredist = @{
        Name       = "Microsoft Visual C++ 2015-2022 Redistributable (x64)"
        Version    = "14.52.37029.0"
        MinVersion = "14.40"
        Url        = "https://download.visualstudio.microsoft.com/download/pr/78d061c5-9ef3-42ab-98ed-3309d1095dc4/9C02C9ED120F671B900E6B9471D890E3B2414117A7E53F4AE2E855466FA2B7C9/VC_redist.x64.exe"
        Sha256     = "9C02C9ED120F671B900E6B9471D890E3B2414117A7E53F4AE2E855466FA2B7C9"
        Publisher  = "CN=Microsoft Corporation"
    }
    nssm = @{
        # Unsigned zip; the SHA-256 is the guarantee. install.ps1 copies only
        # win64\nssm.exe out of it.
        Name      = "NSSM (service wrapper, zip)"
        Version   = "2.24-101-g897c7ad"
        Url       = "https://nssm.cc/ci/nssm-2.24-101-g897c7ad.zip"
        Sha256    = "99F5045FFFBFFB745D67FE3A065A953C4A3D9C253B868892D9B685B0EE7D07B8"
        Publisher = ""
    }
}
