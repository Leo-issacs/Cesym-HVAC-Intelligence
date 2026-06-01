"""
Carga (o recarga) la base de datos desde cero.

Opciones:
  --limpiar   Borra las tablas existentes antes de cargar.
              Útil cuando el schema cambió o hay datos corruptos.

Uso:
    python -X utf8 scripts/cargar_bd.py            # carga sin borrar
    python -X utf8 scripts/cargar_bd.py --limpiar  # borra y recarga
"""

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.etl.load_facturas import run as etl_run

if __name__ == "__main__":
    limpiar = "--limpiar" in sys.argv
    if limpiar:
        print("Modo --limpiar: las tablas existentes serán eliminadas antes de cargar.\n")
    etl_run(limpiar=limpiar)
