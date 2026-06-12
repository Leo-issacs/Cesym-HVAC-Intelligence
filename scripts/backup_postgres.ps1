# backup_postgres.ps1
# Backup de los schemas de produccion (analytics + chatbot) ANTES de cualquier
# escritura. pg_dump en formato custom (-Fc) via la conexion DIRECTA (5432),
# archivo fechado, subida best-effort a Google Drive y retencion local de 30 dias.
#
# NOTA: archivo en ASCII puro a proposito. Windows PowerShell 5.1 lee los .ps1
# sin BOM como ANSI (CP1252); acentos, em-dash y flechas se decodifican como
# comillas tipograficas y rompen el parseo. No metas caracteres no-ASCII aqui.
#
# USO:
#   .\scripts\backup_postgres.ps1
#   .\scripts\backup_postgres.ps1 -SkipUpload      # solo dump local, sin Drive
#
# Exit codes: 0 = dump local OK (la subida a Drive es best-effort y no aborta).
#             1 = pg_dump no encontrado, o el dump fallo (NO continuar con writes).

param(
    [switch]$SkipUpload,
    [string]$BackupDir
)

$ErrorActionPreference = "Stop"

$ROOT     = $PSScriptRoot | Split-Path -Parent
$VENV_PY  = Join-Path $ROOT "cesym_data_analytics\Scripts\python.exe"
$SCHEMAS  = @("analytics", "chatbot")
$RETENCION_DIAS = 30
if (-not $BackupDir) { $BackupDir = Join-Path $ROOT "backups" }

function Write-Sep { Write-Host ("-" * 62) -ForegroundColor DarkGray }

# -- Cargar .env al proceso (mismo patron que sync_maestro.ps1) ----------------
function Import-DotEnv($envFile) {
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | Where-Object { $_ -match '^\s*([^#][^=]+)=(.*)$' } | ForEach-Object {
        $key, $value = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process')
    }
}

# -- Localizar pg_dump / pg_restore (PATH o instalacion estandar de Windows) ----
function Resolve-PgTool($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidatos = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$name.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending   # mayor version primero
    if ($candidatos) { return $candidatos[0].FullName }
    return $null
}

function Show-InstallInstructions {
    Write-Host ""
    Write-Host "ERROR: pg_dump no esta instalado." -ForegroundColor Red
    Write-Host "El servidor es PostgreSQL 17.x, asi que necesitas el cliente v17." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Instalacion en Windows (elige una):" -ForegroundColor Cyan
    Write-Host "  1) winget (recomendado):"
    Write-Host "       winget install -e --id PostgreSQL.PostgreSQL.17"
    Write-Host "     Instala pg_dump.exe / pg_restore.exe en:"
    Write-Host "       C:\Program Files\PostgreSQL\17\bin"
    Write-Host ""
    Write-Host "  2) Binarios sin instalador:"
    Write-Host "       https://www.enterprisedb.com/download-postgresql-binaries"
    Write-Host "       Descarga el zip de PostgreSQL 17 (Windows x86-64),"
    Write-Host "       extrae y usa la carpeta bin\."
    Write-Host ""
    Write-Host "Tras instalar, abre una PowerShell NUEVA (para refrescar el PATH)" -ForegroundColor Yellow
    Write-Host "o este script lo detectara en C:\Program Files\PostgreSQL\17\bin." -ForegroundColor Yellow
    Write-Host ""
}

# ==============================================================================
Write-Sep
Write-Host "  BACKUP POSTGRES  -  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Sep

Import-DotEnv (Join-Path $ROOT ".env")

$pgDump = Resolve-PgTool "pg_dump"
if (-not $pgDump) { Show-InstallInstructions; exit 1 }
$pgRestore = Resolve-PgTool "pg_restore"
Write-Host "pg_dump: $pgDump" -ForegroundColor Green
& $pgDump --version

# -- Conexion DIRECTA (5432), nunca el pooler ----------------------------------
$url = $env:DATABASE_MIGRATION_URL
if (-not $url) {
    Write-Host "ERROR: DATABASE_MIGRATION_URL no esta definida en .env." -ForegroundColor Red
    Write-Host "Debe ser la conexion DIRECTA (puerto 5432), no el pooler (6543)." -ForegroundColor Yellow
    exit 1
}
if ($url -notmatch ":5432/") {
    Write-Host "ERROR: DATABASE_MIGRATION_URL no apunta al puerto 5432 (directa)." -ForegroundColor Red
    Write-Host "pg_dump debe usar la conexion directa, no el pooler de transacciones." -ForegroundColor Yellow
    exit 1
}

# -- Ejecutar el dump ----------------------------------------------------------
New-Item -ItemType Directory -Force $BackupDir | Out-Null
$stamp   = Get-Date -Format "yyyy-MM-dd_HHmmss"
$outFile = Join-Path $BackupDir "cesym_pg_backup_$stamp.dump"

$schemaArgs = @()
foreach ($s in $SCHEMAS) { $schemaArgs += @("--schema=$s") }

Write-Host "`nDump de schemas [$($SCHEMAS -join ', ')] -> $($outFile | Split-Path -Leaf)" -ForegroundColor Yellow
& $pgDump --format=custom --compress=9 --no-owner --no-privileges `
    @schemaArgs --file=$outFile $url
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pg_dump fallo (codigo $LASTEXITCODE). No se genero backup valido." -ForegroundColor Red
    if (Test-Path $outFile) { Remove-Item $outFile -Force }
    exit 1
}

# -- Validar que el archivo es un dump legible ---------------------------------
if (-not (Test-Path $outFile) -or (Get-Item $outFile).Length -eq 0) {
    Write-Host "ERROR: el dump no se creo o esta vacio." -ForegroundColor Red
    exit 1
}
if ($pgRestore) {
    & $pgRestore --list $outFile | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: pg_restore --list no pudo leer el dump (archivo corrupto)." -ForegroundColor Red
        exit 1
    }
}
$sizeKb = [math]::Round((Get-Item $outFile).Length / 1KB, 1)
Write-Host "  OK  dump valido: $outFile  ($sizeKb KB)" -ForegroundColor Green

# -- Subida a Drive (best-effort: no aborta el backup local) -------------------
if (-not $SkipUpload) {
    if (Test-Path $VENV_PY) {
        Write-Host "`nSubiendo a Google Drive..." -ForegroundColor Yellow
        & $VENV_PY -X utf8 (Join-Path $ROOT "scripts\drive_upload.py") $outFile
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  AVISO: la subida a Drive fallo. El backup LOCAL si se creo." -ForegroundColor DarkYellow
            Write-Host "         Revisa scripts/drive_upload.py y docs/runbooks/restore.md." -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "  AVISO: venv no encontrado ($VENV_PY); se omite la subida a Drive." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "`n(-SkipUpload) Subida a Drive omitida." -ForegroundColor DarkGray
}

# -- Retencion local: borrar dumps con mas de 30 dias --------------------------
$viejos = Get-ChildItem $BackupDir -Filter "cesym_pg_backup_*.dump" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RETENCION_DIAS) }
if ($viejos) {
    Write-Host "`nRetencion: borrando $($viejos.Count) backup(s) > $RETENCION_DIAS dias" -ForegroundColor DarkGray
    $viejos | Remove-Item -Force
}

Write-Sep
Write-Host "  BACKUP COMPLETADO." -ForegroundColor Green
Write-Sep
exit 0
