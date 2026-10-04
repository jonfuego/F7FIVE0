# Build, sign, verify, and attach the official F7FIVE0 Android APK to a
# GitHub release. Signing happens on this machine only; the release key never
# goes to GitHub (decision 2026-09-30: local signing, no CI signing, no Play).
#
# Flow:
#   1. Find the keystore properties file (default
#      $HOME\.f7five0-keys\keystore.properties, or $env:F7FIVE0_KEYSTORE_PROPERTIES).
#      Missing file = hard stop. Without it Gradle silently falls back to the
#      debug key, and a debug-signed APK must never ship.
#   2. Check -Version matches `version` in mobile\app.config.ts.
#   3. npm ci, expo prebuild --clean, gradlew assembleRelease, for one ABI
#      (64-bit arm64-v8a unless -Abi says otherwise).
#   4. apksigner verify, then compare the APK's signer SHA-256 with the
#      keystore's certificate SHA-256 (keytool). Mismatch = hard stop. Check
#      the APK carries native code for the requested ABI only.
#   5. Copy to mobile\dist\ and write a matching .sha256 file
#      (mobile\dist\ is gitignored):
#        F7FIVE0-<version>.apk          phone, arm64-v8a
#        F7FIVE0-<version>-armv7.apk    phone, armeabi-v7a (-Abi armeabi-v7a)
#        F7FIVE0-TV-<version>.apk       Android TV (-Tv)
#   6. Print the cert SHA-256 and the android:apk-key-hash origin (for the
#      passkey WEBAUTHN settings).
#   7. Upload to the GitHub release for tag v<version>, creating it as a DRAFT
#      when it does not exist yet. Then push the tag: the Release workflow
#      pulls the phone APK(s) from the draft into Setup.exe, attaches Setup.exe
#      and the zip, and publishes the release. Setup copies the APK onto the
#      server, so the server and its app are always the same version.
#
# Release order:
#   .\scripts\release-apk.ps1 -Version 1.2.0                     (64-bit, required)
#   .\scripts\release-apk.ps1 -Version 1.2.0 -Abi armeabi-v7a    (optional 32-bit)
#   git tag v1.2.0; git push origin v1.2.0
#
# Flags:
#   -Version <x.y.z>  Required. Must match mobile\app.config.ts.
#   -Tag <tag>        Release tag. Default v<Version>.
#   -Abi <abi>        arm64-v8a (default) or armeabi-v7a. -Tv without -Abi
#                     keeps every ABI (TV boxes are often 32-bit).
#   -Tv               Build the Android TV variant (EXPO_TV=1).
#   -SkipBuild        Reuse the APK already in mobile\android\app\build\...
#   -NoUpload         Build, verify, and stage in mobile\dist\ only.
#   -Clobber          Replace an APK with the same name already on the release.
#
# Needs: Node 22, JDK 17 (keytool on PATH or under JAVA_HOME), Android SDK
# build-tools (ANDROID_HOME or ANDROID_SDK_ROOT), and gh signed in (gh auth login).
#
# Example (repo root):
#   .\scripts\release-apk.ps1 -Version 1.0.0

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Tag = "",
    [ValidateSet("arm64-v8a", "armeabi-v7a")][string]$Abi = "arm64-v8a",
    [switch]$Tv,
    [switch]$SkipBuild,
    [switch]$NoUpload,
    [switch]$Clobber
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}
function Invoke-Native([scriptblock]$Block) {
    # Windows PowerShell 5.1 turns redirected native stderr into terminating
    # errors under ErrorActionPreference=Stop. Run with Continue and let the
    # caller check $LASTEXITCODE.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $prev }
}
function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Mobile = Join-Path $RepoRoot "mobile"
if (-not $Tag) { $Tag = "v$Version" }
# TV builds keep every ABI unless one is asked for.
$abiList = if ($Tv -and -not $PSBoundParameters.ContainsKey("Abi")) { "" } else { $Abi }

# 1. Keystore properties -----------------------------------------------------
Step "Keystore"
$propsPath = $env:F7FIVE0_KEYSTORE_PROPERTIES
if (-not $propsPath) { $propsPath = Join-Path $HOME ".f7five0-keys\keystore.properties" }
if (-not (Test-Path -LiteralPath $propsPath)) {
    Fail "Keystore properties not found at $propsPath. See mobile\README.md (Signing). Refusing to build: Gradle would sign with the debug key."
}
$props = @{}
foreach ($line in Get-Content -LiteralPath $propsPath) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("#")) { continue }
    $i = $t.IndexOf("=")
    if ($i -gt 0) { $props[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim() }
}
foreach ($k in "storeFile", "storePassword", "keyAlias", "keyPassword") {
    if (-not $props.ContainsKey($k) -or -not $props[$k]) { Fail "keystore.properties is missing $k" }
}
$storeFile = $props["storeFile"] -replace "/", "\"
if (-not (Test-Path -LiteralPath $storeFile)) { Fail "storeFile not found: $storeFile" }

