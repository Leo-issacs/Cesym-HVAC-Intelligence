# test_restore.ps1
# Verifica que un backup de pg_dump es RESTAURABLE de verdad: restaura el schema
# `analytics` del dump en un schema temporal `analytics_restore_test`, compara los
# conteos de filas contra el `analytics` original, y borra el schema temporal.
#
# Es seguro contra produccion: el SQL restaurado se reescribe para apuntar SOLO a
# analytics_restore_test, y se ABORTA si queda cualquier referencia a `analytics.`
# antes de aplicar nada (asi un restore jamas puede escribir sobre produccion).
#
# ASCII puro a proposito (ver nota en backup_postgres.ps1).
#
# USO:
#   .\scripts\test_restore.ps1                       # usa el dump mas reciente
#   .\scripts\test_restore.ps1 -DumpFile <ruta>      # un dump especifico
#
# Exit codes: 0 = restore verificado (conteos coinciden) | 1 = fallo.

param(
    [string]$DumpFile
)

$ErrorActionPreference = "Stop"
$env:PGCLIENTENCODING = "UTF8"   # los datos son UTF-8 (texto en espanol)

$ROOT = $PSScriptRoot | Split-Path -Parent
$TEST_SCHEMA = "analytics_restore_test"

function Write-Sep { Write-Host ("-" * 62) -ForegroundColor DarkGray }

function Import-DotEnv($envFile) {
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | Where-Object { $_ -match '^\s*([^#][^=]+)=(.*)$' } | ForEach-Object {
        $key, $value = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process')
    }
}

function Resolve-PgTool($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $c = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$name.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($c) { return $c[0].FullName }
    return $null
}

Write-Sep
Write-Host "  TEST DE RESTORE  -  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Sep

Import-DotEnv (Join-Path $ROOT ".env")
$url = $env:DATABASE_MIGRATION_URL
if (-not $url -or $url -notmatch ":5432/") {
    Write-Host "ERROR: DATABASE_MIGRATION_URL (directa 5432) no esta configurada." -ForegroundColor Red
    exit 1
}

$pgRestore = Resolve-PgTool "pg_restore"
$psql      = Resolve-PgTool "psql"
if (-not $pgRestore -or -not $psql) {
    Write-Host "ERROR: pg_restore/psql no encontrados. Instala el cliente PostgreSQL 17." -ForegroundColor Red
    Write-Host "  winget install -e --id PostgreSQL.PostgreSQL.17" -ForegroundColor Yellow
    exit 1
}

# -- Elegir el dump a verificar ------------------------------------------------
if (-not $DumpFile) {
    $latest = Get-ChildItem (Join-Path $ROOT "backups") -Filter "cesym_pg_backup_*.dump" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Write-Host "ERROR: no hay dumps en backups/." -ForegroundColor Red; exit 1 }
    $DumpFile = $latest.FullName
}
if (-not (Test-Path $DumpFile)) { Write-Host "ERROR: no existe $DumpFile" -ForegroundColor Red; exit 1 }
Write-Host "Dump a verificar: $DumpFile" -ForegroundColor Green

$tmpRaw      = Join-Path $env:TEMP "_restore_raw.sql"
$tmpRenamed  = Join-Path $env:TEMP "_restore_renamed.sql"
$tmpVerify   = Join-Path $env:TEMP "_restore_verify.sql"
$utf8NoBom   = New-Object System.Text.UTF8Encoding $false

try {
    # -- 1. Extraer SOLO el schema analytics del dump como SQL -----------------
    Write-Host "`n[1/5] Extrayendo schema analytics del dump..." -ForegroundColor Yellow
    & $pgRestore --schema=analytics --no-owner --no-privileges -f $tmpRaw $DumpFile
    if ($LASTEXITCODE -ne 0) { throw "pg_restore no pudo leer el dump." }

    # -- 2. Reescribir analytics -> analytics_restore_test + safety assert ------
    Write-Host "[2/5] Reescribiendo a $TEST_SCHEMA y validando seguridad..." -ForegroundColor Yellow
    $sql = [System.IO.File]::ReadAllText($tmpRaw, [System.Text.Encoding]::UTF8)
    $sql = $sql -replace '\banalytics\b', $TEST_SCHEMA
    $leftover = [regex]::Matches($sql, '\banalytics\b').Count
    if ($leftover -ne 0) {
        throw "ABORTADO: quedan $leftover referencias a 'analytics' tras el rename. " +
              "No se aplica nada para no arriesgar produccion."
    }
    [System.IO.File]::WriteAllText($tmpRenamed, $sql, $utf8NoBom)

    # -- 3. Crear schema temporal limpio y aplicar el restore ------------------
    Write-Host "[3/5] Restaurando en schema temporal $TEST_SCHEMA..." -ForegroundColor Yellow
    & $psql $url --no-psqlrc -v ON_ERROR_STOP=1 -q `
        -c "DROP SCHEMA IF EXISTS $TEST_SCHEMA CASCADE; CREATE SCHEMA $TEST_SCHEMA;"
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el schema temporal." }
    & $psql $url --no-psqlrc -v ON_ERROR_STOP=1 -q -f $tmpRenamed
    if ($LASTEXITCODE -ne 0) { throw "El restore al schema temporal fallo." }

    # -- 4. Verificar conteos contra el analytics original ---------------------
    Write-Host "[4/5] Verificando conteos vs analytics original..." -ForegroundColor Yellow
    $verify = @"
DO `$`$
DECLARE r record; a bigint; b bigint;
BEGIN
  FOR r IN SELECT table_name FROM information_schema.tables
           WHERE table_schema='analytics' AND table_type='BASE TABLE' ORDER BY table_name
  LOOP
    EXECUTE format('SELECT count(*) FROM analytics.%I', r.table_name) INTO a;
    EXECUTE format('SELECT count(*) FROM $TEST_SCHEMA.%I', r.table_name) INTO b;
    RAISE NOTICE 'tabla %: original=% restaurado=%', r.table_name, a, b;
    IF a <> b THEN
      RAISE EXCEPTION 'MISMATCH en %: original=% restaurado=%', r.table_name, a, b;
    END IF;
  END LOOP;
  RAISE NOTICE 'OK: todos los conteos coinciden.';
END `$`$;
"@
    [System.IO.File]::WriteAllText($tmpVerify, $verify, $utf8NoBom)
    & $psql $url --no-psqlrc -v ON_ERROR_STOP=1 -f $tmpVerify
    if ($LASTEXITCODE -ne 0) { throw "La verificacion de conteos fallo (mismatch)." }

    Write-Host "`n[5/5] RESTORE VERIFICADO: el dump es restaurable y los conteos coinciden." -ForegroundColor Green
    $ok = $true
}
catch {
    Write-Host "`nFALLO: $_" -ForegroundColor Red
    $ok = $false
}
finally {
    # -- Limpieza: borrar SIEMPRE el schema temporal y los archivos ------------
    Write-Host "Limpiando schema temporal $TEST_SCHEMA..." -ForegroundColor DarkGray
    & $psql $url --no-psqlrc -q -c "DROP SCHEMA IF EXISTS $TEST_SCHEMA CASCADE;" | Out-Null
    foreach ($f in @($tmpRaw, $tmpRenamed, $tmpVerify)) {
        if (Test-Path $f) { Remove-Item $f -Force }
    }
}

Write-Sep
if ($ok) { Write-Host "  TEST DE RESTORE: PASS" -ForegroundColor Green; exit 0 }
else     { Write-Host "  TEST DE RESTORE: FAIL" -ForegroundColor Red;   exit 1 }
