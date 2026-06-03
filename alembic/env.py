import pathlib
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, event, pool, text
from alembic import context

# Asegura que la raíz del proyecto esté en sys.path para importar src.db
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import DATABASE_URL, is_postgres  # noqa: E402

config = context.config
# Nota: NO usamos config.set_main_option("sqlalchemy.url", ...) porque ConfigParser
# interpreta '%' (de la contraseña codificada %40) como sintaxis de interpolación.
# Pasamos DATABASE_URL directamente a create_engine / context.configure.

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
_SCHEMA = "analytics" if is_postgres else None


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=_SCHEMA,
        include_schemas=bool(_SCHEMA),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    eng = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    if is_postgres:
        @event.listens_for(eng, "connect")
        def _set_path(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("SET search_path TO analytics")
            cur.close()

    with eng.connect() as connection:
        # El schema analytics debe existir ANTES de que Alembic cree su tabla
        # alembic_version dentro de él (version_table_schema='analytics').
        if is_postgres:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
            connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=_SCHEMA,
            include_schemas=bool(_SCHEMA),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
