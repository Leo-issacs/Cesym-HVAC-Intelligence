# sync_maestro.ps1
# Sincroniza Google Drive para ambos proyectos en una sola ejecución.
#
# USO:
#   .\scripts\sync_maestro.ps1
#   .\scripts\sync_maestro.ps1 -DryRun

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$HVAC_DIR    = $PSScriptRoot | Split-Path -Parent
$HVAC_PY     = Join-Path $HVAC_DIR "cesym_data_analytics\Scripts\python.exe"
$CHATBOT_DIR = "C:\Users\leona\Personal\Works\Programacion\Projects\Cesym Chatbot"
$CHATBOT_PY  = Join-Path $CHATBOT_DIR "venv_Cesym_Chatbot\Scripts\python.exe"

$flag = if ($DryRun) { "--dry-run" } else { $null }

# ── Carga un archivo .env y exporta sus variables al proceso actual ────────────
function Import-DotEnv($envFile) {
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | Where-Object { $_ -match '^\s*([^#][^=]+)=(.*)$' } | ForEach-Object {
        $key, $value = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process')
    }
}

# ── Separador ─────────────────────────────────────────────────────────────────
function Write-Sep { Write-Host ("=" * 60) -ForegroundColor Cyan }

Write-Sep
Write-Host "  SYNC MAESTRO  —  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Sep

# ── 1. HVAC ───────────────────────────────────────────────────────────────────
Write-Host "`n[1/2] HVAC AI System" -ForegroundColor Yellow
Import-DotEnv (Join-Path $HVAC_DIR ".env")
Push-Location $HVAC_DIR
try {
    if ($flag) {
        & $HVAC_PY -X utf8 scripts\sync_drive.py $flag
    } else {
        & $HVAC_PY -X utf8 scripts\sync_drive.py
    }
    if ($LASTEXITCODE -ne 0) { throw "sync_drive.py de HVAC termino con error (codigo $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ── 2. Cesym Chatbot ──────────────────────────────────────────────────────────
Write-Host "`n[2/2] Cesym Chatbot" -ForegroundColor Yellow
Import-DotEnv (Join-Path $CHATBOT_DIR ".env")
Push-Location $CHATBOT_DIR
try {
    if ($flag) {
        & $CHATBOT_PY -X utf8 scripts\sync_drive.py $flag
    } else {
        & $CHATBOT_PY -X utf8 scripts\sync_drive.py
    }
    if ($LASTEXITCODE -ne 0) { throw "sync_drive.py del Chatbot terminó con error (código $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ── Resultado ─────────────────────────────────────────────────────────────────
Write-Sep
Write-Host "  Sincronización completa." -ForegroundColor Green
Write-Sep
