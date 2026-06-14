# install_windows.ps1 — setup complet FL Studio MCP sur Windows
#
# Ce script fait tout ce qui peut etre automatise. Apres son execution,
# il reste 3 etapes manuelles rapides (affichees a la fin).
#
# Usage : depuis le dossier racine du repo :
#   .\scripts\install_windows.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== FL Studio MCP — Installation Windows ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Copier le bridge dans FL Studio Settings ---

$flSettings = if (Test-Path "D:\Image-Line\FL Studio\Settings") {
    "D:\Image-Line\FL Studio\Settings"
} elseif (Test-Path (Join-Path $env:USERPROFILE "Documents\Image-Line\FL Studio\Settings")) {
    Join-Path $env:USERPROFILE "Documents\Image-Line\FL Studio\Settings"
} else {
    $null
}

if (-not $flSettings) {
    Write-Host "[ERREUR] Dossier FL Studio Settings introuvable." -ForegroundColor Red
    Write-Host "  Installez FL Studio 2025, puis relancez ce script."
    exit 1
}

$bridgeDest = Join-Path $flSettings "Hardware\fLMCP Bridge"
New-Item -ItemType Directory -Force $bridgeDest | Out-Null

$bridgeSrc = Join-Path $PSScriptRoot "..\bridge\device_FLStudioMCP.py"
if (-not (Test-Path $bridgeSrc)) {
    Write-Host "[ERREUR] Fichier bridge introuvable : $bridgeSrc" -ForegroundColor Red
    exit 1
}

Copy-Item $bridgeSrc $bridgeDest -Force
Write-Host "[OK] Bridge installe :" -ForegroundColor Green
Write-Host "     $bridgeDest\device_FLStudioMCP.py"

# --- 2. Verifier LoopMIDI ---

Write-Host ""
$loopMidi = Get-ItemProperty "HKLM:\SOFTWARE\Tobias Erichsen\loopMIDI" -ErrorAction SilentlyContinue
if ($loopMidi) {
    Write-Host "[OK] loopMIDI detecte dans le registre." -ForegroundColor Green
} else {
    # Essayer via liste des apps installees
    $apps = Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue
    $lm = $apps | Where-Object { $_.DisplayName -like "*loopMIDI*" } | Select-Object -First 1
    if ($lm) {
        Write-Host "[OK] loopMIDI installe : $($lm.DisplayVersion)" -ForegroundColor Green
    } else {
        Write-Host "[ACTION REQUISE] loopMIDI n'est pas installe." -ForegroundColor Yellow
        Write-Host "  Telecharger sur : https://www.tobias-erichsen.de/software/loopmidi.html"
        Write-Host "  Creer un port nomme 'fLMCP' apres installation."
    }
}

# --- 3. Installer les dependances Python ---

Write-Host ""
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$pipResult = python -m pip install -e "$repoRoot" --quiet 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Package Python installe (pip install -e .)" -ForegroundColor Green
} else {
    Write-Host "[AVERTISSEMENT] pip install a echoue. Lancez manuellement :" -ForegroundColor Yellow
    Write-Host "  cd `"$repoRoot`""
    Write-Host "  pip install -e ."
}

# --- 4. Verifier que le template existe ---

Write-Host ""
$templatePath = Join-Path $repoRoot "template\MCP_Template.flp"
if (Test-Path $templatePath) {
    Write-Host "[OK] Template trouve : $templatePath" -ForegroundColor Green
} else {
    Write-Host "[INFO] Template absent (normal au premier clone)." -ForegroundColor Yellow
    Write-Host "  Creer le template en suivant : template\TEMPLATE-GUIDE.md"
    Write-Host "  Le committer dans le repo une fois cree."
}

# --- 5. Afficher les etapes manuelles restantes ---

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Etapes manuelles restantes (~4 min total)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Configurer LoopMIDI (si pas encore fait)" -ForegroundColor Yellow
Write-Host "   Ouvrir loopMIDI > ajouter un port nomme : fLMCP"
Write-Host ""
Write-Host "2. Configurer FL Studio MIDI (une seule fois par installation)" -ForegroundColor Yellow
Write-Host "   Options > Parametres MIDI"
Write-Host "   ENTREE  : ligne fLMCP > Type controleur = 'fLMCP Bridge' > Port 1 > Activer"
Write-Host "   SORTIE  : ligne fLMCP > Port 1 (laisser desactive cote sortie FL)"
Write-Host "   Note : fLMCP In > port 1 en entree / fLMCP Out desactive en sortie FL"
Write-Host ""
Write-Host "3. Ouvrir le template dans FL Studio" -ForegroundColor Yellow
Write-Host "   Fichier > Ouvrir > $templatePath"
Write-Host "   (Creer le template d'abord si absent — voir template\TEMPLATE-GUIDE.md)"
Write-Host ""
Write-Host "4. Ajouter le serveur MCP a Claude Desktop (claude_desktop_config.json) :" -ForegroundColor Yellow
Write-Host @"
  "fl-studio": {
    "command": "python",
    "args": ["-m", "fl_studio_mcp"],
    "cwd": "$repoRoot",
    "env": { "FLMCP_TRANSPORT": "midi" }
  }
"@
Write-Host ""
Write-Host "5. Redemarrer Claude Desktop, puis valider avec l'outil fl_ping." -ForegroundColor Yellow
Write-Host ""
Write-Host "[DONE] Installation automatique terminee." -ForegroundColor Green
