# Pure decisions for the "map the drive letters your *arr apps use" step of
# install.ps1.
#
# Radarr, Sonarr and Lidarr often list files on a drive letter (N:\Movies) that
# is mapped only in one person's Windows login. The F7FIVE0 services run as a
# system account that has no N:, so those files look missing. Setup runs in the
# user's own login, where N: exists, so it can ask each *arr app for its root
# folders, find what each drive letter points at, and save the rewrite rule
# (PATH_REWRITE_RULES in .env, the rules the backend's path_map reads; the same
# rules Admin > Library folders > Path mappings shows, read-only, and merges
# under its own).
#
# Nothing in the decisions here touches the network, the registry, services or
# files: install.ps1 hands in what it has read (and the real providers for the
# drive map and the *arr call), and installer\tests\pathmap-logic.Tests.ps1 hands
# in canned values. The step never fails the install: every problem becomes a
# line in the log and the step moves on.
# Windows PowerShell 5.1 compatible, ASCII only.

# ---------------------------------------------------------------------------
# Paths and rules
# ---------------------------------------------------------------------------

# "N:" for a path that starts with a drive letter ("N:\Movies", "n:/TV"), else
# "". A UNC path, a relative path and "" give "".
function Get-DriveLetterOfPath([string]$Path) {
    $p = ([string]$Path).Trim()
    if ($p -match '^([A-Za-z]):([\\/]|$)') { return ($Matches[1].ToUpperInvariant() + ":") }
    return ""
}

function Test-UncPathText([string]$Path) {
    return ([string]$Path).Trim() -match '^\\\\[^\\/]+\\[^\\/]+'
}

