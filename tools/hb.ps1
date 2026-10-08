# hb.ps1 - HarmonyOS (hvigor) build proxy
#
# WHY THIS EXISTS
#   Two independent restrictions make an in-place build impossible:
#     1. hvigor rejects non-ASCII project paths outright:
#          "Invalid project path. Current path does not match: <path>
#           Please modify the project path to ensure that it only contains
#           letters, digits, hyphens (-), underscores (_), periods (.), ..."
#        The session workspace is ...\项目开发, so the project must be built
#        from an ASCII mirror. (The Cangjie toolchain has the same class of
#        restriction for a different reason -- see tools/cj.ps1.)
#     2. hvigor wants to write caches under the user profile and to create a
#        workspace symlink. Both are redirected to an ASCII scratch area here.
#
# USAGE
#   powershell -ExecutionPolicy Bypass -File tools\hb.ps1 -Args assembleHap
#   powershell -ExecutionPolicy Bypass -File tools\hb.ps1 -Args clean
#   powershell -ExecutionPolicy Bypass -File tools\hb.ps1 -Args sync
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 decodes BOM-less
#       script files using the system ANSI code page, which corrupts UTF-8.

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$ErrorActionPreference = 'Continue'

# Follow a directory junction/symlink to its real target.
# PowerShell's Resolve-Path does NOT do this (it returns the link path), unlike
# Python's Path.resolve(). The workspace may be reached through a legacy
# junction, and the real path is the ASCII one.
function Get-RealPath([string]$p) {
    $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType -and $item.Target) {
        $t = $item.Target
        if ($t -is [array]) { $t = $t[0] }
        if (Test-Path -LiteralPath $t) { return (Get-Item -LiteralPath $t -Force).FullName }
    }
    return $item.FullName
}

$ws  = Get-RealPath (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$src = Join-Path $ws 'app\harmony'

if (-not (Test-Path $src)) {
    Write-Host "[hb] ERROR: project not found: $src"
    exit 2
}

$dev = 'D:\develop\DevEco Studio'
foreach ($p in @("$dev\tools\hvigor\bin\hvigorw.bat", "$dev\tools\ohpm\bin\ohpm.bat",
                 "$dev\tools\node\node.exe", "$dev\sdk")) {
    if (-not (Test-Path $p)) { Write-Host "[hb] ERROR: missing toolchain component: $p"; exit 2 }
}

# ---- decide: build in place, or mirror into ASCII ----
# The mirror existed ONLY because hvigor rejects non-ASCII project paths
# (error 00306003). With the workspace renamed to ...\Project that reason is
# gone, so build in place. NOTE: hvigor still needs elevated rights in this
# environment for a different reason -- it creates a symlink during setup, which
# the file sandbox denies. That is independent of the path and the mirror never
# fixed it.
$srcIsAscii = -not ($src -match '[^\x20-\x7E]')
if ($srcIsAscii) {
    $dst = $src
    $mirrored = $false
} else {
    if (-not $env:TEMP) {
        Write-Host "[hb] ERROR: path is non-ASCII and env:TEMP is not set"
        exit 2
    }
    $dst = Join-Path $env:TEMP 'hb\harmony'
    if ($dst -match '[^\x20-\x7E]') {
        Write-Host "[hb] ERROR: build path contains non-ASCII characters: $dst"
        exit 2
    }
    $mirrored = $true
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    # /MIR mirrors and deletes strays; exclude everything generated so the copy
    # stays a pure source mirror.
    robocopy $src $dst /MIR /XD node_modules oh_modules build .hvigor .idea .cxx /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { Write-Host "[hb] ERROR: robocopy failed ($LASTEXITCODE)"; exit 3 }
}

Write-Host "[hb] src = $src"
Write-Host "[hb] dst = $dst"
Write-Host "[hb] mode = $(if ($mirrored) { 'ASCII mirror (path was non-ASCII)' } else { 'in place (path is ASCII)' })"

if ($Args.Count -eq 0 -or $Args[0] -eq 'sync') {
    Write-Host "[hb] sync only, no hvigor invocation"
    exit 0
}

# ---- redirected homes (the sandbox denies writes outside the workspace/temp) ----
$hh = Join-Path $dst '_hvhome'
$nc = Join-Path $dst '_npmcache'
New-Item -ItemType Directory -Force -Path $hh, $nc | Out-Null
Set-Content -Path (Join-Path $hh '.npmrc') -Value 'node-linker=hoisted' -Encoding ASCII

$env:HVIGOR_USER_HOME  = $hh
$env:npm_config_cache  = $nc
$env:npm_config_registry = 'https://registry.npmmirror.com'
$env:USERPROFILE       = $hh
$env:HOME              = $hh
$env:npm_config_cache  = $nc
$env:npm_config_prefix = Join-Path $hh 'npm-global'
$env:npm_config_registry = 'https://registry.npmmirror.com/'
$env:DEVECO_SDK_HOME   = Join-Path $dev 'sdk'
$env:Path = "$dev\tools\node;$dev\tools\ohpm\bin;$dev\tools\hvigor\bin;$env:Path"

Push-Location $dst
$code = 0
try {
    & hvigorw.bat @Args --no-daemon 2>&1 | ForEach-Object { $_ }
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

# ---- pull the built artifact back ----
# Stale artifacts must be cleared BEFORE reporting, otherwise a failed build
# silently re-reports the previous successful HAP as if it were fresh.
$outDir = Join-Path $src '_out'
if (Test-Path $outDir) { Remove-Item (Join-Path $outDir '*.hap') -Force -ErrorAction SilentlyContinue }

if ($code -eq 0) {
    $found = Get-ChildItem $dst -Recurse -Filter '*.hap' -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName -match '\\build\\' }
    if ($found) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        foreach ($h in $found) {
            $target = Join-Path $outDir $h.Name
            Copy-Item $h.FullName $target -Force
            Write-Host ("[hb] artifact -> {0} ({1:N0} bytes, {2})" -f $target, $h.Length, $h.LastWriteTime.ToString('HH:mm:ss'))
        }
    } else {
        Write-Host "[hb] build reported success but no .hap was found"
    }
} else {
    Write-Host "[hb] build FAILED (exit $code); no artifact published"
}

Write-Host "[hb] hvigor exit code = $code"
exit $code
