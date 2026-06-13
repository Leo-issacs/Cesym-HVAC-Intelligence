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
| **Offsite** | Supabase Storage, bucket privado `backups` (best-effort — ver §6) |
| **Retención offsite** | 30 días (la aplica `supabase_backup.py` en el bucket) |
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

## 6. Offsite en Supabase Storage (bucket privado `backups`)

La copia offsite va a **Supabase Storage**, al bucket **privado** `backups`, vía
`scripts/supabase_backup.py` (Storage REST API con la `service_role` key). En una
sola corrida: asegura el bucket → sube el dump → aplica retención de 30 días en el
bucket. Es best-effort: si falla, el backup **local** (la red de seguridad
principal) igual quedó.

> **Probado el 2026-06-12**: bucket privado `backups` creado, subida del dump
> (36 KB) OK, y retención verificada (subir un dump con fecha vieja → la purga lo
> borró, dejando solo el vigente).

**Setup (una vez):** en `.env`

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>   # Dashboard > Settings > API
```

- `<project-ref>` es el subdominio del host directo de `DATABASE_MIGRATION_URL`
  (`db.<project-ref>.supabase.co`).
- La `service_role` key es **secreta** (salta RLS): solo en el `.env` del
  servidor, nunca en código cliente ni en el repo.

Subida manual de un archivo:

```powershell
.\cesym_data_analytics\Scripts\python.exe -X utf8 scripts\supabase_backup.py backups\<dump>
```

### Descargar un backup del bucket (camino offsite para restaurar)

Si el dump local se perdió, baja el del bucket antes de restaurar (§5):

```powershell
$U   = $env:SUPABASE_URL
$KEY = $env:SUPABASE_SERVICE_KEY
$name = "cesym_pg_backup_2026-06-11_184536.dump"

# Listar lo que hay en el bucket:
curl.exe -s -X POST "$U/storage/v1/object/list/backups" `
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" `
  -H "Content-Type: application/json" `
  -d '{"prefix":"","limit":1000,"sortBy":{"column":"name","order":"desc"}}'

# Descargar uno a backups\:
curl.exe -s -X GET "$U/storage/v1/object/backups/$name" `
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" `
  -o "backups\$name"
```

Luego verifica con `test_restore.ps1 -DumpFile backups\$name` y procede con §5.

> Alternativa GUI: Dashboard de Supabase > Storage > bucket `backups` > descargar.

---

## 7. Checklist de restauración (imprimir/seguir)

- [ ] Identifica el backup bueno (local `backups/` o el bucket de Supabase Storage).
- [ ] `test_restore.ps1 -DumpFile <dump>` → **PASS**.
- [ ] Aparta el schema dañado (`ALTER SCHEMA ... RENAME`).
- [ ] `CREATE SCHEMA` + `pg_restore --schema=...`.
- [ ] Verifica conteos y `alembic_version`.
- [ ] Corre el smoke test de la app (dashboard / queries clave).
- [ ] Borra el schema apartado solo cuando todo esté confirmado.
