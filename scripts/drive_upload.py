"""drive_upload.py — Sube un archivo a Google Drive reusando la Service Account.

Mismo patrón de autenticación que sync_drive.py, pero con scope de escritura
(drive.file) en vez de readonly. Pensado para subir los backups de pg_dump.

USO:
    python -X utf8 scripts/drive_upload.py <ruta_archivo>

Carpeta destino (en este orden):
    DRIVE_BACKUP_FOLDER_ID  (si está en .env — recomendado: una carpeta dedicada)
    DRIVE_FOLDER_ID         (fallback: la misma carpeta de los Excel)

NOTA IMPORTANTE sobre Service Accounts y cuota de Drive
-------------------------------------------------------
Una Service Account NO tiene almacenamiento propio. Si la carpeta destino está en
"Mi unidad" de un usuario, el archivo subido queda a nombre de la SA y Google lo
rechaza con "storageQuotaExceeded". Para que la subida funcione de forma fiable, la
carpeta destino debe estar en una **Unidad compartida (Shared Drive)** con la SA
agregada como miembro con permiso de escritura. Por eso usamos supportsAllDrives.
Ver docs/runbooks/restore.md.

Exit codes: 0 = subido OK · 1 = error (el backup local NO depende de esto).
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

CREDENTIALS_PATH = ROOT / os.getenv("DRIVE_CREDENTIALS_PATH", "credentials/service_account.json")
FOLDER_ID = (os.getenv("DRIVE_BACKUP_FOLDER_ID") or os.getenv("DRIVE_FOLDER_ID") or "").strip()

# Scope de escritura limitada: la SA solo ve/maneja archivos que ella misma crea.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def main() -> int:
    if len(sys.argv) < 2:
        print("USO: python -X utf8 scripts/drive_upload.py <ruta_archivo>")
        return 1

    archivo = pathlib.Path(sys.argv[1])
    if not archivo.exists():
        print(f"ERROR: no existe el archivo {archivo}")
        return 1
    if not CREDENTIALS_PATH.exists():
        print(f"ERROR: credenciales no encontradas en {CREDENTIALS_PATH}")
        return 1
    if not FOLDER_ID:
        print("ERROR: ni DRIVE_BACKUP_FOLDER_ID ni DRIVE_FOLDER_ID están definidos en .env")
        return 1

    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    try:
        service = get_service()
        metadata = {"name": archivo.name, "parents": [FOLDER_ID]}
        media = MediaFileUpload(str(archivo), resumable=True)
        created = service.files().create(
            body=metadata, media_body=media,
            fields="id, name, size",
            supportsAllDrives=True,   # necesario para Shared Drives
        ).execute()
        size_kb = round(int(created.get("size", 0)) / 1024, 1)
        print(f"  OK  subido a Drive: {created['name']}  (id={created['id']}, {size_kb} KB)")
        return 0
    except HttpError as e:
        print(f"ERROR de Google Drive: {e}")
        if "storageQuotaExceeded" in str(e):
            print("  → La Service Account no tiene cuota. La carpeta destino debe estar")
            print("    en una Unidad compartida (Shared Drive) con la SA como miembro.")
            print("    Ver docs/runbooks/restore.md.")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR subiendo a Drive: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
