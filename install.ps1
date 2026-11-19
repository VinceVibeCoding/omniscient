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
#   -NoAutostart         ne pas créer la tâche de démarrage à l'ouverture de session
param(
    [string]$Wheel = '',
    [string]$Installer = '',
    [switch]$SkipWidget,
    [switch]$NoAutostart
)

function Install-Omniscient {
    param([string]$Wheel, [string]$Installer, [bool]$SkipWidget, [bool]$NoAutostart)

    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    $Repo = 'VinceVibeCoding/omniscient'
    $Total = 5
    $Port = 7341
    $Headers = @{ 'User-Agent' = 'omniscient-install'; 'Accept' = 'application/vnd.github+json' }

    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
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
        $null = Invoke-Native 'schtasks' @('/End', '/TN', 'Omnigroup') -Quiet
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -match 'omniscient' -and $_.CommandLine -match 'group\s+serve' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }

    # Per-user NSIS install: %LOCALAPPDATA%\Omnigroup or %LOCALAPPDATA%\Programs\Omnigroup
    # depending on the installer; fall back to a shallow search so a layout change is found.
    function Find-WidgetExe {
        foreach ($rel in 'Omnigroup\omnigroup.exe', 'Programs\Omnigroup\omnigroup.exe') {
            $candidate = Join-Path $env:LOCALAPPDATA $rel
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
        $hit = Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Filter 'omnigroup.exe' -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
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
            Info '-NoAutostart : pas de tache planifiee.'
        } elseif ((Invoke-Native $omni @('group', 'autostart', 'install', '--write')) -eq 0) {
            Ok "Le démon démarrera à chaque ouverture de session (tâche planifiée 'Omnigroup', sans droits admin)."
        } else {
            Warn "Tâche planifiée refusée : lance 'omniscient group serve' à la main quand tu en as besoin."
        }
        Start-Process -FilePath $omni -ArgumentList @('group', 'serve') -WindowStyle Hidden
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
                $dirs = (Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ', '
                throw "Le widget n'est pas installé : omnigroup.exe est introuvable sous $env:LOCALAPPDATA (dossiers : $dirs)."
            }
            Ok "Widget installé : $app (menu Démarrer > Omnigroup)."
        }

        # ---- 5. etat ----------------------------------------------------------------
        Step 5 'État'
        $null = Invoke-Native $omni @('group', 'status', '--port', "$Port")

        Write-Host ''
        Write-Host 'Et maintenant' -ForegroundColor Green
        Write-Host '  1. Ouvre Omnigroup (menu Démarrer).'
        Write-Host '  2. Va dans Réglages > Demander un code.'
        Write-Host '  3. Tape le code à 6 chiffres affiché sur ton bureau.'
        Write-Host ''
        Write-Host "  Pour mettre à jour : relance la même commande. Désinstallation : docs/install.md."
        return $true
    } catch {
        Write-Host ''
        Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Rien de grave : tu peux relancer la commande après avoir corrigé. Aide : https://github.com/$Repo/blob/main/docs/install.md" -ForegroundColor Yellow
        return $false
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$installed = Install-Omniscient -Wheel $Wheel -Installer $Installer -SkipWidget ([bool]$SkipWidget) -NoAutostart ([bool]$NoAutostart)
if ($installed) {
    $global:LASTEXITCODE = 0
} else {
    $global:LASTEXITCODE = 1
    # `exit` would close the window of someone who pasted the one-liner in an open
    # PowerShell session (no script path there); only exit when run as a file.
    if ($PSCommandPath) { exit 1 }
}
