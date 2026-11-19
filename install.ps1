# Omniscient - installation en une commande (Windows 10/11, PowerShell 5.1 ou 7, sans droits administrateur).
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1 | iex"
#
# Ce que le script fait (détails : docs/install.md) :
#   1. trouve ou installe uv (winget, sinon l'installeur officiel astral.sh) ;
#   2. installe le moteur depuis la roue (.whl) de la dernière version GitHub, SHA-256 vérifié, sans git ;
#   3. active le démarrage du démon à l'ouverture de session et le lance ;
#   4. écrit les hooks Claude Code (sauvegarde d'abord) et installe le widget Omnigroup (silencieux, par utilisateur) ;
#   5. affiche l'état et la suite.
# Relancer le script met tout à jour. Rien n'est écrit hors de ton profil utilisateur.
#
# Parametres (pour les tests ; la commande ci-dessus n'en a pas besoin) :
#   -Wheel <chemin>      roue locale à installer au lieu de la dernière version publiée
#   -Installer <chemin>  installeur du widget local (Omnigroup_*_x64-setup.exe)
#   -SkipWidget          ne pas installer le widget
#   -NoAutostart         ne pas activer le démarrage automatique du démon à l'ouverture de session
#   -NoLaunch            ne pas ouvrir le widget à la fin
#   -Port <n>            port du démon si 7341 est pris (défaut : 7341, ou celui de la variable OMNIGROUP_URL)
#
# `irm ... | iex` ne peut pas recevoir de paramètres : chacun a donc une variable d'environnement
# équivalente, lue quand le paramètre n'est pas donné :
#   OMNIGROUP_INSTALL_WHEEL, OMNIGROUP_INSTALL_INSTALLER, OMNIGROUP_INSTALL_PORT (valeurs),
#   OMNIGROUP_INSTALL_SKIPWIDGET, OMNIGROUP_INSTALL_NOAUTOSTART, OMNIGROUP_INSTALL_NOLAUNCH (1 ou true).
param(
    [string]$Wheel = '',
    [string]$Installer = '',
    [switch]$SkipWidget,
    [switch]$NoAutostart,
    [switch]$NoLaunch,
    [int]$Port = 0
)

# Parameters not given fall back to OMNIGROUP_INSTALL_* (the iex path cannot pass any).
function Get-InstallEnv([string]$name) { return [string][Environment]::GetEnvironmentVariable("OMNIGROUP_INSTALL_$name") }
function Test-InstallFlag([string]$name) { return ((Get-InstallEnv $name).Trim().ToLowerInvariant() -in @('1', 'true', 'yes')) }
if (-not $Wheel) { $Wheel = Get-InstallEnv 'WHEEL' }
if (-not $Installer) { $Installer = Get-InstallEnv 'INSTALLER' }
$wantSkipWidget = ([bool]$SkipWidget) -or (Test-InstallFlag 'SKIPWIDGET')
$wantNoAutostart = ([bool]$NoAutostart) -or (Test-InstallFlag 'NOAUTOSTART')
$wantNoLaunch = ([bool]$NoLaunch) -or (Test-InstallFlag 'NOLAUNCH')
if ($Port -le 0) {
    $envPort = 0
    if ([int]::TryParse((Get-InstallEnv 'PORT'), [ref]$envPort) -and $envPort -gt 0) { $Port = $envPort }
}

