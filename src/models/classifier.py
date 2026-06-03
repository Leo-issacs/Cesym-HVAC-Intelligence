"""
Clasificador NLP de conceptos de servicio HVAC.

Pipeline: preprocesamiento de texto → TF-IDF (unigramas + bigramas) → Regresión Logística

Datos de entrenamiento: data/processed/conceptos_clasificados.csv (73 ejemplos etiquetados)
Categorías de salida:
    mantenimiento_preventivo | mantenimiento_correctivo
    instalacion_nueva        | venta_refaccion | otro

Uso desde línea de comandos:
    python -X utf8 src/models/classifier.py        # entrena, evalúa y clasifica facturas

Uso como módulo desde otro script:
    from src.models.classifier import clasificar
    categoria, confianza = clasificar("MANTENIMIENTO PREVENTIVO A UNIDADES MINISPLIT")
"""

import pathlib
import re
import sys
import unicodedata

import joblib
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer

# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import engine, is_postgres, SQLITE_DB_PATH  # noqa: E402

LABELS_CSV = ROOT / "data" / "processed" / "conceptos_clasificados.csv"
MODEL_PATH = ROOT / "data" / "processed" / "modelo_clasificador.joblib"
OUTPUT_CSV = ROOT / "data" / "processed" / "facturas_clasificadas.csv"


# ── 1. Preprocesamiento de texto ──────────────────────────────────────────────

def normalizar(texto: str) -> str:
    """
    Limpia y estandariza el texto de un concepto de factura.

    Pasos:
      1. Convierte a mayúsculas.
      2. Elimina acentos (é→e, ó→o, ñ→n, etc.) descomponiendo caracteres
         Unicode y descartando las marcas diacríticas (categoría 'Mn').
         Esto hace que "MANTENIMIENTÓ" y "MANTENIMIENTO" sean iguales.
      3. Quita todo lo que no sea letra, número o espacio.
         Los conceptos del Excel traen comas, puntos y guiones que no aportan.
      4. Colapsa espacios múltiples a uno solo.

    Por qué normalizar: reduce el vocabulario y mejora la generalización.
    Sin este paso, "INSTALACIÓN" y "INSTALACION" serían dos tokens distintos.
    """
    texto = str(texto).upper()

    # Descomponer caracteres con tilde en letra base + marca diacrítica
    texto = unicodedata.normalize("NFD", texto)
    # Descartar sólo las marcas diacríticas (Mn = Mark, Nonspacing)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")

    # Dejar solo letras A-Z, dígitos 0-9 y espacios
    texto = re.sub(r"[^A-Z0-9\s]", " ", texto)

    # Colapsar espacios múltiples
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


# ── 2. Construcción del pipeline ──────────────────────────────────────────────

def construir_pipeline() -> Pipeline:
    """
    Crea el pipeline de sklearn: vectorizador TF-IDF + clasificador.

    ¿Por qué TF-IDF?
    Convierte cada concepto en un vector numérico donde cada posición
    representa una palabra (o par de palabras), ponderada por:
      - TF  (Term Frequency):         qué tan seguido aparece en este concepto.
      - IDF (Inverse Doc Frequency):  qué tan rara es en todos los conceptos.
    Resultado: palabras genéricas ("DE", "A") pesan poco; palabras técnicas
    específicas ("CHILLER", "VALVULA") pesan mucho.

    Parámetros clave del TfidfVectorizer:
      ngram_range=(1,2)   → incluye unigramas ("compresor") Y bigramas
                            ("compresor danfoss"), capturando frases técnicas.
      sublinear_tf=True   → usa log(1+tf) en vez de tf puro; reduce el efecto
                            de términos que se repiten muchas veces.
      token_pattern       → solo extrae tokens alfanuméricos en mayúsculas
                            (ya normalizamos el texto antes).

    ¿Por qué Regresión Logística?
    Es el clasificador de referencia para texto: rápido, interpretable y
    funciona muy bien con datasets pequeños como este (73 ejemplos).
    Con redes neuronales necesitaríamos miles de ejemplos para superar a LR.

    Parámetros clave:
      C=5.0               → regularización L2 ligera; con tan pocos ejemplos
                            un C alto permite que el modelo aprenda bien los
                            patrones del vocabulario técnico especializado.
      class_weight=None   → pesos iguales. Las 4 categorías principales tienen
                            entre 15 y 22 ejemplos (suficientemente balanceadas).
                            'otro' se maneja por umbral de confianza, no como
                            clase entrenada, porque con 5 ejemplos el modelo
                            no puede aprenderla sin sesgar todo lo demás.
    """
    vectorizador = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
        lowercase=False,       # la normalización ya dejó todo en mayúsculas
        token_pattern=r"[A-Z0-9]+",
    )
    clasificador = LogisticRegression(
        C=5.0,
        max_iter=1000,
        class_weight=None,
        solver="lbfgs",
        random_state=42,
    )
    return Pipeline([("tfidf", vectorizador), ("clf", clasificador)])


