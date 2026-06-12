# install_windows.ps1 - copie le bridge dans le dossier Hardware de FL Studio.
#
# Le bridge s'enregistre aupres de FL Studio comme un controleur MIDI nomme
# "fLMCP Bridge" (ligne `# name=fLMCP Bridge` en tete de device_FLStudioMCP.py).
# Une fois actif, il ouvre un serveur TCP sur 127.0.0.1:9876 que le serveur MCP
# (fl_studio_mcp) utilise pour piloter FL Studio.

$ErrorActionPreference = "Stop"

$flSettings = Join-Path $env:USERPROFILE "Documents\Image-Line\FL Studio\Settings"
$target = Join-Path $flSettings "Hardware\fLMCP Bridge"

if (-not (Test-Path $flSettings)) {
    Write-Error "FL Studio settings folder not found: $flSettings (install FL Studio first)"
}

New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $PSScriptRoot "..\bridge\device_FLStudioMCP.py") $target -Force

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Bridge installed to: $target" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Restart FL Studio (or rescan: Options > MIDI Settings > Refresh device list)"
Write-Host "2. Options > MIDI Settings > Input: enable an input row and set"
Write-Host "   Controller type = 'fLMCP Bridge' (the TCP server on 127.0.0.1:9876"
Write-Host "   starts as soon as the script initialises)"
Write-Host "3. Add the MCP server to Claude Desktop config (claude_desktop_config.json):"
Write-Host "   `"fl-studio`": {`"command`": `"python`", `"args`": [`"-m`", `"fl_studio_mcp`"], `"cwd`": `"$repoRoot`"}"
Write-Host "4. Restart Claude Desktop, then validate with the fl_ping tool"