function Install-Omniscient {
    param([string]$Wheel, [string]$Installer, [bool]$SkipWidget, [bool]$NoAutostart, [bool]$NoLaunch, [int]$RequestedPort)

    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    $Repo = 'VinceVibeCoding/omniscient'
    $Total = 5
    $omni = $null
    $app = $null
    $savedEnv = @{ PYTHONUTF8 = $env:PYTHONUTF8; PYTHONIOENCODING = $env:PYTHONIOENCODING }
    $Headers = @{ 'User-Agent' = 'omniscient-install'; 'Accept' = 'application/vnd.github+json' }

    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
    # Python encodes a pipe with the ANSI code page (cp1252...): make it speak the UTF-8 we read.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    function Step([int]$n, [string]$text) { Write-Host ''; Write-Host "[$n/$Total] $text" -ForegroundColor Cyan }
    function Info([string]$text) { Write-Host "      $text" }
    function Ok([string]$text) { Write-Host "  OK  $text" -ForegroundColor Green }
    function Warn([string]$text) { Write-Host "  !!  $text" -ForegroundColor Yellow }

    # Run a native command: output goes to the console, the exit code comes back.
    # (PowerShell 5.1 turns native stderr into errors under 'Stop', so relax it here.)
    function Invoke-Native([string]$file, [string[]]$arguments, [switch]$Quiet) {
        $old = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            if ($Quiet) { & $file @arguments *> $null } else { & $file @arguments | Out-Host }
            return $LASTEXITCODE
        } finally { $ErrorActionPreference = $old }
    }

    # The daemon port: -Port, else the one of OMNIGROUP_URL (what the hooks use), else 7341.
    function Resolve-Port([int]$requested) {
        if ($requested -gt 0) { return $requested }
        $url = [Environment]::GetEnvironmentVariable('OMNIGROUP_URL', 'User')
        if (-not $url) { $url = $env:OMNIGROUP_URL }
        if ($url -match '^http://(127\.0\.0\.1|localhost):(\d{1,5})/?$') { return [int]$Matches[2] }
        return 7341
    }
    $Port = Resolve-Port $RequestedPort

    function Update-SessionPath {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [Environment]::GetEnvironmentVariable('Path', 'User')
        $extra = Join-Path $env:USERPROFILE '.local\bin'
        $seen = @{}
        $kept = @()
        foreach ($entry in (@($env:Path, $machine, $user, $extra) -join ';').Split(';')) {
            $key = $entry.Trim().TrimEnd('\').ToLowerInvariant()
            if ($key -and -not $seen.ContainsKey($key)) { $seen[$key] = $true; $kept += $entry.Trim() }
        }
        $env:Path = $kept -join ';'
    }

    function Test-Uv {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { return $false }
        return ((Invoke-Native 'uv' @('--version') -Quiet) -eq 0)
    }

    function Stop-Daemon {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -match 'omniscient' -and $_.CommandLine -match 'group\s+serve' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }

    # Where the NSIS installer put the app: the uninstall entry says (InstallLocation or the
    # folder of the uninstaller), else the usual per-user folders, else a shallow search.
    function Find-WidgetExe {
        $keys = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')
        foreach ($entry in (Get-ItemProperty -Path $keys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq 'Omnigroup' })) {
            $folders = @($entry.InstallLocation, (Split-Path -Parent ([string]$entry.UninstallString).Trim('"'))) | Where-Object { $_ }
            foreach ($folder in $folders) {
                $hit = Get-ChildItem -LiteralPath $folder -Filter 'omnigroup.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($hit) { return $hit.FullName }
            }
        }
        foreach ($rel in 'Omnigroup\omnigroup.exe', 'Programs\Omnigroup\omnigroup.exe') {
            $candidate = Join-Path $env:LOCALAPPDATA $rel
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
        foreach ($root in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }) {
            $hit = Get-ChildItem -LiteralPath $root -Filter 'omnigroup.exe' -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
        return $null
    }

    function Get-LatestWheel([string]$workDir) {
        $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
        try {
            $release = Invoke-RestMethod -Uri $apiUrl -Headers $Headers -UseBasicParsing
        } catch {
            throw "Impossible de lire la dernière version sur GitHub ($apiUrl) : $($_.Exception.Message). Vérifie ta connexion Internet (ou ton proxy) et relance."
        }
        $prefix = "https://github.com/$Repo/releases/download/"
        $assets = @($release.assets)
        $whl = $assets | Where-Object { $_.name -match '^omniscient-[0-9][0-9A-Za-z.+!_-]*-py3-none-any\.whl$' -and $_.browser_download_url.StartsWith($prefix) } | Select-Object -First 1
        $sums = $assets | Where-Object { $_.name -eq 'SHA256SUMS' -and $_.browser_download_url.StartsWith($prefix) } | Select-Object -First 1
        if (-not $whl -or -not $sums) {
            throw "La version $($release.tag_name) ne contient pas encore le moteur (roue .whl + SHA256SUMS). Réessaie plus tard ou suis l'installation manuelle du README."
        }
        $wheelPath = Join-Path $workDir $whl.name
        $sumsPath = Join-Path $workDir 'SHA256SUMS'
        Info "Téléchargement de $($whl.name) ($($release.tag_name))..."
        Invoke-WebRequest -Uri $whl.browser_download_url -OutFile $wheelPath -UseBasicParsing -Headers $Headers
        Invoke-WebRequest -Uri $sums.browser_download_url -OutFile $sumsPath -UseBasicParsing -Headers $Headers
        $line = Get-Content -LiteralPath $sumsPath | Where-Object { $_ -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$' -and $Matches[2] -eq $whl.name } | Select-Object -First 1
        if (-not $line) { throw "$($whl.name) est absent de SHA256SUMS : installation refusée." }
        $null = $line -match '^([0-9a-fA-F]{64})'
        $expected = $Matches[1].ToLowerInvariant()
        $actual = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "SHA-256 différent pour $($whl.name) (attendu $expected, obtenu $actual) : fichier rejeté, rien n'a été installé." }
        Ok "SHA-256 vérifié ($actual)"
        return $wheelPath
    }

    $work = Join-Path ([IO.Path]::GetTempPath()) ('omniscient-install-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    try {
        Write-Host ''
        Write-Host 'Omniscient - installation' -ForegroundColor White

        # ---- 1. uv ------------------------------------------------------------------
        Step 1 'uv (gestionnaire Python)'
        Update-SessionPath
        if (Test-Uv) {
            Ok 'uv est déjà installé.'
        } else {
            if (Get-Command winget -ErrorAction SilentlyContinue) {
                Info 'Installation de uv avec winget...'
                $null = Invoke-Native 'winget' @('install', '--id', 'astral-sh.uv', '-e', '--silent', '--accept-package-agreements', '--accept-source-agreements')
                Update-SessionPath
            }
            if (-not (Test-Uv)) {
                Info "Installation de uv avec l'installeur officiel (astral.sh)..."
                $null = Invoke-Native 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'ByPass', '-Command', 'irm https://astral.sh/uv/install.ps1 | iex')
                Update-SessionPath
            }
            if (-not (Test-Uv)) {
                throw "uv n'a pas pu être installé. Installe-le à la main (https://docs.astral.sh/uv/), puis relance ce script."
            }
            Ok 'uv installé.'
        }

        # ---- 2. moteur --------------------------------------------------------------
        Step 2 'Moteur Omniscient (sans git)'
        if ($Wheel) {
            if (-not (Test-Path -LiteralPath $Wheel -PathType Leaf) -or -not $Wheel.EndsWith('.whl')) { throw "-Wheel : roue introuvable : $Wheel" }
            $wheelPath = (Resolve-Path -LiteralPath $Wheel).Path
            Warn "Roue locale (pas de vérification SHA-256) : $wheelPath"
        } else {
            $wheelPath = Get-LatestWheel $work
        }
        Stop-Daemon
        Info 'Installation (uv télécharge Python 3.12+ si besoin)...'
        if ((Invoke-Native 'uv' @('tool', 'install', '--force', $wheelPath)) -ne 0) { throw "uv n'a pas pu installer le moteur (voir ci-dessus)." }
        $null = Invoke-Native 'uv' @('tool', 'update-shell') -Quiet
        $bin = ((& uv tool dir --bin) | Out-String).Trim()
        $omni = Join-Path $bin 'omniscient.exe'
        if (-not (Test-Path -LiteralPath $omni)) { throw "omniscient.exe est introuvable dans $bin après l'installation." }
        if (-not ($env:Path.ToLowerInvariant().Split(';') -contains $bin.TrimEnd('\').ToLowerInvariant())) { $env:Path = "$bin;$env:Path" }
        if ((Invoke-Native $omni @('--version')) -ne 0) { throw "omniscient --version a échoué." }
        Ok 'Moteur installé.'

        # ---- 3. démon ---------------------------------------------------------------
        Step 3 "Démon (démarrage à l'ouverture de session)"
        if ($NoAutostart) {
            Info '-NoAutostart : pas de démarrage automatique.'
        } elseif ((Invoke-Native $omni @('group', 'autostart', 'install', '--write', '--port', "$Port")) -eq 0) {
            Ok 'Le démon démarrera à chaque ouverture de session (sans droits administrateur).'
        } else {
            Warn "Démarrage automatique non activé : lance 'omniscient group serve' à la main quand tu en as besoin."
        }
        # A hidden process hides its errors: test the port first (busy, or reserved by Windows).
        if ((Invoke-Native $omni @('group', 'serve', '--check-port', '--port', "$Port")) -ne 0) {
            throw "Le port $Port est inutilisable pour le démon (voir ci-dessus) : relance avec un autre port, par exemple -Port $($Port + 10)."
        }
        if ($Port -ne 7341) {
            [Environment]::SetEnvironmentVariable('OMNIGROUP_URL', "http://127.0.0.1:$Port", 'User')
            $env:OMNIGROUP_URL = "http://127.0.0.1:$Port"
            Warn "Port $Port : dans le widget, Réglages > Adresse du démon doit être http://127.0.0.1:$Port. Les hooks suivent la variable OMNIGROUP_URL (rouvre Claude Code)."
        }
        Start-Process -FilePath $omni -ArgumentList @('group', 'serve', '--port', "$Port") -WindowStyle Hidden
        $up = $false
        for ($i = 0; $i -lt 30 -and -not $up; $i++) {
            Start-Sleep -Seconds 2
            $up = ((Invoke-Native $omni @('group', 'status', '--port', "$Port") -Quiet) -eq 0)
        }
        if (-not $up) { throw "Le démon ne répond pas sur le port $Port. Lance 'omniscient group serve' dans un terminal pour voir l'erreur." }
        Ok "Le démon répond sur http://127.0.0.1:$Port."

        # ---- 4. hooks + widget ------------------------------------------------------
        Step 4 'Hooks Claude Code et widget Omnigroup'
        $setupArgs = @('group', 'setup', '--write', '--port', "$Port")
        $widgetDir = Join-Path $work 'widget'
        if ($SkipWidget -or $Installer) { $setupArgs += '--skip-widget' } else { $setupArgs += @('--widget-dir', $widgetDir, '--update-widget') }
        if ((Invoke-Native $omni $setupArgs) -ne 0) { throw "omniscient group setup a échoué (voir ci-dessus)." }
        if ($SkipWidget) {
            Info '-SkipWidget : widget non installé.'
        } else {
            if ($Installer) {
                if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw "-Installer : fichier introuvable : $Installer" }
                $exe = (Resolve-Path -LiteralPath $Installer).Path
            } else {
                $found = Get-ChildItem -LiteralPath $widgetDir -Filter 'Omnigroup_*-setup.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
                if (-not $found) { throw "L'installeur du widget n'a pas été téléchargé ou vérifié (voir les messages ci-dessus)." }
                $exe = $found.FullName
            }
            Get-Process -Name 'omnigroup' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            Info "Installation silencieuse de $(Split-Path -Leaf $exe) (pour ton utilisateur uniquement)..."
            $proc = Start-Process -FilePath $exe -ArgumentList '/S' -Wait -PassThru
            if ($proc.ExitCode -ne 0) { throw "L'installeur du widget a échoué (code $($proc.ExitCode))." }
            $app = Find-WidgetExe
            if (-not $app) {
                $seen = (Get-ChildItem -Path "$env:LOCALAPPDATA\*mnigroup*", "$env:ProgramFiles\*mnigroup*", "$env:LOCALAPPDATA\Programs\*" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }) -join '; '
                throw "Le widget n'est pas installé : omnigroup.exe est introuvable (installeur : code $($proc.ExitCode)). Vu : $seen"
            }
            Ok "Widget installé : $app (menu Démarrer > Omnigroup)."
        }

        # ---- 5. etat ----------------------------------------------------------------
        Step 5 'État'
        $null = Invoke-Native $omni @('group', 'status', '--port', "$Port")

        Write-Host ''
        Write-Host 'Et maintenant' -ForegroundColor Green
        if ($app -and -not $NoLaunch) {
            Start-Process -FilePath $app
            Write-Host '  Le widget Omnigroup vient de s''ouvrir en bas à droite de l''écran.'
        } elseif ($app) {
            Write-Host '  Ouvre Omnigroup depuis le menu Démarrer : le widget s''ouvre en bas à droite de l''écran.'
        }
        Write-Host '  Si le widget affiche un code à taper, saisis les 6 chiffres affichés sur ton bureau.'
        Write-Host ''
        Write-Host "  Pour mettre à jour : relance la même commande. Désinstallation : docs/install.md."
        return $true
    } catch {
        Write-Host ''
        Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Rien de grave : tu peux relancer la commande après avoir corrigé. Aide : https://github.com/$Repo/blob/main/docs/install.md" -ForegroundColor Yellow
        if ($omni -and (Test-Path -LiteralPath $omni)) {
            Write-Host "Pour demander de l'aide : lance `"omniscient group doctor`" et colle le résultat (rien de secret n'y figure)." -ForegroundColor Yellow
        } else {
            Write-Host "Une fois le moteur installé, `"omniscient group doctor`" donne un diagnostic à coller dans un rapport." -ForegroundColor Yellow
        }
        return $false
    } finally {
        $env:PYTHONUTF8 = $savedEnv.PYTHONUTF8
        $env:PYTHONIOENCODING = $savedEnv.PYTHONIOENCODING
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$installed = Install-Omniscient -Wheel $Wheel -Installer $Installer -SkipWidget $wantSkipWidget -NoAutostart $wantNoAutostart -NoLaunch $wantNoLaunch -RequestedPort $Port
if ($installed) {
    $global:LASTEXITCODE = 0
} else {
    $global:LASTEXITCODE = 1
    # `exit` would close the window of someone who pasted the one-liner in an open
    # PowerShell session (no script path there); only exit when run as a file.
    if ($PSCommandPath) { exit 1 }
}
