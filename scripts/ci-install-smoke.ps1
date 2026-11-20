# CI only: run install.ps1 on a Windows runner and check what it installed.
#   -Wheel <path>       the wheel built from this commit
#   (the script also runs the real irm | iex one-liner against a local HTTP server)
#   -Installer <path>   the NSIS installer built by the widget workflow (omit: engine only)
#   -Profile clean      a simple English profile (the CI runner as it is)
#   -Profile hostile    a user profile and TEMP with spaces, accents, an apostrophe and
#                       parentheses, the French culture, and NO PYTHONUTF8 (a real console
#                       is not UTF-8: Python then encodes a pipe with the ANSI code page)
# USERPROFILE and HOME point to a temporary folder, so ~/.claude and ~/.local are throwaway.
# This file stays pure ASCII: PowerShell 5.1 reads a BOM-less script as ANSI, so every
# accented character below is built from its code point.
param(
    [Parameter(Mandatory = $true)][string]$Wheel,
    [string]$Installer = '',
    [ValidateSet('clean', 'hostile')][string]$Profile = 'clean'
)
$ErrorActionPreference = 'Continue'
$hostile = ($Profile -eq 'hostile')

function Assert([bool]$ok, [string]$message) {
    if (-not $ok) { Write-Host "ASSERT FAILED: $message" -ForegroundColor Red; exit 1 }
    Write-Host "assert ok: $message"
}

# Run a native command, capture stdout+stderr as text and the exit code (never throws).
function Invoke-Captured([string]$file, [string[]]$arguments, [object]$stdin = $null) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($null -ne $stdin) { $text = ($stdin | & $file @arguments 2>&1 | Out-String) }
        else { $text = (& $file @arguments 2>&1 | Out-String) }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Text = $text }
    } finally { $ErrorActionPreference = $old }
}