# "N:=\\nas\media;M:=\\nas\music" as a list of objects with Src and Dst. Both
# sides lose trailing backslashes, so "N:" and "N:\" are the same rule. Empty
# or malformed pieces are dropped. Same reading as the backend's _parse_rules.
function ConvertFrom-RewriteRules([string]$Raw) {
    $rules = New-Object System.Collections.ArrayList
    foreach ($part in (([string]$Raw) -split ';')) {
        $part = $part.Trim()
        if (-not $part -or $part.IndexOf('=') -lt 0) { continue }
        $i = $part.IndexOf('=')
        $src = $part.Substring(0, $i).Trim().TrimEnd('\')
        $dst = $part.Substring($i + 1).Trim().TrimEnd('\')
        if (-not $src -or -not $dst) { continue }
        [void]$rules.Add([pscustomobject]@{ Src = $src; Dst = $dst })
    }
    return @($rules.ToArray())
}

function ConvertTo-RewriteRules($Rules) {
    return ((@($Rules) | ForEach-Object { "$($_.Src)=$($_.Dst)" }) -join ';')
}

# ---------------------------------------------------------------------------
# What each drive letter points at
# ---------------------------------------------------------------------------

# Lines of `net use` output -> @{ "N:" = "\\server\share" }. Only rows that have
# a local drive letter and a UNC remote name; "Unavailable" rows count (the
# connection is remembered, just not up right now).
function ConvertFrom-NetUseLines([string[]]$Lines) {
    $map = @{}
    foreach ($line in @($Lines)) {
        # The share name may hold a space (\\fuegonas\The Hive); the network name
        # that follows is separated from it by two or more spaces.
        if ($line -match '^\s*(?:OK|Disconnected|Unavailable|Reconnecting|Disconnect)?\s*([A-Za-z]:)\s+(\\\\.+?)(?:\s{2,}.*)?$') {
            $map[$Matches[1].ToUpperInvariant()] = $Matches[2].TrimEnd('\')
        }
    }
    return $map
}

# The drive letters this login has mapped, from three places, first answer wins
# for a letter:
#   Smb      Get-SmbMapping (LocalPath, RemotePath rows)
#   NetUse   `net use` text
#   Registry HKCU:\Network\<letter>\RemotePath (a remembered connection). An
#            elevated Setup does not always see the connections the same user
#            made in a normal window (UAC keeps them apart), but HKCU is the
#            same user's, so this one still answers.
# Each source is a scriptblock so tests can hand in canned answers; one that
# throws counts as "no answer" and the next is tried.
function Get-NetworkDriveMap([scriptblock]$Smb, [scriptblock]$NetUse, [scriptblock]$Registry) {
    $map = @{}
    if ($Smb) {
        try {
            foreach ($m in @(& $Smb)) {
                $letter = Get-DriveLetterOfPath ([string]$m.LocalPath)
                $remote = ([string]$m.RemotePath).Trim().TrimEnd('\')
                if ($letter -and (Test-UncPathText $remote) -and -not $map.ContainsKey($letter)) { $map[$letter] = $remote }
            }
        } catch { }
    }
    if ($NetUse) {
        try {
            $fromNet = ConvertFrom-NetUseLines @(& $NetUse)
            foreach ($k in $fromNet.Keys) { if (-not $map.ContainsKey($k)) { $map[$k] = $fromNet[$k] } }
        } catch { }
    }
    if ($Registry) {
        try {
            foreach ($m in @(& $Registry)) {
                $letter = Get-DriveLetterOfPath ([string]$m.LocalPath + ":")
                $remote = ([string]$m.RemotePath).Trim().TrimEnd('\')
                if ($letter -and (Test-UncPathText $remote) -and -not $map.ContainsKey($letter)) { $map[$letter] = $remote }
            }
        } catch { }
    }
    return $map
}

# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

# Roots     objects with App (Radarr, ...) and Path, as the *arr apps report them
# DriveMap  @{ "N:" = "\\server\share" }
# Existing  the PATH_REWRITE_RULES text already in .env ("" when none)
#
# A UNC root needs nothing. A drive-letter root with a known network path gets a
# rule, unless .env already has a rule for that letter (kept, never duplicated,
# never changed). A drive letter with no network path (a local disk, or a
# connection this login does not have) is left alone. Returns:
#   Rules    the full PATH_REWRITE_RULES text to save
#   Added    objects with Src, Dst and For (the root that needed it)
#   Kept     letters that already had a rule
#   Skipped  sentences for the run log (a UNC root is not listed: nothing to say)
#   Changed  whether Rules differs from Existing
function Get-PathMappingPlan($Roots, [hashtable]$DriveMap, [string]$Existing) {
    $rules = New-Object System.Collections.ArrayList
    foreach ($r in @(ConvertFrom-RewriteRules $Existing)) { [void]$rules.Add($r) }
    $have = @{}
    foreach ($r in $rules) { $have[([string]$r.Src).ToUpperInvariant()] = $true }

    $added = New-Object System.Collections.ArrayList
    $kept = New-Object System.Collections.ArrayList
    $skipped = New-Object System.Collections.ArrayList

    foreach ($root in @($Roots)) {
        $path = ([string]$root.Path).Trim()
        if (-not $path) { continue }
        if (Test-UncPathText $path) { continue }
        $letter = Get-DriveLetterOfPath $path
        if (-not $letter) { continue }
        if ($have.ContainsKey($letter)) {
            if ($kept -notcontains $letter) { [void]$kept.Add($letter) }
            continue
        }
        if ($DriveMap -and $DriveMap.ContainsKey($letter)) {
            $dst = [string]$DriveMap[$letter]
            [void]$rules.Add([pscustomobject]@{ Src = $letter; Dst = $dst })
            [void]$added.Add([pscustomobject]@{ Src = $letter; Dst = $dst; For = "$($root.App) folder $path" })
            $have[$letter] = $true
        } else {
            $line = "$($root.App) uses $path, but $letter is not a network drive in this Windows login, so it was left alone."
            if ($skipped -notcontains $line) { [void]$skipped.Add($line) }
        }
    }
    $text = ConvertTo-RewriteRules $rules
    return [pscustomobject]@{
        Rules   = $text
        Added   = @($added.ToArray())
        Kept    = @($kept.ToArray())
        Skipped = @($skipped.ToArray())
        Changed = ($text -ne ((ConvertTo-RewriteRules @(ConvertFrom-RewriteRules $Existing))))
    }
}

# The step. Never throws.
#   Apps       objects with Name (Radarr), Url and Key, one per *arr app that has a key
#   Existing   PATH_REWRITE_RULES now in .env
#   DriveMap   from Get-NetworkDriveMap
#   FetchRoots scriptblock: param($app) -> the root folder paths (strings); throws
#              when the app cannot be reached
#   Writer     scriptblock: param($line), for the run log
# An app that cannot be reached adds a log line and nothing else; the others are
# still asked. Returns the plan (see Get-PathMappingPlan) plus Asked, the number
# of apps that answered.
function Invoke-PathMappingStep($Apps, [string]$Existing, [hashtable]$DriveMap, [scriptblock]$FetchRoots, [scriptblock]$Writer) {
    function Say([string]$line) { if ($Writer) { try { & $Writer $line } catch { } } }
    $roots = New-Object System.Collections.ArrayList
    $asked = 0
    foreach ($app in @($Apps)) {
        try {
            $paths = @(& $FetchRoots $app)
            $asked++
            foreach ($p in $paths) {
                if ($p) { [void]$roots.Add([pscustomobject]@{ App = $app.Name; Path = [string]$p }) }
            }
        } catch {
            Say "$($app.Name) did not answer ($($_.Exception.Message)), so its folders were not checked."
        }
    }
    try {
        $plan = Get-PathMappingPlan @($roots.ToArray()) $DriveMap $Existing
    } catch {
        Say "Could not work out the drive mappings ($($_.Exception.Message))."
        $plan = [pscustomobject]@{
            Rules = $Existing; Added = @(); Kept = @(); Skipped = @(); Changed = $false
        }
    }
    foreach ($s in $plan.Skipped) { Say $s }
    foreach ($k in $plan.Kept) { Say "$k already has a rule in .env; kept as it is." }
    foreach ($a in $plan.Added) { Say "Mapped $($a.Src) to $($a.Dst) (for $($a.For))." }
    $plan | Add-Member -NotePropertyName Asked -NotePropertyValue $asked -Force
    return $plan
}
