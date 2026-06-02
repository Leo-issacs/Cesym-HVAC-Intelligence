# Configurar Google Drive API (una sola vez)

Este archivo NO se sube a git. El JSON de la service account tampoco.

---

## Paso 1 — Crear proyecto en Google Cloud

1. Ve a https://console.cloud.google.com
2. Arriba a la izquierda → "Seleccionar proyecto" → "Nuevo proyecto"
3. Nombre: `cesym-hvac` → Crear

---

## Paso 2 — Habilitar la API de Drive

1. En el proyecto recién creado, ve al menú → "APIs y servicios" → "Biblioteca"
2. Busca "Google Drive API" → Habilitar

---

## Paso 3 — Crear Service Account

Una Service Account es como un "usuario robot" que accede a Drive sin que
nadie tenga que iniciar sesión.

1. Ve a "APIs y servicios" → "Credenciales" → "+ Crear credenciales" → "Cuenta de servicio"
2. Nombre: `cesym-sync` → Crear y continuar → Omitir los pasos opcionales → Listo
3. Haz clic en la cuenta recién creada → pestaña "Claves" → "Agregar clave" → JSON
4. Se descarga un archivo JSON → **Guárdalo en esta carpeta como `service_account.json`**

El email de la service account se ve así:
  `cesym-sync@cesym-hvac.iam.gserviceaccount.com`

---

## Paso 4 — Compartir la carpeta de Drive

1. En Google Drive, abre la carpeta donde se van a subir los Excel
2. Clic derecho → "Compartir"
3. Agrega el email de la service account (del paso 3)
4. Permiso: **Lector** (solo necesita descargar)
5. Compartir

---

## Paso 5 — Configurar el .env

1. Copia `.env.example` como `.env` en la raíz del proyecto
2. Abre la carpeta de Drive en el navegador
3. La URL se ve así: `drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp`
   El ID es la parte final: `1AbCdEfGhIjKlMnOp`
4. Pega ese ID en `.env` como `DRIVE_FOLDER_ID`

---

## Verificar que funciona

```powershell
cd "C:\Users\leona\Personal\Works\Programacion\Projects\hvac-ai-system"
.\cesym_data_analytics\Scripts\Activate.ps1
python -X utf8 scripts/sync_drive.py --dry-run
```

Si ves la lista de archivos de Drive → todo correcto.
