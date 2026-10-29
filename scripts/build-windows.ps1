$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne 'Windows_NT') { throw 'Build Windows distributions on a Windows x64 runner.' }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required on the build machine.' }
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install --require-hashes -r requirements-windows.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $Python -m pip install --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
& $Python -m ruff check app tests scripts
if ($LASTEXITCODE -ne 0) { throw 'Lint failed.' }
New-Item -ItemType Directory -Force build\validation | Out-Null
& $Python -m pytest -q --junitxml=build/validation/tests.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $Python -m PyInstaller --noconfirm --clean ATLAS.spec
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }

# Document and package the complete onedir distribution, including _internal.
Copy-Item README.md dist\ATLAS\README.md
Copy-Item docs\WINDOWS.md dist\ATLAS\WINDOWS.md
$Archive = Join-Path $PWD 'dist\ATLAS-Windows-x64.zip'
Compress-Archive -Path dist\ATLAS -DestinationPath $Archive -Force
# Test what users download, extracted outside the repository, without Python on PATH.
$SmokeRoot = Join-Path $env:TEMP ('atlas-smoke-' + [guid]::NewGuid())
$SmokeDir = Join-Path $SmokeRoot 'data'
New-Item -ItemType Directory -Force $SmokeDir | Out-Null
Expand-Archive -Path $Archive -DestinationPath $SmokeRoot
$SavedPath = $env:PATH
$SavedBackend = $env:PYTHON_KEYRING_BACKEND
$SavedQtPlatform = $env:QT_QPA_PLATFORM
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHON_KEYRING_BACKEND = 'keyring.backends.null.Keyring'
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    $Exe = Join-Path $SmokeRoot 'ATLAS\ATLAS.exe'
    $Process = Start-Process -FilePath $Exe -WorkingDirectory $SmokeRoot -ArgumentList @('--data-dir', "`"$SmokeDir`"", '--smoke-test') -PassThru
    if (-not $Process.WaitForExit(60000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw 'Packaged application startup timed out.'
    }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) { throw "Packaged application failed: exit $($Process.ExitCode)" }
    $ResultPath = Join-Path $SmokeDir 'smoke-result.json'
    if (-not (Test-Path $ResultPath)) { throw 'Packaged application did not write its validation result.' }
    $Result = Get-Content $ResultPath -Raw | ConvertFrom-Json
    if (-not $Result.ok -or -not $Result.frozen -or $Result.platform -ne 'Windows' -or $Result.qt_platform -ne 'windows' -or -not $Result.webengine_local_asset) {
        throw "Packaged validation failed: $(Get-Content $ResultPath -Raw)"
    }
    if (-not (Test-Path (Join-Path $SmokeDir 'atlas.db'))) { throw 'Database was not initialized.' }
} finally {
    $env:PATH = $SavedPath
    $env:PYTHON_KEYRING_BACKEND = $SavedBackend
    $env:QT_QPA_PLATFORM = $SavedQtPlatform
    Copy-Item "$SmokeDir\*" build\validation -ErrorAction SilentlyContinue
}
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  ATLAS-Windows-x64.zip" | Set-Content dist\ATLAS-Windows-x64.zip.sha256 -Encoding ascii
Write-Host 'Validated the extracted Windows application; build ready at dist\ATLAS-Windows-x64.zip.'
