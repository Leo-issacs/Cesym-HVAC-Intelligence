"""
sync_drive.py — Descarga los Excel de Google Drive y ejecuta el pipeline.

La persona responsable solo necesita subir los archivos actualizados a la
carpeta de Drive compartida. Este script descarga todo y actualiza la DB.

CONFIGURACIÓN (una sola vez — ver credentials/INSTRUCCIONES.md):
  1. Crea un proyecto en Google Cloud Console
  2. Habilita la Google Drive API
  3. Crea una Service Account → descarga el JSON → guárdalo como
     credentials/service_account.json
  4. Comparte la carpeta de Drive con el email de la service account
  5. Copia .env.example a .env y llena DRIVE_FOLDER_ID

USO:
  python -X utf8 scripts/sync_drive.py              # descarga + ETL + scoring
  python -X utf8 scripts/sync_drive.py --dry-run    # qué descargaría, sin tocar nada
  python -X utf8 scripts/sync_drive.py --solo-sync  # solo descarga, sin pipeline
"""

import argparse
import io
import logging
import os
import pathlib
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Logging (archivo + consola) ───────────────────────────────────────────────
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_drive.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Variables de entorno ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # sin python-dotenv, se usan las variables del sistema

FOLDER_ID        = os.getenv("DRIVE_FOLDER_ID", "").strip()
CREDENTIALS_PATH = ROOT / os.getenv("DRIVE_CREDENTIALS_PATH", "credentials/service_account.json")
RAW_DIR          = ROOT / "data" / "raw"

# ── Mapeo de archivos objetivo ────────────────────────────────────────────────
# Clave = nombre local en data/raw/ que el ETL espera.
# Valor = palabras clave para buscar en Drive (case-insensitive).
# Así funciona aunque el nombre en Drive cambie de fecha (ej. "CARTERA AL 11032026").
ARCHIVOS = {
    "reporteMensual_FACTURAS.xlsx":           ["facturas"],
    "CARTERA AL 11032026.xlsx":               ["cartera"],
    "CONTROL DE INST. MINISPLIT 2026.xlsx":   ["minisplit", "control inst"],
}


# ── Validación ────────────────────────────────────────────────────────────────

def validar_config() -> None:
    errores = []
    if not FOLDER_ID:
        errores.append("DRIVE_FOLDER_ID no definido en .env")
    if not CREDENTIALS_PATH.exists():
        errores.append(
            f"Credenciales no encontradas: {CREDENTIALS_PATH}\n"
            "  → Sigue las instrucciones en credentials/INSTRUCCIONES.md"
        )
    if errores:
        for e in errores:
            log.error(e)
        sys.exit(1)


# ── Google Drive ──────────────────────────────────────────────────────────────

def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def listar_xlsx_en_carpeta(service) -> list[dict]:
    """Lista todos los .xlsx de la carpeta compartida."""
    mime  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    query = f"'{FOLDER_ID}' in parents and mimeType='{mime}' and trashed=false"
    res   = service.files().list(
        q=query, fields="files(id, name, modifiedTime, size)"
    ).execute()
    return res.get("files", [])


def encontrar_coincidencia(nombre_local: str, keywords: list[str], archivos_drive: list[dict]) -> dict | None:
    """
    Busca el archivo de Drive que corresponde a un archivo local.
    Primero intenta nombre exacto; si no, busca por keywords parciales.
    """
    nombre_lower = nombre_local.lower()

    # Intento 1: nombre exacto
    for f in archivos_drive:
        if f["name"].lower() == nombre_lower:
            return f

    # Intento 2: coincidencia parcial con keywords
    for f in archivos_drive:
        f_lower = f["name"].lower()
        if any(kw in f_lower for kw in keywords):
            return f

    return None


def descargar_archivo(service, file_id: str, destino: pathlib.Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload
    request = service.files().get_media(fileId=file_id)
    buffer  = io.BytesIO()
    dl      = MediaIoBaseDownload(buffer, request, chunksize=10 * 1024 * 1024)
    done    = False
    while not done:
        _, done = dl.next_chunk()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(buffer.getvalue())


# ── Sincronización ────────────────────────────────────────────────────────────

def sync(dry_run: bool = False) -> int:
    """Descarga archivos de Drive. Retorna número de archivos descargados."""
    log.info("=" * 58)
    log.info(f"SYNC DRIVE  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Carpeta Drive ID: {FOLDER_ID}")

    validar_config()

    try:
        service = get_service()
        en_drive = listar_xlsx_en_carpeta(service)
    except Exception as e:
        log.error(f"Error conectando con Google Drive: {e}")
        sys.exit(1)

    if not en_drive:
        log.warning("No se encontraron archivos xlsx en la carpeta. ¿Está bien compartida?")
        return 0

    log.info(f"Archivos en Drive ({len(en_drive)}): {[f['name'] for f in en_drive]}")
    log.info("-" * 58)

    descargados = 0
    for nombre_local, keywords in ARCHIVOS.items():
        match = encontrar_coincidencia(nombre_local, keywords, en_drive)
        if not match:
            log.warning(f"  ⚠  No encontrado en Drive: '{nombre_local}' (keywords: {keywords})")
            continue

        destino = RAW_DIR / nombre_local
        tam_kb  = int(match.get("size", 0)) // 1024
        mod     = match["modifiedTime"][:10]

        if dry_run:
            log.info(f"  [DRY-RUN] '{match['name']}' → {nombre_local}  ({tam_kb} KB, modificado {mod})")
            continue

        log.info(f"  ↓  '{match['name']}'  ({tam_kb} KB, mod. {mod})")
        descargar_archivo(service, match["id"], destino)
        log.info(f"     Guardado: {destino.relative_to(ROOT)}")
        descargados += 1

    if not dry_run:
        log.info(f"Descarga: {descargados}/{len(ARCHIVOS)} archivos OK")

    return descargados


# ── Pipeline post-descarga ────────────────────────────────────────────────────

def run_pipeline() -> None:
    log.info("-" * 58)
    log.info("[1/2] ETL — cargando facturas en la DB...")
    from src.etl.load_facturas import run as etl_run
    etl_run(limpiar=True)

    log.info("[2/2] Scoring de clientes...")
    from src.models.client_score import run as score_run
    score_run()

    log.info("Pipeline completado. El dashboard ya refleja los datos nuevos.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true", help="Simula sin descargar nada")
    parser.add_argument("--solo-sync",  action="store_true", help="Solo descarga, sin ejecutar ETL")
    args = parser.parse_args()

    n = sync(dry_run=args.dry_run)

    if args.dry_run:
        log.info("Modo dry-run completado. Sin cambios.")
    elif n > 0 and not args.solo_sync:
        run_pipeline()
    elif n == 0:
        log.info("Sin archivos descargados. Pipeline no ejecutado.")

    log.info("=" * 58)
