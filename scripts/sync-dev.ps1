$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$branch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne "main") {
    throw "Synchronized development must run from the main branch."
}

$dirty = git status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read Git status."
}
if ($dirty) {
    throw "Local changes exist. Commit or stash them before starting synchronized development."
}

Write-Host "Syncing origin/main..."
git fetch origin main
if ($LASTEXITCODE -ne 0) {
    throw "git fetch failed."
}
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) {
    throw "git pull --ff-only failed."
}

$localHead = git rev-parse HEAD
$remoteHead = git rev-parse origin/main
if ($localHead.Trim() -ne $remoteHead.Trim()) {
    throw "Local HEAD does not match origin/main after synchronization."
}

$envFile = Join-Path $repoRoot ".env.local"
if (-not (Test-Path -LiteralPath $envFile)) {
    $envContent = @"
# Local frontend uses the dedicated local FastAPI backend.
NEXT_PUBLIC_API_URL=http://localhost:8002
NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL=1
"@
    [System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.UTF8Encoding]::new($false))
} else {
    $envContent = Get-Content -LiteralPath $envFile -Raw
    if ($envContent -notmatch '(?m)^NEXT_PUBLIC_API_URL=') {
        Add-Content -LiteralPath $envFile -Value "`nNEXT_PUBLIC_API_URL=http://localhost:8002"
    }
}

$nextDir = Join-Path $repoRoot ".next"
if (Test-Path -LiteralPath $nextDir) {
    $resolvedNext = (Resolve-Path -LiteralPath $nextDir).Path
    $expectedNext = Join-Path $repoRoot ".next"
    if ($resolvedNext -ne $expectedNext) {
        throw "Unexpected Next.js cache path: $resolvedNext"
    }
    Remove-Item -LiteralPath $resolvedNext -Recurse -Force
}

Write-Host "Starting local frontend with the dedicated local FastAPI backend..."
Write-Host "Git commit: $($localHead.Trim())"
Write-Host "API: http://localhost:8002"
& npm.cmd run dev:local
exit $LASTEXITCODE
