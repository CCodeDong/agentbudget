# cj.ps1 - Cangjie build proxy
#
# WHY THIS EXISTS
#   `cjpm` runs `cjc -p <path> --scan-dependency`, which fails with
#   "Invalid unicode scalar value" on non-ASCII paths. Any project that
#   contains an `import` statement therefore cannot be built in place.
#
#   The workspace was previously `...\项目开发`, so this script mirrored the
#   sources into an ASCII directory under the session TEMP and built there.
#   The workspace is now `...\Project` (pure ASCII), so **the mirror is no
#   longer needed**: this script builds in place and only falls back to the
#   mirror when the resolved path is still non-ASCII (e.g. reached through the
#   legacy junction, or a project placed outside the workspace).
#
#   Dropping the mirror also removes a real failure mode: the mirror lived in
#   the session TEMP, which rotates and silently wiped it mid-session.
#
# USAGE  (Windows PowerShell 5.1 needs -ExecutionPolicy Bypass for this file)
#   powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project NAME build
#   ... -Project NAME test
#   ... -Project NAME run
#   ... -Project NAME bench
#   ... -Project NAME cover
#   ... -Project NAME bin
#   ... -Project NAME clean
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 decodes BOM-less
#       script files using the system ANSI code page, which corrupts UTF-8.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$ErrorActionPreference = 'Continue'

# Follow a directory junction/symlink to its real target.
# PowerShell's Resolve-Path does NOT do this (it returns the link path), unlike
# Python's Path.resolve(). Since the workspace may be reached through a
# legacy junction, the build must use the real path to be ASCII.
function Get-RealPath([string]$p) {
    $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType -and $item.Target) {
        $t = $item.Target
        if ($t -is [array]) { $t = $t[0] }
        if (Test-Path -LiteralPath $t) { return (Get-Item -LiteralPath $t -Force).FullName }
    }
    return $item.FullName
}

