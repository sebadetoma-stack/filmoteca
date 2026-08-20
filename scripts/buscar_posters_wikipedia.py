"""
buscar_posters_wikipedia.py
Filmoteca Clásica — Busca posters en Wikipedia para películas sin poster.

Para cada película sin poster, busca la imagen principal del artículo
en Wikipedia (en español primero, luego en inglés).

Uso:
    python buscar_posters_wikipedia.py
"""

import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
PAUSA   = 2

def buscar_imagen_wikipedia(titulo, anio, titulo_orig=None, lang="es"):
    """Busca la imagen principal de un artículo de Wikipedia."""
    # Buscar el artículo
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": f"{titulo} {anio} película",
        "srlimit": 3,
        "format": "json",
    })
    url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    headers = {"User-Agent": "FilmotecaClasica/1.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("query", {}).get("search", [])
        if not resultados:
            return None

        # Obtener imagen principal del artículo
        pageid = resultados[0]["pageid"]
        params2 = urllib.parse.urlencode({
            "action": "query",
            "pageids": pageid,
            "prop": "pageimages",
            "pithumbsize": 300,
            "format": "json",
        })
        url2 = f"https://{lang}.wikipedia.org/w/api.php?{params2}"
        req2 = urllib.request.Request(url2, headers=headers)
        with urllib.request.urlopen(req2, timeout=10) as r:
            data2 = json.loads(r.read())
        pages = data2.get("query", {}).get("pages", {})
        for page in pages.values():
            thumb = page.get("thumbnail", {})
            if thumb and thumb.get("source"):
                return thumb["source"]
        return None
    except Exception as e:
        if "429" not in str(e):
            print(f"    ERROR Wikipedia ({lang}): {e}")
        else:
            print(f"    Rate limit Wikipedia ({lang}), esperando...")
            time.sleep(5)
        return None

# ── Cargar películas sin poster ───────────────────────────────────────────────

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.titulo_orig, p.anio, p.votos
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
    tconst     = r["tconst"]
    titulo     = r["titulo_primario"]
    titulo_orig = r["titulo_orig"]
    anio       = r["anio"]

    print(f"[{i:>2}/{len(filas)}] {titulo} ({anio})")

    # 1. Wikipedia en español
    imagen = buscar_imagen_wikipedia(titulo, anio, lang="es")
    if not imagen and titulo_orig and titulo_orig != titulo:
        imagen = buscar_imagen_wikipedia(titulo_orig, anio, lang="es")

    # 2. Wikipedia en inglés
    if not imagen:
        imagen = buscar_imagen_wikipedia(titulo, anio, lang="en")
        if not imagen and titulo_orig and titulo_orig != titulo:
            imagen = buscar_imagen_wikipedia(titulo_orig, anio, lang="en")

    if imagen:
        con.execute(
            "UPDATE peliculas SET poster_url=? WHERE tconst=?",
            (imagen, tconst)
        )
        con.commit()
        encontradas += 1
        print(f"    ✓ imagen encontrada")
    else:
        no_encontradas.append(f"{titulo} ({anio})")
        print(f"    ✗ no encontrada")

    time.sleep(PAUSA)

con.close()

print()
print("─" * 60)
print(f"Encontradas: {encontradas}")
print(f"No encontradas: {len(no_encontradas)}")
if no_encontradas:
    print()
    for p in no_encontradas:
        print(f"  {p}")
