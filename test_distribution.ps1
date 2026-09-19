# Runs only on a disposable GitHub Actions Windows runner.
param([Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this installation test in GitHub Actions only.' }

$extract = Join-Path $env:RUNNER_TEMP 'zip-test'
Expand-Archive "dist/YouTubeMusicDownloader-$Version-windows-x64.zip" $extract
$payload = Join-Path $extract 'YouTubeMusicDownloader'
& "$payload/_internal/node.exe" --version
if ($LASTEXITCODE -ne 0) { throw 'Bundled Node.js failed' }
$ffmpeg = Get-ChildItem "$payload/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe" | Select-Object -First 1
& $ffmpeg.FullName -version
if ($LASTEXITCODE -ne 0) { throw 'Bundled FFmpeg failed' }

# Both formats must start and share their database, even after uninstall.
$install = Join-Path $env:RUNNER_TEMP 'installed-app'
$setup = (Resolve-Path "dist/YouTubeMusicDownloader-$Version-windows-x64-setup.exe").Path
$process = Start-Process $setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$install`"") -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Install failed: $($process.ExitCode)" }
foreach ($folder in @($payload, $install)) {
    $process = Start-Process "$folder/YouTubeMusicDownloader.exe" -WindowStyle Hidden -PassThru
    try {
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Seconds 1
            $process.Refresh()
            if ($process.HasExited) { throw 'Application exited during startup' }
            if ($process.MainWindowHandle -ne 0 -and $process.Responding) { $ready = $true; break }
        }
        if (-not $ready) { throw 'Application window did not become ready' }
        if (-not $process.CloseMainWindow() -or -not $process.WaitForExit(10000)) { throw 'Application did not close cleanly' }
        if ($process.ExitCode -ne 0) { throw 'Application failed on exit' }
    } finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    }
}
$database = Join-Path $env:LOCALAPPDATA 'YouTubeMusicDownloader/library.sqlite3'
$before = (Get-FileHash $database).Hash
$process = Start-Process "$install/unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0) { throw 'Uninstall failed' }
if (Test-Path "$install/YouTubeMusicDownloader.exe") { throw 'Uninstall left the application behind' }
if ((Get-FileHash $database).Hash -ne $before) { throw 'Uninstall changed user data' }