# 2. Version check ------------------------------------------------------------
Step "Version $Version"
$cfg = Get-Content -LiteralPath (Join-Path $Mobile "app.config.ts") -Raw
$m = [regex]::Match($cfg, 'version:\s*"([^"]+)"')
if (-not $m.Success) { Fail "Could not read version from mobile\app.config.ts" }
if ($m.Groups[1].Value -ne $Version) {
    Fail "mobile\app.config.ts has version $($m.Groups[1].Value), not $Version. Bump version and versionCode first."
}
$vc = [regex]::Match($cfg, 'versionCode:\s*(\d+)')
if ($vc.Success) { Write-Host "    versionCode $($vc.Groups[1].Value)" }

# Tools -------------------------------------------------------------------------
$keytool = "keytool"
if ($env:JAVA_HOME -and (Test-Path (Join-Path $env:JAVA_HOME "bin\keytool.exe"))) {
    $keytool = Join-Path $env:JAVA_HOME "bin\keytool.exe"
} elseif (-not (Get-Command keytool -ErrorAction SilentlyContinue)) {
    Fail "keytool not found. Install JDK 17 or set JAVA_HOME."
}
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
if (-not $sdk) { $sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk" }
$bt = Join-Path $sdk "build-tools"
if (-not (Test-Path $bt)) { Fail "Android SDK build-tools not found under $sdk. Set ANDROID_HOME." }
$apksigner = Get-ChildItem $bt -Directory |
    Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
    ForEach-Object { Join-Path $_.FullName "apksigner.bat" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $apksigner) { Fail "apksigner.bat not found in $bt" }
if (-not $NoUpload -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Fail "gh (GitHub CLI) not found. Install it or use -NoUpload."
}

# 3. Build ----------------------------------------------------------------------
$built = Join-Path $Mobile "android\app\build\outputs\apk\release\app-release.apk"
if (-not $SkipBuild) {
    $oldTv = $env:EXPO_TV
    $oldProps = $env:F7FIVE0_KEYSTORE_PROPERTIES
    $oldAbis = $env:F7FIVE0_ABIS
    $startLoc = Get-Location
    try {
        if ($Tv) { $env:EXPO_TV = "1" } else { Remove-Item Env:EXPO_TV -ErrorAction SilentlyContinue }
        $env:F7FIVE0_KEYSTORE_PROPERTIES = $propsPath
        # plugins\withAbiFilter.js reads this during prebuild.
        if ($abiList) { $env:F7FIVE0_ABIS = $abiList } else { Remove-Item Env:F7FIVE0_ABIS -ErrorAction SilentlyContinue }
        Set-Location $Mobile
        Step "npm ci"
        & npm ci
        if ($LASTEXITCODE -ne 0) { Fail "npm ci failed" }
        Step "expo prebuild"
        & npx expo prebuild -p android --clean
        if ($LASTEXITCODE -ne 0) { Fail "expo prebuild failed" }
        Set-Location (Join-Path $Mobile "android")
        Step "gradlew assembleRelease ($(if ($abiList) { $abiList } else { 'all ABIs' }))"
        $gradleArgs = @("assembleRelease")
        if ($abiList) { $gradleArgs += "-PreactNativeArchitectures=$abiList" }
        & .\gradlew.bat @gradleArgs
        if ($LASTEXITCODE -ne 0) { Fail "gradle build failed" }
    } finally {
        Set-Location $startLoc
        if ($null -ne $oldTv) { $env:EXPO_TV = $oldTv } else { Remove-Item Env:EXPO_TV -ErrorAction SilentlyContinue }
        if ($null -ne $oldProps) { $env:F7FIVE0_KEYSTORE_PROPERTIES = $oldProps } else { Remove-Item Env:F7FIVE0_KEYSTORE_PROPERTIES -ErrorAction SilentlyContinue }
        if ($null -ne $oldAbis) { $env:F7FIVE0_ABIS = $oldAbis } else { Remove-Item Env:F7FIVE0_ABIS -ErrorAction SilentlyContinue }
    }
}
if (-not (Test-Path -LiteralPath $built)) { Fail "APK not found at $built" }

# 4. Verify signature against the keystore ----------------------------------------
Step "Verify signature"
$env:F7FIVE0_STOREPASS = $props["storePassword"]
try {
    $ktOut = Invoke-Native { & $keytool -list -v -keystore $storeFile -alias $props["keyAlias"] -storepass:env F7FIVE0_STOREPASS 2>&1 | Out-String }
} finally {
    Remove-Item Env:F7FIVE0_STOREPASS -ErrorAction SilentlyContinue
}
if ($LASTEXITCODE -ne 0) { Fail "keytool could not read the keystore (wrong storePassword or keyAlias?)" }
$km = [regex]::Match($ktOut, 'SHA256:\s*([0-9A-Fa-f:]{95})')
if (-not $km.Success) { Fail "Could not read SHA-256 from keytool output" }
$keyHex = ($km.Groups[1].Value -replace ":", "").ToLowerInvariant()

$asOut = Invoke-Native { & $apksigner verify --print-certs $built 2>&1 | Out-String }
if ($LASTEXITCODE -ne 0) { Fail "apksigner verify failed:`n$asOut" }
if ($asOut -match "CN=Android Debug") { Fail "APK is signed with the Android debug key. Not shipping it." }
$am = [regex]::Match($asOut, 'Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})')
if (-not $am.Success) { Fail "Could not read signer SHA-256 from apksigner output" }
$apkHex = $am.Groups[1].Value.ToLowerInvariant()
if ($apkHex -ne $keyHex) { Fail "APK signer $apkHex does not match keystore cert $keyHex" }
Write-Host "    signer matches keystore" -ForegroundColor Green

# Native code: only the requested ABI (a stale -SkipBuild APK or a prebuild
# that missed the ABI filter would ship the wrong or every ABI).
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($built)
try {
    $found = @($zip.Entries | ForEach-Object {
        if ($_.FullName -match '^lib/([^/]+)/') { $matches[1] }
    } | Sort-Object -Unique)
} finally { $zip.Dispose() }
if ($abiList) {
    $extra = @($found | Where-Object { $_ -ne $abiList })
    if ($extra.Count -or ($found -notcontains $abiList)) {
        Fail "APK native code is [$($found -join ', ')], expected only $abiList. Rebuild without -SkipBuild."
    }
}
Write-Host "    native code: $(if ($found.Count) { $found -join ', ' } else { 'none' })"

# 5. Stage ----------------------------------------------------------------------
$dist = Join-Path $Mobile "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$suffix = if ($abiList -eq "armeabi-v7a") { "-armv7" } else { "" }
$name = if ($Tv) { "F7FIVE0-TV-$Version$suffix.apk" } else { "F7FIVE0-$Version$suffix.apk" }
$out = Join-Path $dist $name
Copy-Item -LiteralPath $built -Destination $out -Force
$sha = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLowerInvariant()
$shaFile = "$out.sha256"
Set-Content -LiteralPath $shaFile -Value "$sha  $name" -Encoding ascii -NoNewline
Step "Staged $out"
Write-Host "    sha256 $sha"

# 6. Passkey values --------------------------------------------------------------
$bytes = New-Object byte[] 32
for ($i = 0; $i -lt 32; $i++) { $bytes[$i] = [Convert]::ToByte($keyHex.Substring($i * 2, 2), 16) }
$b64url = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
$colon = (($keyHex.ToUpperInvariant() -split "(..)" | Where-Object { $_ }) -join ":")
Write-Host ""
Write-Host "Release cert SHA-256 : $colon"
Write-Host "WebAuthn app origin  : android:apk-key-hash:$b64url"
Write-Host ""

# 7. Upload ---------------------------------------------------------------------
if ($NoUpload) {
    Write-Host "Skipping upload (-NoUpload)."
    exit 0
}
Step "Upload to release $Tag"
Invoke-Native { & gh release view $Tag *> $null }
if ($LASTEXITCODE -ne 0) {
    # No release yet: create a draft for the tag at this commit. The Release
    # workflow fills it in and publishes it when the tag is pushed.
    $commit = (Invoke-Native { & git -C $RepoRoot rev-parse HEAD 2>&1 | Out-String }).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { Fail "git rev-parse HEAD failed: $commit" }
    Invoke-Native { & gh release create $Tag --draft --target $commit --title "F7FIVE0 $Version" --notes "Draft. Published by the Release workflow when $Tag is pushed." }
    if ($LASTEXITCODE -ne 0) { Fail "gh release create $Tag --draft failed" }
    Write-Host "    created draft release $Tag at $($commit.Substring(0, 12))"
}
$ghArgs = @("release", "upload", $Tag, $out, $shaFile)
if ($Clobber) { $ghArgs += "--clobber" }
Invoke-Native { & gh @ghArgs }
if ($LASTEXITCODE -ne 0) { Fail "gh release upload failed (use -Clobber to replace an existing asset)" }
Write-Host "Done: $name attached to $Tag" -ForegroundColor Green
if (-not $Tv) {
    Write-Host ""
    Write-Host "Next (once every APK for $Tag is uploaded):"
    Write-Host "  git tag $Tag"
    Write-Host "  git push origin $Tag"
    Write-Host "The Release workflow bundles the APK into Setup.exe and publishes the release."
}
