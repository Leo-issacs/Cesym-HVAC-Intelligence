# sync_maestro.ps1
# Backup de produccion PRIMERO, luego sincroniza Google Drive para ambos
# proyectos. El backup va antes que cualquier ETL: el lunes 7 AM siempre existe
# una restauracion previa a cualquier escritura. Si el backup falla, se ABORTA y
# NO se ejecuta ningun sync (no se escribe sin respaldo).
#
# NOTA: ASCII puro a proposito. Windows PowerShell 5.1 lee los .ps1 sin BOM como
# ANSI (CP1252); acentos, em-dash y flechas se decodifican como comillas
# tipograficas y rompen el parseo. No metas caracteres no-ASCII aqui.
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

# -- Carga un archivo .env y exporta sus variables al proceso actual -----------
function Import-DotEnv($envFile) {
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | Where-Object { $_ -match '^\s*([^#][^=]+)=(.*)$' } | ForEach-Object {
        $key, $value = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process')
    }
}

function Write-Sep { Write-Host ("=" * 60) -ForegroundColor Cyan }

Write-Sep
Write-Host "  SYNC MAESTRO  -  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Sep

# -- 1. BACKUP PRIMERO (analytics + chatbot, una sola DB) ----------------------
# Corre en su propio proceso para aislar su exit code. Si falla, abortamos: no
# se escribe en produccion sin un respaldo del dia.
Write-Host "`n[1/3] Backup de Postgres (antes de cualquier escritura)" -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  (dry-run) backup omitido." -ForegroundColor DarkGray
} else {
    $backupScript = Join-Path $HVAC_DIR "scripts\backup_postgres.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupScript
    if ($LASTEXITCODE -ne 0) {
        throw "Backup fallo (codigo $LASTEXITCODE). Se ABORTA el sync: no se escribe sin respaldo."
    }
}

# -- 2. HVAC -------------------------------------------------------------------
Write-Host "`n[2/3] HVAC AI System" -ForegroundColor Yellow
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

# -- 3. Cesym Chatbot ----------------------------------------------------------
Write-Host "`n[3/3] Cesym Chatbot" -ForegroundColor Yellow
Import-DotEnv (Join-Path $CHATBOT_DIR ".env")
Push-Location $CHATBOT_DIR
try {
    if ($flag) {
        & $CHATBOT_PY -X utf8 scripts\sync_drive.py $flag
    } else {
        & $CHATBOT_PY -X utf8 scripts\sync_drive.py
    }
    if ($LASTEXITCODE -ne 0) { throw "sync_drive.py del Chatbot termino con error (codigo $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Sep
Write-Host "  Sincronizacion completa." -ForegroundColor Green
Write-Sep
