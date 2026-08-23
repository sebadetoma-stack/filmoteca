"""
auditar_titulo_sinopsis_es.py
Filmoteca Clásica — Audita títulos y sinopsis en español via TMDb.

Para cada película confirmada sin titulo_es:
1. Consulta TMDb en es-AR
2. Si trae título en español → resuelto
3. Si trae sinopsis en español y la actual está en inglés → resuelto
4. Lo que TMDb no resuelve → va a pendientes_gemini.json

Guarda TODOS los resultados en tmdb_resueltos.json (los resueltos por TMDb)
y los pendientes en pendientes_gemini.json (como antes).

Uso:
    $env:TMDB_API_KEY="tu_clave"
    python auditar_titulo_sinopsis_es.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

try:
    from langdetect import detect
except ImportError:
    sys.exit("Falta langdetect. Corré: pip install langdetect")

DB_PATH          = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
JSON_PENDIENTES  = Path(__file__).resolve().parent / "pendientes_gemini.json"
JSON_RESUELTOS   = Path(__file__).resolve().parent / "tmdb_resueltos.json"
TMDB_BASE        = "https://api.themoviedb.org/3"
PAUSA            = 0.26

TMDB_KEY = os.environ.get("TMDB_API_KEY", "")
if not TMDB_KEY:
    sys.exit("ERROR: Falta TMDB_API_KEY")


def es_ingles(texto):
    if not texto or len(texto.strip()) < 20:
        return False
    try:
        return detect(texto) == "en"
    except Exception:
        return False


def titulo_sigue_en_ingles(titulo_tmdb, titulo_orig, titulo_primario):
    if not titulo_tmdb:
        return True
    if titulo_tmdb.lower() == titulo_primario.lower():
        return True
    if titulo_orig and titulo_tmdb.lower() == titulo_orig.lower():
        return True
    return es_ingles(titulo_tmdb)


def consultar_tmdb(tconst):
    url = (
        f"{TMDB_BASE}/find/{tconst}"
        f"?api_key={TMDB_KEY}&external_source=imdb_id&language=es-AR"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("movie_results", [])
        if not resultados:
            return None, None
        m = resultados[0]
        return m.get("title") or None, m.get("overview") or None
    except Exception as e:
        print(f"    [!] Error TMDb ({tconst}): {e}")
        return None, None


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    cols = {r[1] for r in con.execute("PRAGMA table_info(peliculas)")}
    if "titulo_es" not in cols:
        con.execute("ALTER TABLE peliculas ADD COLUMN titulo_es TEXT")
        con.commit()
        print("✓ Columna titulo_es creada en peliculas")
    else:
        print("✓ Columna titulo_es ya existe")

    filas = con.execute("""
        SELECT DISTINCT
            p.tconst, p.titulo_primario, p.titulo_orig, p.anio, p.sinopsis
        FROM peliculas p
        JOIN coincidencias co ON co.tconst = p.tconst
        WHERE co.estado = 'confirmada'
          AND (p.titulo_es IS NULL OR p.titulo_es = '')
        ORDER BY p.votos DESC NULLS LAST
    """).fetchall()

    con.close()

    total = len(filas)
    print(f"\nPelículas confirmadas sin titulo_es: {total:,}")
    print("Procesando...\n")

    cnt_titulo_tmdb   = 0
    cnt_sinopsis_tmdb = 0
    cnt_ok            = 0
    pendientes        = []
    resueltos         = []

    for i, r in enumerate(filas, 1):
        tconst          = r["tconst"]
        titulo_primario = r["titulo_primario"]
        titulo_orig     = r["titulo_orig"]
        anio            = r["anio"]
        sinopsis_actual = r["sinopsis"] or ""

        print(f"  [{i}/{total}] {titulo_primario} ({anio})")

        titulo_tmdb, sinopsis_tmdb = consultar_tmdb(tconst)
        time.sleep(PAUSA)

        titulo_es   = None
        sinopsis_es = None

        if titulo_tmdb and not titulo_sigue_en_ingles(titulo_tmdb, titulo_orig, titulo_primario):
            titulo_es = titulo_tmdb
            cnt_titulo_tmdb += 1

        if es_ingles(sinopsis_actual) and sinopsis_tmdb and not es_ingles(sinopsis_tmdb):
            sinopsis_es = sinopsis_tmdb
            cnt_sinopsis_tmdb += 1

        necesita_titulo   = not titulo_es
        necesita_sinopsis = es_ingles(sinopsis_actual) and not sinopsis_es

        if necesita_titulo or necesita_sinopsis:
            entrada = {
                "tconst":          tconst,
                "titulo_primario": titulo_primario,
                "titulo_orig":     titulo_orig,
                "anio":            anio,
            }
            if necesita_titulo:
                entrada["traducir_titulo"] = titulo_primario
            if necesita_sinopsis:
                entrada["traducir_sinopsis"] = sinopsis_actual
            if titulo_es:
                entrada["titulo_es_resuelto"] = titulo_es
                entrada["fuente_titulo"]       = "tmdb"
            if sinopsis_es:
                entrada["sinopsis_es_resuelta"] = sinopsis_es
                entrada["fuente_sinopsis"]       = "tmdb"
            pendientes.append(entrada)
        else:
            # Resuelto completamente por TMDb
            entrada = {
                "tconst":               tconst,
                "titulo_primario":      titulo_primario,
                "titulo_orig":          titulo_orig,
                "anio":                 anio,
                "titulo_es_resuelto":   titulo_es,
                "fuente_titulo":        "tmdb",
            }
            if sinopsis_es:
                entrada["sinopsis_es_resuelta"] = sinopsis_es
                entrada["fuente_sinopsis"]       = "tmdb"
            resueltos.append(entrada)
            cnt_ok += 1

    # Guardar JSONs
    with open(JSON_PENDIENTES, "w", encoding="utf-8") as f:
        json.dump(pendientes, f, ensure_ascii=False, indent=2)
    with open(JSON_RESUELTOS, "w", encoding="utf-8") as f:
        json.dump(resueltos, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"RESUMEN")
    print(f"{'=' * 60}")
    print(f"  Total procesadas:              {total:,}")
    print(f"  Resueltas por TMDb:            {cnt_ok:,}")
    print(f"  Pendientes (Gemini/manual):    {len(pendientes):,}")
    print(f"")
    print(f"  Títulos resueltos por TMDb:    {cnt_titulo_tmdb:,}")
    print(f"  Sinopsis resueltas por TMDb:   {cnt_sinopsis_tmdb:,}")
    print(f"")
    if pendientes:
        nt = sum(1 for p in pendientes if "traducir_titulo"   in p)
        ns = sum(1 for p in pendientes if "traducir_sinopsis" in p)
        print(f"  Necesitan traducir título:     {nt:,}")
        print(f"  Necesitan traducir sinopsis:   {ns:,}")
    print(f"\n  JSON resueltos:   {JSON_RESUELTOS}")
    print(f"  JSON pendientes:  {JSON_PENDIENTES}")


if __name__ == "__main__":
    main()
