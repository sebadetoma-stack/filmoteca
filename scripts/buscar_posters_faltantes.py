"""
buscar_posters_faltantes.py
Filmoteca Clásica — Busca posters en TMDb para películas sin poster.

Para cada película sin poster, busca en TMDb por título y año
(en lugar de solo por tconst de IMDb, que puede no estar indexado).

Uso:
    $env:TMDB_API_KEY="tu_clave"
    python buscar_posters_faltantes.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH  = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
BASE_URL = "https://api.themoviedb.org/3"
IMG_URL  = "https://image.tmdb.org/t/p/w342"
PAUSA    = 0.3

API_KEY = os.environ.get("TMDB_API_KEY", "")
if not API_KEY:
    print("ERROR: Falta TMDB_API_KEY")
    sys.exit(1)

def buscar_por_titulo(titulo, anio):
    """Busca película en TMDb por título y año. Devuelve (poster_url, sinopsis) o (None, None)."""
    params = urllib.parse.urlencode({
        "api_key": API_KEY,
        "query": titulo,
        "year": anio,
        "language": "es-AR",
    })
    url = f"{BASE_URL}/search/movie?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("results", [])
        if not resultados:
            # Intentar sin año
            params2 = urllib.parse.urlencode({
                "api_key": API_KEY,
                "query": titulo,
                "language": "es-AR",
            })
            url2 = f"{BASE_URL}/search/movie?{params2}"
            with urllib.request.urlopen(url2, timeout=10) as r:
                data2 = json.loads(r.read())
            resultados = data2.get("results", [])

        if not resultados:
            return None, None

        m = resultados[0]
        poster = IMG_URL + m["poster_path"] if m.get("poster_path") else None
        sinopsis = m.get("overview") or None

        # Si no hay sinopsis en español, buscar en inglés
        if not sinopsis:
            params_en = urllib.parse.urlencode({
                "api_key": API_KEY,
                "query": titulo,
                "year": anio,
                "language": "en",
            })
            url_en = f"{BASE_URL}/search/movie?{params_en}"
            with urllib.request.urlopen(url_en, timeout=10) as r:
                data_en = json.loads(r.read())
            res_en = data_en.get("results", [])
            if res_en:
                sinopsis = res_en[0].get("overview") or None

        return poster, sinopsis
    except Exception as e:
        print(f"    ERROR: {e}")
        return None, None

# ── Cargar películas sin poster disponibles en AR ─────────────────────────────

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.titulo_orig, p.anio
    FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.poster_url IS NULL
    ORDER BY p.votos DESC NULLS LAST
""").fetchall()

print(f"Películas sin poster a buscar: {len(filas)}")
print()

encontradas = 0
no_encontradas = []

for i, r in enumerate(filas, 1):
    tconst = r["tconst"]
    titulo = r["titulo_primario"]
    titulo_orig = r["titulo_orig"]
    anio   = r["anio"]

    print(f"[{i:>2}/{len(filas)}] {titulo} ({anio})")

    # Buscar por título primario
    poster, sinopsis = buscar_por_titulo(titulo, anio)

    # Si no encuentra, probar con título original
    if not poster and titulo_orig and titulo_orig != titulo:
        poster, sinopsis = buscar_por_titulo(titulo_orig, anio)

    if poster or sinopsis:
        con.execute(
            "UPDATE peliculas SET poster_url=?, sinopsis=? WHERE tconst=?",
            (poster, sinopsis, tconst)
        )
        con.commit()
        encontradas += 1
        print(f"    ✓ poster={'sí' if poster else 'no'} sinopsis={'sí' if sinopsis else 'no'}")
    else:
        no_encontradas.append(f"{titulo} ({anio})")
        print(f"    ✗ no encontrado en TMDb")

    time.sleep(PAUSA)

con.close()

print()
print("─" * 60)
print(f"Encontradas: {encontradas}")
print(f"No encontradas: {len(no_encontradas)}")
if no_encontradas:
    print()
    print("Sin datos en TMDb:")
    for p in no_encontradas:
        print(f"  {p}")
