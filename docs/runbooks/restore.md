# Runbook: Backup y Restauración de PostgreSQL

Procedimiento operativo para respaldar y **restaurar** la base de datos de
producción (Supabase). Escrito para que cualquiera pueda restaurar bajo presión
sin improvisar.

> **Regla de oro** (ver `CLAUDE.md`): no se aplica DDL ni escrituras
> estructurales en producción sin un **backup del día** y sin haber mergeado el
> cambio. El backup del lunes 7 AM corre **antes** de cualquier ETL.

---

## 1. Qué se respalda y dónde

| | |
|---|---|
| **Qué** | Schemas `analytics` (HVAC) y `chatbot`, ambos en la misma base Supabase |
| **Cómo** | `pg_dump` formato custom (`-Fc`, comprimido) — incluye datos, constraints (p.ej. `pk_facturas`), secuencias |
| **Conexión** | `DATABASE_MIGRATION_URL` = conexión **DIRECTA** (puerto 5432), nunca el pooler (6543) |
| **Local** | `backups/cesym_pg_backup_YYYY-MM-DD_HHmmss.dump` (gitignored) |
| **Retención local** | 30 días (los dumps más viejos se borran solos) |
| **Offsite** | Google Drive (best-effort — ver §6) |
| **Disparo** | `scripts/sync_maestro.ps1`, paso `[1/3]`, lunes 7 AM, **antes** del ETL |

El script: `scripts/backup_postgres.ps1`. La verificación: `scripts/test_restore.ps1`.

---

## 2. Requisitos previos

1. **Cliente PostgreSQL 17** (`pg_dump`/`pg_restore`/`psql`). El servidor es
   PostgreSQL 17.x; el cliente debe ser **v17** o el dump falla.

   ```powershell
   winget install -e --id PostgreSQL.PostgreSQL.17
   ```

   Queda en `C:\Program Files\PostgreSQL\17\bin`. Los scripts lo detectan ahí
   aunque no esté en el PATH. Tras instalar, abre una PowerShell **nueva** para
   refrescar el PATH (o deja que el script lo resuelva solo).

2. **`.env`** con `DATABASE_MIGRATION_URL` apuntando a la conexión directa 5432.

---

## 3. Hacer un backup manual (bajo demanda)

Antes de cualquier cambio estructural (migración, DDL, carga masiva):

```powershell
.\scripts\backup_postgres.ps1            # dump local + subida a Drive
.\scripts\backup_postgres.ps1 -SkipUpload  # solo local (más rápido)
```

Exit code `0` = dump local creado y validado (`pg_restore --list`). La subida a
Drive es best-effort: si falla, el backup local **sí** quedó.

---

## 4. Verificar que un backup es restaurable

**No confíes en un dump que no probaste.** Este script restaura el schema
`analytics` del dump en un schema temporal `analytics_restore_test`, compara los
conteos contra el `analytics` real y borra el temporal. Es seguro contra
producción (aborta si quedara cualquier referencia a `analytics.` antes de
aplicar).

```powershell
.\scripts\test_restore.ps1                                   # usa el dump más reciente
.\scripts\test_restore.ps1 -DumpFile backups\cesym_pg_backup_2026-06-11_184536.dump
```

Salida esperada: `TEST DE RESTORE: PASS` con los conteos por tabla.

> **Probado el 2026-06-11** contra `cesym_pg_backup_2026-06-11_184536.dump`:
> `alembic_version 1=1`, `facturas 374=374`, `scores_clientes 17=17` → **PASS**.

---

## 5. Restaurar en producción (disaster recovery)

Escenario: una migración o escritura corrompió `analytics` y hay que volver al
último backup bueno.

### 5.1 Restaurar un schema completo (método "apartar y reemplazar")

No borres el schema dañado de entrada: renómbralo para tener forense.

