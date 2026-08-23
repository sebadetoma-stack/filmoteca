"""
aplicar_es_db.py
Filmoteca Clásica — Aplica títulos y sinopsis en español a filmoteca_completa.db

Fuentes (en orden de prioridad):
1. traducidos_gemini.json — títulos y sinopsis traducidos por Gemini
2. tmdb_resueltos.json — títulos y sinopsis resueltos por TMDb
3. pendientes_gemini.json — los que tienen titulo_es_resuelto parcial desde TMDb

Reglas:
- titulo_es: solo escribe si está vacío
- sinopsis: solo se reemplaza si la actual está en inglés

Modo --dry-run: muestra qué haría sin modificar nada.

Uso:
    python aplicar_es_db.py [--dry-run]
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    from langdetect import detect
except ImportError:
    sys.exit("Falta langdetect. Corré: pip install langdetect")

SCRIPTS_DIR = Path(__file__).resolve().parent
DB_PATH     = SCRIPTS_DIR.parent / "datos" / "filmoteca_completa.db"

DRY_RUN = "--dry-run" in sys.argv


def es_ingles(texto):
    if not texto or len(texto.strip()) < 20:
        return False
    try:
        return detect(texto) == "en"
    except Exception:
        return False


def cargar_json(nombre):
    path = SCRIPTS_DIR / nombre
    if not path.exists():
        print(f"  [!] No encontrado: {nombre}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    if DRY_RUN:
        print("=== MODO DRY-RUN: no se modifica nada ===\n")

    # ── Cargar fuentes ────────────────────────────────────────────────────────
    traducidos  = cargar_json("traducidos_gemini.json")
    tmdb_res    = cargar_json("tmdb_resueltos.json")
    pendientes  = cargar_json("pendientes_gemini.json")

    # Armar índice unificado: tconst → {titulo_es, sinopsis_es}
    # Prioridad: traducidos > tmdb_resueltos > pendientes parciales
    indice = {}

    # 3. Pendientes parciales (menor prioridad)
    for p in pendientes:
        t = p["tconst"]
        if t not in indice:
            indice[t] = {}
        if "titulo_es_resuelto" in p and "titulo_es" not in indice[t]:
            indice[t]["titulo_es"] = p["titulo_es_resuelto"]
        if "sinopsis_es_resuelta" in p and "sinopsis_es" not in indice[t]:
            indice[t]["sinopsis_es"] = p["sinopsis_es_resuelta"]

    # 2. TMDb resueltos
    for p in tmdb_res:
        t = p["tconst"]
        if t not in indice:
            indice[t] = {}
        if "titulo_es_resuelto" in p:
            indice[t]["titulo_es"] = p["titulo_es_resuelto"]
        if "sinopsis_es_resuelta" in p:
            indice[t]["sinopsis_es"] = p["sinopsis_es_resuelta"]

    # 1. Traducidos por Gemini (mayor prioridad)
    for p in traducidos:
        t = p["tconst"]
        if t not in indice:
            indice[t] = {}
        if "titulo_es_resuelto" in p:
            indice[t]["titulo_es"] = p["titulo_es_resuelto"]
        if "sinopsis_es_resuelta" in p:
            indice[t]["sinopsis_es"] = p["sinopsis_es_resuelta"]

    print(f"Registros en índice: {len(indice):,}")

    # ── Conectar DB ───────────────────────────────────────────────────────────
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Leer sinopsis actuales para verificar si están en inglés
    sinopsis_db = {
        r["tconst"]: r["sinopsis"] or ""
        for r in con.execute("SELECT tconst, sinopsis FROM peliculas")
    }

    titulo_es_db = {
        r["tconst"]: r["titulo_es"] or ""
        for r in con.execute("SELECT tconst, titulo_es FROM peliculas")
    }

    cnt_titulo   = 0
    cnt_sinopsis = 0
    cnt_skip_s   = 0
    muestra      = []

    for tconst, datos in indice.items():
        titulo_es       = datos.get("titulo_es")
        sinopsis_es     = datos.get("sinopsis_es")
        sinopsis_actual = sinopsis_db.get(tconst, "")
        titulo_es_actual = titulo_es_db.get(tconst, "")

        # Solo escribir titulo_es si está vacío en la DB
        escribir_titulo = titulo_es and not titulo_es_actual
        actualizar_sinopsis = sinopsis_es and es_ingles(sinopsis_actual)

        if DRY_RUN:
            if len(muestra) < 20:
                muestra.append({
                    "tconst":    tconst,
                    "titulo_es": titulo_es,
                    "sinopsis":  (sinopsis_es or "")[:100] if actualizar_sinopsis else "(sin cambio)",
                })
        else:
            if escribir_titulo:
                con.execute(
                    "UPDATE peliculas SET titulo_es = ? WHERE tconst = ?",
                    (titulo_es, tconst)
                )
                cnt_titulo += 1

            if actualizar_sinopsis:
                con.execute(
                    "UPDATE peliculas SET sinopsis = ? WHERE tconst = ?",
                    (sinopsis_es, tconst)
                )
                cnt_sinopsis += 1
            elif sinopsis_es and not es_ingles(sinopsis_actual):
                cnt_skip_s += 1

    if not DRY_RUN:
        con.commit()
        print(f"  Títulos escritos:           {cnt_titulo:,}")
        print(f"  Sinopsis actualizadas:      {cnt_sinopsis:,}")
        print(f"  Sinopsis sin cambio (ES):   {cnt_skip_s:,}")
    else:
        print("\nMuestra de lo que se aplicaría (primeros 20):")
        for m in muestra:
            print(f"  [{m['tconst']}]")
            print(f"    titulo_es: {m['titulo_es']}")
            print(f"    sinopsis:  {m['sinopsis']}")
            print()

    con.close()
    if not DRY_RUN:
        print("\nListo. filmoteca_completa.db actualizada.")


if __name__ == "__main__":
    main()
