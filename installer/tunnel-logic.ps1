# Pure decisions for the Cloudflare tunnel step of remote-access.ps1.
#
# Nothing here runs cloudflared, touches the network, the registry, services,
# or files. remote-access.ps1 dot-sources this file and feeds it text it has
# already read; installer\tests\tunnel-logic.Tests.ps1 dot-sources it with
# canned text. Windows PowerShell 5.1 compatible, ASCII only.

# ---------------------------------------------------------------------------
# Tunnel name
# ---------------------------------------------------------------------------

# "f7five0-<computer name>": lowercase, letters digits and hyphens only, runs
# of anything else collapsed to one hyphen, hyphens trimmed, and the computer
# part cut at 40 characters so the whole name stays short.
function ConvertTo-TunnelName([string]$ComputerName) {
    $part = ([string]$ComputerName).ToLowerInvariant()
    $part = [regex]::Replace($part, '[^a-z0-9]+', '-').Trim('-')
    if ($part.Length -gt 40) { $part = $part.Substring(0, 40).Trim('-') }
    if (-not $part) { $part = "pc" }
    return "f7five0-$part"
}

# A name Setup will accept from .env or from an existing tunnel: what
# Cloudflare shows for tunnels made by hand (f7-main, f750) must pass.
function Test-TunnelNameValid([string]$Name) {
    return ([string]$Name) -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$'
}

# Which tunnel this install uses.
#   SavedName       CLOUDFLARE_TUNNEL_NAME from .env ("" when not there)
#   LocalTunnelName the name of the tunnel this install already runs, found
#                   from its own cloudflared\config.yml / tunnel.json and the
#                   account's tunnel list ("" when none)
#   ComputerName    $env:COMPUTERNAME
# Order: the saved name, then the tunnel the install already has, then a new
# per-computer name. An install keeps what it has: a rerun never renames a
# tunnel or creates a second one. Returns Name, Source (saved, existing, new)
# and Reason (a sentence for the run log).
function Get-TunnelNameDecision([string]$SavedName, [string]$LocalTunnelName, [string]$ComputerName) {
    $saved = ([string]$SavedName).Trim()
    $local = ([string]$LocalTunnelName).Trim()
    $skipped = ""
    if ($saved) {
        if (Test-TunnelNameValid $saved) {
            return [pscustomobject]@{
                Name = $saved; Source = "saved"
                Reason = "using the tunnel '$saved' saved for this install (CLOUDFLARE_TUNNEL_NAME in .env)"
            }
        }
        $skipped = " The saved name '$saved' is not a usable tunnel name, so it was ignored."
    }
    if ($local -and (Test-TunnelNameValid $local)) {
        return [pscustomobject]@{
            Name = $local; Source = "existing"
            Reason = "this install already runs the tunnel '$local'; keeping it.$skipped"
        }
    }
    $new = ConvertTo-TunnelName $ComputerName
    return [pscustomobject]@{
        Name = $new; Source = "new"
        Reason = "no tunnel saved for this install yet; using its own name '$new'.$skipped"
    }
}

# ---------------------------------------------------------------------------
# What this install already has (cloudflared\config.yml and tunnel.json)
# ---------------------------------------------------------------------------

# Ref is the config's "tunnel:" value, which cloudflared accepts as either the
# id or the name (a hand-made config may use the name). With no config line,
# the TunnelID inside the credentials file stands in. CredFile is the config's
# "credentials-file:" path, or "".
function Read-LocalTunnel([string]$ConfigText, [string]$CredText) {
    $ref = ""
    $credFile = ""
    foreach ($line in ([string]$ConfigText -split "`r?`n")) {
        if ($line -match '^\s*tunnel\s*:\s*(.*?)\s*$' -and -not $ref) { $ref = $matches[1].Trim('"', "'") }
        elseif ($line -match '^\s*credentials-file\s*:\s*(.*?)\s*$' -and -not $credFile) { $credFile = $matches[1].Trim('"', "'") }
    }
    if ($ref -match '^#') { $ref = "" }
    if (-not $ref) { $ref = Get-CredTunnelId $CredText }
    return [pscustomobject]@{ Ref = $ref; CredFile = $credFile }
}

# TunnelID out of a credentials file's text, or "".
function Get-CredTunnelId([string]$CredText) {
    if (-not ([string]$CredText).Trim()) { return "" }
    try {
        $j = $CredText | ConvertFrom-Json
        if ($j -and $j.TunnelID) { return ([string]$j.TunnelID).Trim().ToLowerInvariant() }
    } catch { }
    return ""
}

# ---------------------------------------------------------------------------
# Is the tunnel already running somewhere? (`cloudflared tunnel info <name>`)
# ---------------------------------------------------------------------------

