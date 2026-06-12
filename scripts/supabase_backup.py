"""supabase_backup.py - Sube un dump a Supabase Storage y aplica retencion.

Reemplaza el intento offsite a Google Drive (una Service Account no tiene cuota
en "Mi unidad"). Usa el bucket privado "backups" via la Storage REST API de
Supabase con la service_role key.

Hace, en una sola corrida:
  1. Asegura que el bucket exista (lo crea PRIVADO si no).
  2. Sube el archivo (con x-upsert).
  3. Retencion: lista el bucket y borra los backups con mas de 30 dias.

USO:
    python -X utf8 scripts/supabase_backup.py <ruta_dump>

Variables de entorno (.env):
    SUPABASE_URL          https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  service_role key (Dashboard > Settings > API)
    SUPABASE_BACKUP_BUCKET  opcional, default "backups"

Exit codes: 0 = subida + retencion OK · 1 = error (el backup LOCAL no depende de esto).
"""
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BACKUP_BUCKET", "backups").strip()
RETENTION_DAYS = 30

# Solo gestionamos archivos con este patron (no tocamos nada mas del bucket).
FNAME_RE = re.compile(r"^cesym_pg_backup_(\d{4}-\d{2}-\d{2})_\d{6}\.dump$")

TIMEOUT = 120


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
    if extra:
        h.update(extra)
    return h


def ensure_bucket() -> None:
    """Crea el bucket PRIVADO si no existe."""
    r = requests.get(
        f"{SUPABASE_URL}/storage/v1/bucket/{BUCKET}",
        headers=_headers(), timeout=TIMEOUT,
    )
    if r.status_code == 200:
        return
    # Supabase Storage responde HTTP 400 con body {"statusCode":"404",
    # "error":"Bucket not found"} cuando el bucket no existe; cualquier otro
    # error real lo propagamos.
    if not (r.status_code in (400, 404) and "not found" in r.text.lower()):
        r.raise_for_status()

    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/bucket",
        headers=_headers(), timeout=TIMEOUT,
        json={"id": BUCKET, "name": BUCKET, "public": False},
    )
    # 409 / "already exists" = carrera benigna, lo tratamos como OK.
    if r.status_code in (200, 201):
        print(f"  bucket '{BUCKET}' creado (privado)")
    elif r.status_code == 409 or "already exists" in r.text.lower():
        pass
    else:
        raise RuntimeError(f"No se pudo crear el bucket: {r.status_code} {r.text}")


def upload(archivo: pathlib.Path) -> None:
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{archivo.name}"
    with open(archivo, "rb") as fh:
        data = fh.read()
    r = requests.post(
        url, headers=_headers({"Content-Type": "application/octet-stream", "x-upsert": "true"}),
        data=data, timeout=TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Fallo la subida: {r.status_code} {r.text}")
    size_kb = round(len(data) / 1024, 1)
    print(f"  OK  subido a Supabase Storage: {BUCKET}/{archivo.name}  ({size_kb} KB)")


def prune() -> None:
    """Lista el bucket y borra los backups con mas de RETENTION_DAYS dias."""
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}",
        headers=_headers(), timeout=TIMEOUT,
        json={"prefix": "", "limit": 1000, "offset": 0,
              "sortBy": {"column": "name", "order": "asc"}},
    )
    r.raise_for_status()
    objetos = r.json()

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    viejos = []
    for o in objetos:
        m = FNAME_RE.match(o.get("name", ""))
        if not m:
            continue
        fecha = datetime.strptime(m.group(1), "%Y-%m-%d")
        if fecha < cutoff:
            viejos.append(o["name"])

    if not viejos:
        print(f"  retencion: nada que borrar (> {RETENTION_DAYS} dias)")
        return

    r = requests.delete(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}",
        headers=_headers(), timeout=TIMEOUT, json={"prefixes": viejos},
    )
    r.raise_for_status()
    print(f"  retencion: borrados {len(viejos)} backup(s) > {RETENTION_DAYS} dias")


def main() -> int:
    if len(sys.argv) < 2:
        print("USO: python -X utf8 scripts/supabase_backup.py <ruta_dump>")
        return 1
    archivo = pathlib.Path(sys.argv[1])
    if not archivo.exists():
        print(f"ERROR: no existe el archivo {archivo}")
        return 1
    if not SUPABASE_URL or not SERVICE_KEY:
        print("ERROR: faltan SUPABASE_URL y/o SUPABASE_SERVICE_KEY en .env")
        print("  SUPABASE_URL=https://<ref>.supabase.co")
        print("  SUPABASE_SERVICE_KEY=<service_role key: Dashboard > Settings > API>")
        return 1

    try:
        ensure_bucket()
        upload(archivo)
        prune()
        return 0
    except requests.RequestException as e:
        print(f"ERROR de red con Supabase Storage: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR en Supabase Storage: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