function Stop-OmniscientDaemon {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'omniscient' -and $_.CommandLine -match 'group\s+serve' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Wait-Daemon([string]$omni, [int]$port, [int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if ((Invoke-Captured $omni @('group', 'status', '--port', "$port")).Code -eq 0) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # read uv's UTF-8 paths

if ($hostile) {
    # Zoe-acute Muller-umlaut (test) O'Neil: spaces, non-ASCII, parentheses, an apostrophe.
    $segment = 'Zo' + [char]0xE9 + ' M' + [char]0xFC + "ller (test) O'Neil"
} else {
    $segment = 'clean-home'
}
$fake = Join-Path $env:RUNNER_TEMP $segment
New-Item -ItemType Directory -Force -Path $fake | Out-Null
$env:USERPROFILE = $fake
$env:HOME = $fake
if ($hostile) {
    # uv decides where tools, interpreters and cache live: put them under the odd profile too,
    # so the hooks, the scheduled task and the venv all carry the hostile path.
    $temp = Join-Path $fake 'AppData\Local\Temp'
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:UV_TOOL_DIR = Join-Path $fake 'uv\tools'
    $env:UV_TOOL_BIN_DIR = Join-Path $fake '.local\bin'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $fake 'uv\python'
    $env:UV_CACHE_DIR = Join-Path $fake 'uv\cache'
    Remove-Item Env:\PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:\PYTHONIOENCODING -ErrorAction SilentlyContinue
    # The French culture: this process, and the user's locale for the processes started later.
    try { Set-Culture 'fr-FR' } catch {
        try { Set-ItemProperty -Path 'HKCU:\Control Panel\International' -Name 'LocaleName' -Value 'fr-FR' } catch { Write-Host "could not set the user locale: $_" }
    }
    $fr = [Globalization.CultureInfo]::GetCultureInfo('fr-FR')
    [Threading.Thread]::CurrentThread.CurrentCulture = $fr
    [Threading.Thread]::CurrentThread.CurrentUICulture = $fr
    [Globalization.CultureInfo]::DefaultThreadCurrentCulture = $fr
    [Globalization.CultureInfo]::DefaultThreadCurrentUICulture = $fr
    $acp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage').ACP
    $threadCulture = [Globalization.CultureInfo]::CurrentCulture.Name  # Get-Culture is the host's, fixed at startup
    $userLocale = (Get-ItemProperty 'HKCU:\Control Panel\International').LocaleName
    Write-Host "culture=$threadCulture user-locale=$userLocale ansi-code-page=$acp (a real localized UI language needs a language pack: not reproducible here)"
    Assert ($threadCulture -eq 'fr-FR') 'the session culture is fr-FR'
    Assert ($userLocale -eq 'fr-FR') 'the user locale inherited by new processes is fr-FR'
    Assert ($acp -ne '65001') "the ANSI code page is not UTF-8 ($acp): Python pipes are not UTF-8"
    Assert (("{0}" -f 1.5) -eq '1,5') 'fr-FR formatting is active (decimal comma)'
} else {
    $env:PYTHONUTF8 = '1'
}
Assert (-not (Get-Command omniscient -ErrorAction SilentlyContinue)) 'omniscient is not installed before the script'

$script = [IO.File]::ReadAllText((Join-Path $PWD 'install.ps1'), [Text.Encoding]::UTF8)
$install = [scriptblock]::Create($script)  # the same text path as `irm ... | iex`
$params = @{ Wheel = (Resolve-Path $Wheel).Path; NoLaunch = $true }
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
if ($hostile) { Assert ($bin.Contains($segment)) "the uv bin folder carries the hostile profile name ($bin)" }
$version = (& $omni --version | Out-String).Trim()
Assert ($version -match '^omniscient \d') "omniscient --version prints a version ($version)"
$status = (& $omni group status 2>&1 | Out-String)
Assert ($status -match '127\.0\.0\.1:7341') 'group status: the daemon answers on 127.0.0.1:7341'

# Console code page: the CLI's French messages (check marks, arrows) must never crash a pipe.
$preview = Invoke-Captured $omni @('group', 'setup', '--skip-widget')
Assert (($preview.Code -eq 0) -and ($preview.Text -notmatch 'UnicodeEncodeError|Traceback')) 'group setup (preview, piped) does not crash on the console code page'

# Hooks: valid JSON read as UTF-8, exec form, and the command really resolves and runs.
$settings = Join-Path $fake '.claude\settings.json'
Assert (Test-Path -LiteralPath $settings) "hooks written to the temporary $settings"
$raw = [IO.File]::ReadAllText($settings, [Text.Encoding]::UTF8)
Assert ($raw -match 'omniscient') 'settings.json carries the omniscient hooks'
$json = $raw | ConvertFrom-Json
$entry = $json.hooks.SessionStart[0].hooks[0]
$hookCommand = [string]$entry.command
$hookArgs = @($entry.args)
Write-Host "hook command: $hookCommand ; args: $($hookArgs -join ' ')"
Assert ($hookArgs.Count -gt 0) 'the hook uses the exec form (command + args), no shell string to quote'
Assert (Test-Path -LiteralPath $hookCommand) 'the hook command exists on disk'
if ($hostile) {
    Assert ($hookCommand.Replace('/', '\').Contains($segment)) 'the hook command path carries the hostile profile name (spaces, accent, apostrophe, parentheses)'
}
$sample = '{"hook_event_name":"SessionStart","session_id":"ci-smoke","cwd":"."}'
$hookRun = Invoke-Captured $hookCommand $hookArgs $sample
Assert ($hookRun.Code -eq 0) "the hook command runs from its path and exits 0 ($($hookRun.Text.Trim()))"
$statusLine = [string]$json.statusLine.command
Write-Host "statusLine: $statusLine"
Assert ($statusLine -match 'statusline') 'the statusLine command is written'
# The statusLine is one string Claude hands to a shell: try cmd.exe and PowerShell (info only:
# which shell runs it depends on the user's Claude Code setup; Git Bash accepts double quotes).
function Test-StatusLine([string]$exe, [string]$arguments) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $arguments
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $proc = [Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Write('{}')
    $proc.StandardInput.Close()
    $null = $proc.WaitForExit(20000)
    return $proc.ExitCode
}
$cmdCode = Test-StatusLine 'cmd.exe' "/d /s /c `"$statusLine`""
$psCode = Test-StatusLine 'powershell.exe' ('-NoProfile -Command "& ' + ($statusLine -replace '"', '\"') + '"')
Write-Host "statusLine exit codes: cmd.exe=$cmdCode powershell.exe=$psCode"
if (($cmdCode -ne 0) -or ($psCode -ne 0)) { Write-Host 'WARNING: the statusLine string does not run in every Windows shell (see the codes above)' -ForegroundColor Yellow }

$auto = (& $omni group autostart status | Out-String)
Assert ($auto -match 'actif') 'autostart (Run key) is registered'

# The Run value really starts the daemon: its command line survives spaces, accents, parentheses.
Stop-OmniscientDaemon
Start-Sleep -Seconds 2
Assert (-not ((Invoke-Captured $omni @('group', 'status')).Code -eq 0)) 'the daemon is stopped before the Run test'
$runCommand = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run').Omniscient
Assert ([bool]$runCommand) 'the Run value exists'
$null = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $runCommand }
Assert (Wait-Daemon $omni 7341 40) 'the Run command line starts the daemon (it resolves like at logon)'

# Port conflicts: a clear French failure, never a silent death.
$taken = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 7352)
$taken.Start()
$busy = Invoke-Captured $omni @('group', 'serve', '--port', '7352')
$taken.Stop()
Assert (($busy.Code -ne 0) -and ($busy.Text -match '7352') -and ($busy.Text -match 'occup')) "serve on a busy port exits non-zero and names it ($($busy.Text.Trim().Split([char]10)[0]))"
Assert ($busy.Text -match 'OMNISCIENT_URL') 'the busy-port message says how the hooks and the widget must follow'
$free = Invoke-Captured $omni @('group', 'serve', '--check-port', '--port', '7353')
Assert ($free.Code -eq 0) 'serve --check-port exits 0 on a free port'
$ours = Invoke-Captured $omni @('group', 'serve', '--check-port', '--port', '7341')
Assert (($ours.Code -eq 0) -and ($ours.Text -match 'tourne')) 'our own daemon on the port is reported as already running, not as a conflict'
# Windows-reserved ranges (WSAEACCES): an elevated runner can still bind an administratively
# excluded port, so this only reports what happens; the classification is unit-tested.
$reserved = Invoke-Captured 'netsh' @('int', 'ipv4', 'add', 'excludedportrange', 'protocol=tcp', 'startport=7360', 'numberofports=1')
if ($reserved.Code -eq 0) {
    $res = Invoke-Captured $omni @('group', 'serve', '--check-port', '--port', '7360')  # never a real serve here
    $null = Invoke-Captured 'netsh' @('int', 'ipv4', 'delete', 'excludedportrange', 'protocol=tcp', 'startport=7360', 'numberofports=1')
    Write-Host "excluded-port check on 7360: exit $($res.Code): $($res.Text.Trim())"
} else {
    Write-Host "skipped the excluded-port probe (netsh needs administrator rights): $($reserved.Text.Trim())"
}

# update --check / --dry-run: network-dependent (a release may not carry all assets yet);
# they must answer in French with a known exit code, never a traceback.
foreach ($flag in '--check', '--dry-run') {
    $upd = Invoke-Captured $omni @('update', $flag)
    Assert (($upd.Code -in 0, 1, 2) -and ($upd.Text -notmatch 'Traceback')) "omniscient update $flag answers without a traceback (exit $($upd.Code))"
}

# doctor: read-only, safe to paste: no profile path, no secrets.
$doc = Invoke-Captured $omni @('group', 'doctor')
Write-Host $doc.Text
Assert ($doc.Code -eq 0) 'group doctor exits 0 on a healthy install'
Assert ($doc.Text -notmatch 'Traceback') 'group doctor never prints a traceback'
Assert ((-not $doc.Text.Contains($fake)) -and (-not $doc.Text.Contains($segment))) 'group doctor redacts the profile path'
Assert ($doc.Text -match '(?m)^OK ') 'group doctor prints OK lines'

# A different port (the 7341 case on a PC where it is taken): -Port moves daemon, task, hooks
# variable and status together.
Write-Host '::group::install.ps1 run 3 (-Port 7371)'
& $install @params -Port 7371
$code = $LASTEXITCODE
Write-Host '::endgroup::'
Assert ($code -eq 0) 'install.ps1 -Port 7371 exits 0'
Assert ($env:OMNISCIENT_URL -eq 'http://127.0.0.1:7371') 'OMNISCIENT_URL (what the hooks read) follows -Port'
$moved = (Invoke-Captured $omni @('group', 'status')).Text
Assert ($moved -match '127\.0\.0\.1:7371') 'group status (no --port) follows OMNISCIENT_URL to the daemon on 7371'
Assert (((Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run').Omniscient) -match '--port 7371') 'the Run value is written with the new port'
[Environment]::SetEnvironmentVariable('OMNISCIENT_URL', $null, 'User')
Remove-Item Env:\OMNISCIENT_URL -ErrorAction SilentlyContinue

# The REAL one-liner path: install.ps1 served over HTTP and run as `irm <url> | iex` in a fresh
# shell (iex takes no parameters: the OMNISCIENT_INSTALL_* variables carry them). The shell is the
# one of the matrix leg (powershell 5.1 or pwsh 7). Success is judged on the effects, not only on
# the exit code of `-c`.
$probe = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
$probe.Start()
$httpPort = $probe.LocalEndpoint.Port
$probe.Stop()
$listener = New-Object Net.HttpListener
$listener.Prefixes.Add("http://127.0.0.1:$httpPort/")
$listener.Start()
$serverBody = [Text.Encoding]::UTF8.GetBytes($script)
$serverShell = [powershell]::Create()
$null = $serverShell.AddScript({
    param($l, $bytes)
    while ($l.IsListening) {
        try { $ctx = $l.GetContext() } catch { break }
        $ctx.Response.ContentType = 'text/plain; charset=utf-8'
        $ctx.Response.ContentLength64 = $bytes.Length
        $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        $ctx.Response.Close()
    }
}).AddArgument($listener).AddArgument($serverBody)
$serverHandle = $serverShell.BeginInvoke()
$oneLinerShell = if ($PSVersionTable.PSEdition -eq 'Core') { 'pwsh' } else { 'powershell' }
$env:OMNISCIENT_INSTALL_WHEEL = $params.Wheel
if ($Installer) { $env:OMNISCIENT_INSTALL_INSTALLER = $params.Installer } else { $env:OMNISCIENT_INSTALL_SKIPWIDGET = '1' }
$env:OMNISCIENT_INSTALL_NOLAUNCH = '1'
Write-Host "::group::irm http://127.0.0.1:$httpPort/install.ps1 | iex ($oneLinerShell)"
$oneLiner = Invoke-Captured $oneLinerShell @('-NoProfile', '-ExecutionPolicy', 'ByPass', '-c', "irm http://127.0.0.1:$httpPort/install.ps1 | iex")
Write-Host $oneLiner.Text
Write-Host '::endgroup::'
$listener.Stop()
$serverShell.Dispose()
foreach ($name in 'WHEEL', 'INSTALLER', 'SKIPWIDGET', 'NOLAUNCH') { Remove-Item "Env:\OMNISCIENT_INSTALL_$name" -ErrorAction SilentlyContinue }
Assert ($oneLiner.Text -notmatch 'ERREUR :') 'the irm | iex one-liner reports no error'
Assert ($oneLiner.Text -match 'Et maintenant') 'the irm | iex one-liner reaches its final message'
Assert ($oneLiner.Text -notmatch 'lance-le|double-clic|gh absent|Demander un code') 'the install output has no confusing WSL, pairing or gh text'
Assert ($oneLiner.Code -eq 0) "the irm | iex one-liner exits 0 (got $($oneLiner.Code))"
Assert ((Invoke-Captured $omni @('group', 'status')).Code -eq 0) 'the daemon answers after the irm | iex one-liner'
Assert (((Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run').Omniscient) -match '--port 7341') 'the Run value is back on port 7341 after the one-liner'

if ($Installer) {
    $app = (Get-ChildItem -LiteralPath $fake, $env:LOCALAPPDATA, $env:ProgramFiles -Filter omniscient-widget.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    Assert ([bool]$app) "widget installed at $app"
    Get-Process -Name omniscient-widget -ErrorAction SilentlyContinue | Stop-Process -Force
    $proc = Start-Process -FilePath $app -PassThru
    Start-Sleep -Seconds 8
    Assert (-not $proc.HasExited) 'the widget process stays alive for 8 seconds'
    Get-Process -Name omniscient-widget -ErrorAction SilentlyContinue | Stop-Process -Force
}

# Cleanup path documented in docs/install.md
& $omni group autostart remove
Assert ((& $omni group autostart status | Out-String) -match 'inactif') 'autostart task removed'
& $omni group hooks uninstall --write
Assert (-not ([IO.File]::ReadAllText($settings, [Text.Encoding]::UTF8) -match 'omniscient')) 'hooks removed from settings.json'
Stop-OmniscientDaemon
& uv tool uninstall omniscient
Assert (-not (Test-Path -LiteralPath $omni)) 'omniscient.exe removed by uv tool uninstall'
Write-Host 'install smoke test passed' -ForegroundColor Green