# ── 3. Entrenamiento ──────────────────────────────────────────────────────────

def entrenar() -> Pipeline:
    """
    Lee los datos etiquetados, evalúa el modelo con validación cruzada,
    entrena con todos los datos y guarda el modelo en disco.

    ¿Por qué validación cruzada en vez de train/test split?
    Con solo 73 ejemplos, separar un test set fijo (ej. 20%) nos dejaría
    con ~58 ejemplos para entrenar — muy poco para 5 clases. La validación
    cruzada k-fold reparte mejor los datos: entrena k veces, cada vez con
    k-1 partes y evalúa en la restante. Usamos StratifiedKFold para que
    cada fold tenga la misma proporción de clases que el dataset completo.

    El modelo final se reentrena con TODOS los datos (mayor cantidad de
    ejemplos = mejores pesos), y ese es el que se guarda en disco.

    Devuelve: el pipeline ya entrenado.
    """
    df = pd.read_csv(LABELS_CSV)

    # Excluimos "otro" del entrenamiento porque solo tiene 5 ejemplos —
    # tan pocos hacen que class_weight='balanced' sesgue el modelo hacia esa clase,
    # clasificando casi todo como "otro". En cambio la asignamos por umbral de
    # confianza: si el modelo no está seguro de ninguna de las 4 categorías
    # principales, la factura se marca como "otro" para revisión manual.
    df_train = df[df["categoria_modelo"] != "otro"].copy()

    X = df_train["concepto"].apply(normalizar).tolist()
    y = df_train["categoria_modelo"].tolist()

    print(f"Datos de entrenamiento: {len(X)} ejemplos etiquetados")
    print("Distribución de clases:")
    for cat, n in pd.Series(y).value_counts().items():
        barra = "█" * n
        print(f"  {cat:<30} {n:>3}  {barra}")
    print()

    pipeline = construir_pipeline()

    # ── Validación cruzada estratificada (5 folds) ────────────────────────────
    # Estratificada = cada fold mantiene las proporciones de cada clase.
    # Con 5 folds y 73 ejemplos, cada fold tiene ~15 ejemplos de evaluación.
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, X, y, cv=cv, scoring="accuracy")

    print("Precisión por validación cruzada (5-fold):")
    for i, s in enumerate(scores, 1):
        barra = "█" * int(s * 20)
        print(f"  Fold {i}: {s:.0%}  {barra}")
    print(f"  {'Media':>6}: {scores.mean():.1%}  ±  {scores.std():.1%}")
    print()

    # ── Reporte detallado con último fold ─────────────────────────────────────
    # Para mostrar métricas por clase, entrenamos/evaluamos una vez más
    # en el último fold (no afecta al modelo final).
    from sklearn.model_selection import train_test_split
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=42
    )
    pipeline.fit(X_tr, y_tr)
    y_pred = pipeline.predict(X_te)
    print("Reporte de clasificación (hold-out 25%):")
    print(classification_report(y_te, y_pred, zero_division=0))

    # ── Entrenamiento final con TODOS los datos ────────────────────────────────
    # Ahora que validamos la calidad, entrenamos con el dataset completo
    # para maximizar la información disponible para el modelo de producción.
    pipeline.fit(X, y)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"Modelo guardado en: {MODEL_PATH.relative_to(ROOT)}")

    return pipeline


# ── 4. Inferencia ─────────────────────────────────────────────────────────────

# Umbral mínimo de confianza para aceptar una categoría.
# Si la probabilidad máxima del modelo es menor a este valor,
# la factura se clasifica como "otro" (requiere revisión manual).
UMBRAL_CONFIANZA = 0.40


def cargar_modelo() -> Pipeline:
    """Carga el modelo serializado. Lo entrena si no existe en disco."""
    if not MODEL_PATH.exists():
        print("Modelo no encontrado en disco, entrenando...")
        return entrenar()
    return joblib.load(MODEL_PATH)


def clasificar(concepto: str) -> tuple:
    """
    Clasifica un concepto de factura y devuelve (categoria, confianza).

    La confianza es la probabilidad que asigna el modelo a la categoría
    predicha. Si es menor a UMBRAL_CONFIANZA (0.40), se devuelve "otro"
    para indicar que el texto no encaja claramente en ninguna categoría.

    Ejemplo de uso:
        from src.models.classifier import clasificar

        cat, conf = clasificar("COMPRESOR DANFOSS PARA CHILLER 80 TON")
        print(cat, conf)   # venta_refaccion  0.91
    """
    pipeline   = cargar_modelo()
    texto_norm = normalizar(concepto)

    # predict_proba → array de shape (1, n_clases) con la probabilidad de cada clase
    proba     = pipeline.predict_proba([texto_norm])[0]
    confianza = float(proba.max())

    if confianza < UMBRAL_CONFIANZA:
        return "otro", confianza

    categoria = pipeline.predict([texto_norm])[0]
    return categoria, confianza


