# CI only: run install.ps1 on a clean Windows runner and check what it installed.
#   -Wheel <path>       the wheel built from this commit
#   -Installer <path>   the NSIS installer built by the widget workflow (omit: engine only)
# USERPROFILE and HOME point to a temporary folder, so ~/.claude and ~/.local are throwaway.
param(
    [Parameter(Mandatory = $true)][string]$Wheel,
    [string]$Installer = ''
)
$ErrorActionPreference = 'Continue'

function Assert([bool]$ok, [string]$message) {
    if (-not $ok) { Write-Host "ASSERT FAILED: $message" -ForegroundColor Red; exit 1 }
    Write-Host "assert ok: $message"
}

$fake = Join-Path $env:RUNNER_TEMP 'clean-home'
New-Item -ItemType Directory -Force -Path $fake | Out-Null
$env:USERPROFILE = $fake
$env:HOME = $fake
$env:PYTHONUTF8 = '1'
Assert (-not (Get-Command omniscient -ErrorAction SilentlyContinue)) 'omniscient is not installed before the script'

$script = [IO.File]::ReadAllText((Join-Path $PWD 'install.ps1'), [Text.Encoding]::UTF8)
$install = [scriptblock]::Create($script)  # the same text path as `irm ... | iex`
$params = @{ Wheel = (Resolve-Path $Wheel).Path }
if ($Installer) { $params.Installer = (Resolve-Path $Installer).Path } else { $params.SkipWidget = $true }

foreach ($run in 1, 2) {  # the second run proves idempotence (update in place, daemon restarted)
    Write-Host "::group::install.ps1 run $run"
    & $install @params
    $code = $LASTEXITCODE
    Write-Host '::endgroup::'
    Assert ($code -eq 0) "install.ps1 run $run exits 0"
}

$bin = (& uv tool dir --bin | Out-String).Trim()
$omni = Join-Path $bin 'omniscient.exe'
$version = (& $omni --version | Out-String).Trim()
Assert ($version -match '^omniscient \d') "omniscient --version prints a version ($version)"
$status = (& $omni group status 2>&1 | Out-String)
Assert ($status -match '127\.0\.0\.1:7341') 'group status: the daemon answers on 127.0.0.1:7341'
$settings = Join-Path $fake '.claude\settings.json'
Assert (Test-Path $settings) "hooks written to the temporary $settings"
Assert ((Get-Content -Raw $settings) -match 'omniscient') 'settings.json carries the omnigroup hooks'
$auto = (& $omni group autostart status | Out-String)
Assert ($auto -match 'actif') 'autostart task is registered'

if ($Installer) {
    $app = (Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Filter omnigroup.exe -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    Assert ([bool]$app) "widget installed at $app"
    Get-Process -Name omnigroup -ErrorAction SilentlyContinue | Stop-Process -Force
    $proc = Start-Process -FilePath $app -PassThru
    Start-Sleep -Seconds 8
    Assert (-not $proc.HasExited) 'the widget process stays alive for 8 seconds'
    Get-Process -Name omnigroup -ErrorAction SilentlyContinue | Stop-Process -Force
}

# Cleanup path documented in docs/install.md
& $omni group autostart remove
Assert ((& $omni group autostart status | Out-String) -match 'inactif') 'autostart task removed'
& $omni group hooks uninstall --write
Assert (-not ((Get-Content -Raw $settings) -match 'omniscient')) 'hooks removed from settings.json'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'omniscient' -and $_.CommandLine -match 'group\s+serve' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
& uv tool uninstall omniscient
Assert (-not (Test-Path $omni)) 'omniscient.exe removed by uv tool uninstall'
Write-Host 'install smoke test passed' -ForegroundColor Green