# ---- toolchain ----
$ws  = Get-RealPath (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$src = Join-Path $ws "projects\$Project"

# Allow an explicit project directory (absolute, or relative to the workspace)
# for projects that live outside projects\, e.g. the stdx sample projects.
if (-not (Test-Path $src)) {
    $alt = $Project
    if (-not [System.IO.Path]::IsPathRooted($alt)) { $alt = Join-Path $ws $alt }
    if (Test-Path $alt) {
        $src = (Resolve-Path $alt).Path
    }
}

if (-not (Test-Path $src)) {
    Write-Host "[cj] ERROR: project not found: $src"
    exit 2
}

$env:Path = "D:\develop\Cangjie\tools\bin;D:\develop\Cangjie\bin;$env:Path"
if (-not $env:CANGJIE_HOME) { $env:CANGJIE_HOME = 'D:\develop\Cangjie' }
$cjpm = 'D:\develop\Cangjie\tools\bin\cjpm.exe'

# ---- decide: build in place, or mirror into ASCII ----
$srcIsAscii = -not ($src -match '[^\x20-\x7E]')
if ($srcIsAscii) {
    $dst = $src
    $mirrored = $false
} else {
    $leaf = Split-Path -Leaf $src
    if (-not $env:TEMP) {
        Write-Host "[cj] ERROR: path is non-ASCII and env:TEMP is not set, so no ASCII mirror can be made"
        exit 2
    }
    $dst = Join-Path $env:TEMP "cjbuild\$leaf"
    if ($dst -match '[^\x20-\x7E]') {
        Write-Host "[cj] ERROR: build path still contains non-ASCII characters: $dst"
        Write-Host "[cj]        Cangjie cannot build there. Aborting."
        exit 2
    }
    $mirrored = $true

    # ---- sync source into the ASCII build area ----
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    $prevSrc = Join-Path $dst 'src'
    if (Test-Path $prevSrc) { Remove-Item $prevSrc -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item (Join-Path $src 'cjpm.toml') $dst -Force
    Copy-Item (Join-Path $src 'src') $dst -Recurse -Force
    foreach ($extra in @('cjpm.lock', 'README.md', 'tests')) {
        $p = Join-Path $src $extra
        if (Test-Path $p) { Copy-Item $p $dst -Recurse -Force }
    }
}

Write-Host "[cj] src = $src"
Write-Host "[cj] dst = $dst"
Write-Host "[cj] mode = $(if ($mirrored) { 'ASCII mirror (path was non-ASCII)' } else { 'in place (path is ASCII)' })"

if ($Args.Count -eq 0 -or $Args[0] -eq 'sync') {
    Write-Host "[cj] sync only, no cjpm invocation"
    exit 0
}

$isCover = ($Args[0] -eq 'cover')
$isBin   = ($Args[0] -eq 'bin')

# ---- run cjpm ----
Push-Location $dst
$code = 0
try {
    if ($isCover) {
        Write-Host "[cj] cjpm test --coverage"
        & $cjpm test --coverage 2>&1 | ForEach-Object { $_ }
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            $cjcov = 'D:\develop\Cangjie\tools\bin\cjcov.exe'
            $htmlDir = Join-Path $dst 'coverage_html'
            New-Item -ItemType Directory -Force -Path $htmlDir | Out-Null
            # -b enables branch coverage; --json emits machine-readable totals.
            # Without -b the Branches column reads "-", which is how an earlier
            # revision ended up quoting a per-file LINE figure as branch coverage.
            Write-Host "[cj] cjcov --branches --html-details --json"
            & $cjcov --root=$dst --branches --html-details --json --output=$htmlDir 2>&1 | ForEach-Object { $_ }
            Write-Host "[cj] cjcov exit code = $LASTEXITCODE"
        }
    } elseif ($isBin) {
        Write-Host "[cj] cjpm build (release)"
        & $cjpm build 2>&1 | ForEach-Object { $_ }
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            # The build mirror lives in the session TEMP and is not durable, so
            # publish the executable somewhere stable for the experiment harness.
            $built = Get-ChildItem (Join-Path $dst 'target\release\bin') -Filter '*.exe' -ErrorAction SilentlyContinue |
                     Where-Object { $_.Name -notmatch 'unittest|testrunner' } |
                     Select-Object -First 1
            if ($built) {
                $binDir = Join-Path $src 'bin'
                New-Item -ItemType Directory -Force -Path $binDir | Out-Null
                Copy-Item $built.FullName (Join-Path $binDir 'agentbudget4cj.exe') -Force
                Write-Host "[cj] published -> $(Join-Path $binDir 'agentbudget4cj.exe')"
            } else {
                Write-Host "[cj] WARNING: no executable found under target\release\bin"
                $code = 3
            }
        }
    } else {
        & $cjpm @Args 2>&1 | ForEach-Object { $_ }
        $code = $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# ---- pull artifacts back (bench CSV / coverage / html reports) ----
$outDir = Join-Path $src '_out'
$pulled = New-Object System.Collections.ArrayList
$pullSpecs = @(
    @{ From = (Join-Path $dst 'target\release\reports'); To = 'reports' },
    @{ From = (Join-Path $dst 'cov_output');             To = 'cov_output' },
    @{ From = (Join-Path $dst 'coverage_html');          To = 'coverage_html' }
)
foreach ($spec in $pullSpecs) {
    if (Test-Path $spec.From) {
        $target = Join-Path $outDir $spec.To
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item $spec.From $target -Recurse -Force -ErrorAction SilentlyContinue
        [void]$pulled.Add($spec.To)
    }
}
if ($pulled.Count -gt 0) {
    Write-Host "[cj] artifacts pulled back to $outDir"
    $pulled | Select-Object -Unique | ForEach-Object { Write-Host "      $_" }
}

Write-Host "[cj] cjpm exit code = $code"
exit $code