def clasificar_batch(conceptos: list) -> pd.DataFrame:
    """
    Clasifica una lista de conceptos de forma vectorizada.

    Más eficiente que llamar clasificar() en un loop porque el vectorizador
    TF-IDF procesa todos los textos de una vez (construcción única de la
    matriz documento-término).

    Devuelve un DataFrame con columnas: concepto, categoria, confianza.
    """
    pipeline   = cargar_modelo()
    textos     = [normalizar(c) for c in conceptos]
    probas     = pipeline.predict_proba(textos)
    confianzas = probas.max(axis=1)
    categorias = np.where(
        confianzas >= UMBRAL_CONFIANZA,
        pipeline.predict(textos),
        "otro",
    )

    return pd.DataFrame({
        "concepto":  conceptos,
        "categoria": categorias,
        "confianza": np.round(confianzas, 4),
    })


# ── 5. Aplicar clasificación a todas las facturas ────────────────────────────

def clasificar_facturas(pipeline: Pipeline) -> pd.DataFrame:
    """
    Lee todas las facturas de hvac.db, aplica el modelo y guarda el resultado.

    El CSV de salida incluye la categoría predicha y la confianza para cada
    factura, listo para ser consumido por el dashboard o agentes de cobranza.
    """
    if not is_postgres and not SQLITE_DB_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró la base de datos en {SQLITE_DB_PATH}\n"
            "Ejecuta primero: python -X utf8 scripts/cargar_bd.py --limpiar"
        )

    df = pd.read_sql(
        "SELECT folio, cliente, fecha_factura, concepto, total, pagada FROM facturas",
        engine,
    )

    print(f"Clasificando {len(df)} facturas...")
    textos_norm = [normalizar(c) for c in df["concepto"]]
    probas     = pipeline.predict_proba(textos_norm)
    confianzas = probas.max(axis=1)

    # Aplicar umbral: confianza baja → "otro" (revisión manual recomendada)
    df["categoria_predicha"] = np.where(
        confianzas >= UMBRAL_CONFIANZA,
        pipeline.predict(textos_norm),
        "otro",
    )
    df["confianza"] = np.round(confianzas, 4)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Resultado guardado en: {OUTPUT_CSV.relative_to(ROOT)}")

    return df


# ── 6. Reporte en consola ─────────────────────────────────────────────────────

def imprimir_reporte(df: pd.DataFrame) -> None:
    """Imprime distribución de categorías, montos y alertas de baja confianza."""
    sep = "─" * 72

    resumen = (
        df.groupby("categoria_predicha")
        .agg(
            facturas=("folio",     "count"),
            monto=   ("total",     "sum"),
            confianza=("confianza","mean"),
        )
        .sort_values("monto", ascending=False)
    )

    print()
    print(sep)
    print(f"  {'CLASIFICACIÓN DE FACTURAS HVAC':^68}")
    print(sep)
    print(f"  {'Categoría':<30} {'Facturas':>8} {'Monto total':>15} {'Confianza':>10}")
    print(sep)
    for cat, row in resumen.iterrows():
        print(
            f"  {cat:<30}"
            f"  {row['facturas']:>6.0f}"
            f"  ${row['monto']:>13,.0f}"
            f"  {row['confianza']:>9.1%}"
        )
    print(sep)

    # Facturas con confianza baja → candidatas a revisión manual
    baja = df[df["confianza"] < 0.60].sort_values("confianza")
    if len(baja):
        print(f"\n  REVISION SUGERIDA — {len(baja)} facturas con confianza < 60%:")
        for _, row in baja.head(8).iterrows():
            concepto_corto = str(row["concepto"])[:52]
            print(
                f"    [{row['categoria_predicha']:<26}]"
                f"  {concepto_corto:<52}"
                f"  ({row['confianza']:.0%})"
            )
        if len(baja) > 8:
            print(f"    ... y {len(baja) - 8} más (ver {OUTPUT_CSV.name})")
    else:
        print("\n  Todas las facturas clasificadas con confianza >= 60%.")

    print(sep)


# ── Main ───────────────────────────────────────────────────────────────────────

def run() -> None:
    """Ejecuta el pipeline completo: entrenar → clasificar → reportar."""
    print("=" * 55)
    print("  CLASIFICADOR NLP — CONCEPTOS DE SERVICIO HVAC")
    print("=" * 55)
    print()

    print("PASO 1/3 — Entrenar el modelo")
    print("-" * 40)
    pipeline = entrenar()

    print()
    print("PASO 2/3 — Clasificar todas las facturas")
    print("-" * 40)
    df_facturas = clasificar_facturas(pipeline)

    print()
    print("PASO 3/3 — Reporte de resultados")
    imprimir_reporte(df_facturas)


if __name__ == "__main__":
    run()