```powershell
$U = $env:DATABASE_MIGRATION_URL
$bin = "C:\Program Files\PostgreSQL\17\bin"
$dump = "backups\cesym_pg_backup_2026-06-11_184536.dump"

# 0. Verifica primero que el dump elegido es bueno:
.\scripts\test_restore.ps1 -DumpFile $dump

# 1. Aparta el schema dañado (NO lo borres aún):
& "$bin\psql.exe" $U -c "ALTER SCHEMA analytics RENAME TO analytics_broken_20260611;"

# 2. Crea el schema vacío. OJO: pg_restore --schema=analytics NO crea el schema
#    (el filtro excluye la entrada CREATE SCHEMA), por eso se crea a mano:
& "$bin\psql.exe" $U -c "CREATE SCHEMA analytics;"

# 3. Restaura SOLO analytics (tablas + datos + constraints + secuencias):
& "$bin\pg_restore.exe" --schema=analytics --no-owner --no-privileges `
    --dbname $U $dump

# 4. Verifica:
& "$bin\psql.exe" $U -c "SELECT count(*) AS facturas FROM analytics.facturas;"
& "$bin\psql.exe" $U -c "SELECT version_num FROM analytics.alembic_version;"

# 5. Cuando CONFIRMES que todo está bien, borra el schema apartado:
& "$bin\psql.exe" $U -c "DROP SCHEMA analytics_broken_20260611 CASCADE;"
```

Para restaurar `chatbot`, repite cambiando `analytics` por `chatbot`.

### 5.2 Restaurar todo a un Postgres vacío

Si la base está vacía (o es un proyecto nuevo) puedes restaurar ambos schemas de
un golpe — el dump incluye las entradas `CREATE SCHEMA`:

```powershell
& "$bin\pg_restore.exe" --no-owner --no-privileges --dbname $U $dump
```

Si los schemas ya existen, fallará al recrearlos: usa el método 5.1 (apartar) o
agrega `--clean` (que dropea objetos antes de recrearlos — **destructivo**).

### 5.3 Restaurar una sola tabla

```powershell
# La tabla debe existir con el schema correcto. Si quieres reemplazar su
# contenido, trúncala antes (respeta FKs):
& "$bin\psql.exe" $U -c "TRUNCATE analytics.facturas;"
& "$bin\pg_restore.exe" --schema=analytics --table=facturas --data-only `
    --no-owner --dbname $U $dump
```

---

## 6. Offsite en Google Drive — setup obligatorio (Shared Drive)

La subida reusa la **Service Account** (`credentials/service_account.json`, mismo
patrón que `sync_drive.py`) con scope `drive.file`. Hay un detalle crítico:

> Una Service Account **no tiene almacenamiento propio**. Si la carpeta destino
> está en "Mi unidad" de un usuario, Google rechaza la subida con
> `storageQuotaExceeded`.

**Solución (una vez):**

1. Crea una **Unidad compartida** (Shared Drive) en Google Drive.
2. Agrégale la Service Account como miembro con permiso de **Administrador de
   contenido** (o Colaborador).
3. Crea dentro una carpeta para los backups y copia su **ID**.
4. Ponlo en `.env`:

   ```
   DRIVE_BACKUP_FOLDER_ID=<id_de_la_carpeta_en_la_shared_drive>
   ```

Sin esto, el backup **local** sigue funcionando (es la red de seguridad
principal); solo falta la copia offsite. `drive_upload.py` usa
`supportsAllDrives=True`, así que funcionará en cuanto el destino sea una Shared
Drive. Alternativa: OAuth con delegación de dominio (Workspace).

Subida manual de un archivo:

```powershell
.\cesym_data_analytics\Scripts\python.exe -X utf8 scripts\drive_upload.py backups\<dump>
```

---

## 7. Checklist de restauración (imprimir/seguir)

- [ ] Identifica el backup bueno (local `backups/` o Drive).
- [ ] `test_restore.ps1 -DumpFile <dump>` → **PASS**.
- [ ] Aparta el schema dañado (`ALTER SCHEMA ... RENAME`).
- [ ] `CREATE SCHEMA` + `pg_restore --schema=...`.
- [ ] Verifica conteos y `alembic_version`.
- [ ] Corre el smoke test de la app (dashboard / queries clave).
- [ ] Borra el schema apartado solo cuando todo esté confirmado.
