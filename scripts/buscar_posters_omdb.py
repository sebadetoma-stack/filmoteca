"""
buscar_posters_omdb.py
Filmoteca Clásica — Busca posters en OMDB para películas sin poster.

OMDB busca por IMDb ID directamente — muy preciso.

Uso:
    $env:OMDB_API_KEY="tu_clave"
    python buscar_posters_omdb.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
PAUSA   = 0.3

OMDB_KEY = os.environ.get("OMDB_API_KEY", "")
if not OMDB_KEY:
    print("ERROR: Falta OMDB_API_KEY")
    sys.exit(1)

def verificar_imagen(url):
    """Verifica que una URL de imagen realmente carga."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            content_type = r.headers.get("Content-Type", "")
            return "image" in content_type
    except Exception:
        return False

def buscar_omdb(tconst):
    """Busca poster en OMDB por tconst de IMDb. Devuelve URL o None."""
    params = urllib.parse.urlencode({
        "i": tconst,
        "apikey": OMDB_KEY,
    })
    url = f"http://www.omdbapi.com/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        if data.get("Response") == "True":
            poster = data.get("Poster")
            if poster and poster != "N/A":
                if "amazon" not in poster and verificar_imagen(poster):
                    return poster
                else:
                    print(f"    imagen de Amazon descartada (hotlink bloqueado)")
        return None
    except Exception as e:
        print(f"    ERROR OMDB: {e}")
        return None

# ── Cargar películas sin poster ───────────────────────────────────────────────

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.anio, p.votos
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
    anio   = r["anio"]

    print(f"[{i:>2}/{len(filas)}] {titulo} ({anio})")

    poster = buscar_omdb(tconst)

    if poster:
        con.execute(
            "UPDATE peliculas SET poster_url=? WHERE tconst=?",
            (poster, tconst)
        )
        con.commit()
        encontradas += 1
        print(f"    ✓ poster encontrado")
    else:
        no_encontradas.append(f"{titulo} ({anio})")
        print(f"    ✗ no encontrado")

    time.sleep(PAUSA)

con.close()

print()
print("─" * 60)
print(f"Encontradas: {encontradas}")
print(f"No encontradas: {len(no_encontradas)}")
if no_encontradas:
    print()
    print("Sin poster en OMDB:")
    for p in no_encontradas:
        print(f"  {p}")
