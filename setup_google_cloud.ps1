# setup_google_cloud.ps1
#
# Crea el proyecto de Google Cloud, habilita Drive API,
# genera la Service Account y descarga las credenciales.
#
# USO:
#   1. Abre PowerShell y ejecuta:  gcloud auth login
#      (se abre el navegador — inicia sesión con tu cuenta de Google)
#   2. Luego ejecuta este script:  .\setup_google_cloud.ps1

$ErrorActionPreference = "Stop"

$PROJECT_ID     = "cesym-hvac-$(Get-Random -Maximum 9999)"   # ID único
$SA_NAME        = "cesym-sync"
$CREDS_PATH     = "credentials\service_account.json"
$ENV_FILE       = ".env"

Write-Host ""
Write-Host "=== Setup Google Cloud para Cesym ===" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verificar autenticación ────────────────────────────────────────────────
Write-Host "[1/6] Verificando autenticacion..." -ForegroundColor Yellow
$account = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>&1
if (-not $account -or $account -like "*ERROR*") {
    Write-Host ""
    Write-Host "ERROR: No estas autenticado en gcloud." -ForegroundColor Red
    Write-Host "Ejecuta primero:  gcloud auth login" -ForegroundColor White
    exit 1
}
Write-Host "  Cuenta activa: $account" -ForegroundColor Green

# ── 2. Crear proyecto ─────────────────────────────────────────────────────────
Write-Host "[2/6] Creando proyecto '$PROJECT_ID'..." -ForegroundColor Yellow
gcloud projects create $PROJECT_ID --name="Cesym HVAC Analytics" 2>&1 | Out-Null
gcloud config set project $PROJECT_ID 2>&1 | Out-Null
Write-Host "  Proyecto creado: $PROJECT_ID" -ForegroundColor Green

# ── 3. Habilitar Drive API ────────────────────────────────────────────────────
Write-Host "[3/6] Habilitando Google Drive API..." -ForegroundColor Yellow
gcloud services enable drive.googleapis.com --project=$PROJECT_ID 2>&1 | Out-Null
Write-Host "  Drive API habilitada" -ForegroundColor Green

# ── 4. Crear Service Account ──────────────────────────────────────────────────
Write-Host "[4/6] Creando Service Account '$SA_NAME'..." -ForegroundColor Yellow
gcloud iam service-accounts create $SA_NAME `
    --display-name="Cesym Sync Bot" `
    --project=$PROJECT_ID 2>&1 | Out-Null

$SA_EMAIL = "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
Write-Host "  Service Account: $SA_EMAIL" -ForegroundColor Green

# ── 5. Descargar credenciales JSON ────────────────────────────────────────────
Write-Host "[5/6] Descargando credenciales JSON..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force "credentials" | Out-Null
gcloud iam service-accounts keys create $CREDS_PATH `
    --iam-account=$SA_EMAIL `
    --project=$PROJECT_ID 2>&1 | Out-Null
Write-Host "  Guardado en: $CREDS_PATH" -ForegroundColor Green

# ── 6. Crear / actualizar .env ────────────────────────────────────────────────
Write-Host "[6/6] Configurando .env..." -ForegroundColor Yellow

# Pedir al usuario el ID de la carpeta de Drive
Write-Host ""
Write-Host "Abre Google Drive en tu navegador, ve a la carpeta donde se" -ForegroundColor White
Write-Host "suberan los Excel y copia el ID de la URL:" -ForegroundColor White
Write-Host "  drive.google.com/drive/folders/ --> ESTE_ES_EL_ID <--" -ForegroundColor Cyan
Write-Host ""
$FOLDER_ID = Read-Host "Pega aqui el ID de la carpeta de Drive"

$envContent = @"
# Generado por setup_google_cloud.ps1
DRIVE_FOLDER_ID=$FOLDER_ID
DRIVE_CREDENTIALS_PATH=credentials/service_account.json
"@

Set-Content -Path $ENV_FILE -Value $envContent -Encoding UTF8
Write-Host "  .env configurado" -ForegroundColor Green

# ── Resumen final ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Setup completado exitosamente" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Proyecto GCP:     $PROJECT_ID"
Write-Host "Service Account:  $SA_EMAIL"
Write-Host "Credenciales:     $CREDS_PATH"
Write-Host "Carpeta Drive:    $FOLDER_ID"
Write-Host ""
Write-Host "PASO FINAL (manual — 30 segundos):" -ForegroundColor Yellow
Write-Host "  1. Ve a Google Drive"
Write-Host "  2. Clic derecho en tu carpeta de Excel -> Compartir"
Write-Host "  3. Agrega este email como Lector:"
Write-Host "     $SA_EMAIL" -ForegroundColor Cyan
Write-Host ""
Write-Host "Luego verifica que funciona:" -ForegroundColor Yellow
Write-Host "  python -X utf8 scripts/sync_drive.py --dry-run"
Write-Host ""