# Reads the text of `cloudflared tunnel info`. Known shapes:
#   with connectors   a header row "CONNECTOR ID  CREATED  ARCHITECTURE ..."
#                     then one row per connector that starts with its UUID
#   none running      "Your tunnel <id> does not have any active connection."
#   --output json     an object listing "connectors" (or "conns" / "connections")
# The exact wording can change between cloudflared versions, so the rule is:
# a connector row, the connector header, or a non-empty JSON list is evidence
# of connectors (State "active"); a clear "no active connection" sentence or an
# empty JSON list is State "none"; anything else is "unknown", which Setup does
# NOT treat as in use because it has no evidence (it logs that it could not
# tell). Count is the number of connector rows seen.
function Get-TunnelConnectorState([string]$InfoText) {
    $text = ([string]$InfoText)
    $trim = $text.Trim()
    if ($trim.StartsWith("{") -or $trim.StartsWith("[")) {
        try {
            $j = $trim | ConvertFrom-Json
            if ($j -is [array]) { $j = $j | Select-Object -First 1 }
            foreach ($prop in @("connectors", "conns", "connections")) {
                if ($j.PSObject.Properties.Name -contains $prop) {
                    $n = @($j.$prop | Where-Object { $_ }).Count
                    if ($n -gt 0) { return [pscustomobject]@{ State = "active"; Count = $n } }
                    return [pscustomobject]@{ State = "none"; Count = 0 }
                }
            }
            # A tunnel with no connectors can leave the list out entirely.
            if ($j.PSObject.Properties.Name -contains "id") { return [pscustomobject]@{ State = "none"; Count = 0 } }
        } catch { }
        return [pscustomobject]@{ State = "unknown"; Count = 0 }
    }
    $rows = 0
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '^\s*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(\s|$)') { $rows++ }
    }
    if ($rows -gt 0) { return [pscustomobject]@{ State = "active"; Count = $rows } }
    if ($text -match '(?i)\bCONNECTOR\s+ID\b') { return [pscustomobject]@{ State = "active"; Count = 0 } }
    if ($text -match '(?i)(does not have any|no)\s+active\s+(connection|connector)') { return [pscustomobject]@{ State = "none"; Count = 0 } }
    return [pscustomobject]@{ State = "unknown"; Count = 0 }
}

# Decides whether Setup may fetch credentials for a tunnel that already
# exists on the account. InUse is true when it has active connectors and they
# are not this machine's own F7FIVE0-Tunnel service (OwnServiceRunsIt).
# Message is the text for the run log and Admin page when InUse; Note is a
# line for the run log when the answer was unclear.
function Get-TunnelUseDecision([string]$InfoText, [string]$TunnelName, [bool]$OwnServiceRunsIt) {
    $s = Get-TunnelConnectorState $InfoText
    $inUse = ($s.State -eq "active") -and -not $OwnServiceRunsIt
    $message = ""
    $note = ""
    if ($inUse) {
        $count = if ($s.Count -gt 0) { "$($s.Count) connector(s) are" } else { "connectors are" }
        $message = "The Cloudflare tunnel '$TunnelName' is already in use elsewhere ($count connected to it now), so F7FIVE0 did not take it over and fetched no credentials. " +
            "Joining it would split its traffic with whatever it already serves. " +
            "Pick another name: set CLOUDFLARE_TUNNEL_NAME=$TunnelName-2 (or any other new name) in the .env file in the F7FIVE0 install folder, then run Remote access again. " +
            "Or stop the other connector first."
    } elseif ($s.State -eq "unknown") {
        $note = "Could not tell from 'cloudflared tunnel info' whether '$TunnelName' has active connectors; there was no sign of any, so going on."
    }
    return [pscustomobject]@{ InUse = $inUse; State = $s.State; Count = $s.Count; Message = $message; Note = $note }
}

# ---------------------------------------------------------------------------
# Where does the DNS record point after `route dns`?
# ---------------------------------------------------------------------------

# True when two tunnel ids are the same tunnel. cloudflared messages and
# people shorten ids (431c14c2), so a prefix of 8 or more characters counts.
function Test-SameTunnelId([string]$A, [string]$B) {
    $x = ([string]$A).Replace("-", "").Trim().ToLowerInvariant()
    $y = ([string]$B).Replace("-", "").Trim().ToLowerInvariant()
    if ($x.Length -lt 8 -or $y.Length -lt 8) { return $false }
    return $x.StartsWith($y) -or $y.StartsWith($x)
}

# Reads what `cloudflared tunnel route dns` printed. Two lines matter:
#   "Added CNAME <host> which will route to this tunnel tunnelID=<id>"
#   "<host> is already configured to route to your tunnel tunnelID=<id>"
# The second one is printed with --overwrite-dns when the record was left
# pointing at whatever tunnel it already had, and the command still exits 0.
# State is ours (every id named is this tunnel), other (a different tunnel is
# named: OtherId), or unknown (neither line found).
function Test-RouteDnsOutput([string]$Output, [string]$TunnelId) {
    $found = @()
    $rx = '(?i)route\s+to\s+(?:your|this)\s+tunnel\s*[:=]?\s*(?:tunnelID\s*=\s*)?[''"]?([0-9a-f][0-9a-f-]{6,35})'
    foreach ($m in [regex]::Matches([string]$Output, $rx)) { $found += $m.Groups[1].Value }
    if ($found.Count -eq 0) { return [pscustomobject]@{ State = "unknown"; OtherId = "" } }
    foreach ($id in $found) {
        if (-not (Test-SameTunnelId $id $TunnelId)) { return [pscustomobject]@{ State = "other"; OtherId = $id } }
    }
    return [pscustomobject]@{ State = "ours"; OtherId = "" }
}

