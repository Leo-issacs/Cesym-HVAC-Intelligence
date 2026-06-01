"""
Punto de entrada del ETL.

Ejecuta la carga completa de datos: Excel → SQLite.

Uso:
    python -X utf8 scripts/etl.py
"""

import sys
import pathlib

# Agrega la raíz del proyecto al path para que Python encuentre src/
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.etl.load_facturas import run

if __name__ == "__main__":
    run(limpiar=False)