# Compares the CNAME target found for the hostname with this tunnel's
# "<id>.cfargotunnel.com". State: match, other (a different tunnel: OtherId),
# foreign (not a tunnel address at all), or missing (nothing was found).
function Compare-CnameTarget([string]$Target, [string]$TunnelId) {
    $t = ([string]$Target).Trim().ToLowerInvariant().TrimEnd('.')
    if (-not $t) { return [pscustomobject]@{ State = "missing"; OtherId = "" } }
    $want = (([string]$TunnelId).Trim().ToLowerInvariant()) + ".cfargotunnel.com"
    if ($t -eq $want) { return [pscustomobject]@{ State = "match"; OtherId = "" } }
    if ($t -match '^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.cfargotunnel\.com$') {
        return [pscustomobject]@{ State = "other"; OtherId = $matches[1] }
    }
    return [pscustomobject]@{ State = "foreign"; OtherId = "" }
}

# Combines both signals into one verdict.
#   ok       the record points at this tunnel (or cloudflared said so and
#            nothing contradicts it)
#   failed   it points somewhere else: Message says where and what to do
#   unknown  nothing could confirm it (a proxied record hides its CNAME from a
#            plain DNS lookup); Setup logs that and goes on
# Retryable is true for a verdict that only a lookup produced, which a stale
# DNS answer can cause, so Setup asks again for a short while.
function Get-RouteDnsVerdict([string]$RouteOutput, [string]$TunnelId, [string]$CnameTarget, [string]$HostName) {
    $out = Test-RouteDnsOutput $RouteOutput $TunnelId
    $cname = Compare-CnameTarget $CnameTarget $TunnelId
    $fix = "Open the Cloudflare dashboard, DNS, and delete or edit the record for $HostName so it is a CNAME to $TunnelId.cfargotunnel.com (or use another address), then run Remote access again."
    if ($out.State -eq "other") {
        return [pscustomobject]@{
            State = "failed"; Retryable = $false
            Message = "$HostName still points at another Cloudflare tunnel ($($out.OtherId)), not this one ($TunnelId). cloudflared said so and left the record alone. The tunnel service was not started. $fix"
        }
    }
    if ($cname.State -eq "other") {
        return [pscustomobject]@{
            State = "failed"; Retryable = $true
            Message = "$HostName still points at another Cloudflare tunnel ($($cname.OtherId).cfargotunnel.com), not this one ($TunnelId.cfargotunnel.com). The tunnel service was not started. $fix"
        }
    }
    if ($cname.State -eq "foreign") {
        return [pscustomobject]@{
            State = "failed"; Retryable = $true
            Message = "$HostName points at $(([string]$CnameTarget).Trim().TrimEnd('.')), not at this tunnel ($TunnelId.cfargotunnel.com). The tunnel service was not started. $fix"
        }
    }
    if ($cname.State -eq "match") {
        return [pscustomobject]@{ State = "ok"; Retryable = $false; Message = "$HostName points at this tunnel ($TunnelId.cfargotunnel.com)." }
    }
    if ($out.State -eq "ours") {
        return [pscustomobject]@{ State = "ok"; Retryable = $false; Message = "cloudflared reports $HostName routes to this tunnel ($TunnelId)." }
    }
    return [pscustomobject]@{
        State = "unknown"; Retryable = $true
        Message = "Could not confirm where $HostName points. If the site shows the wrong page, check its DNS record in the Cloudflare dashboard: it should be a CNAME to $TunnelId.cfargotunnel.com."
    }
}

# The account, zone and API token that `cloudflared tunnel login` stored in
# cert.pem (a base64 JSON block). Returns ZoneId, AccountId, ApiToken, or
# $null when the text is not a cert Setup understands. The token is returned
# to the caller only; nothing here prints or logs it.
function Read-OriginCertToken([string]$PemText) {
    $m = [regex]::Match([string]$PemText, '-----BEGIN ARGO TUNNEL TOKEN-----(.+?)-----END ARGO TUNNEL TOKEN-----', 'Singleline')
    if (-not $m.Success) { return $null }
    try {
        $b64 = ($m.Groups[1].Value -replace '\s', '')
        $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
        $j = $json | ConvertFrom-Json
        if (-not $j.zoneID -or -not $j.apiToken) { return $null }
        return [pscustomobject]@{ ZoneId = [string]$j.zoneID; AccountId = [string]$j.accountID; ApiToken = [string]$j.apiToken }
    } catch { return $null }
}
