#!/usr/bin/env python3
"""
Obtiene pósters y sinopsis desde TMDb para las películas confirmadas.

Uso:
  export TMDB_API_KEY=tu-clave
  python3 enriquecer_tmdb.py

Agrega columnas 'poster_url' y 'sinopsis' a la tabla peliculas.
Gratis, sin límite estricto (40 requests/10 segundos).
"""
import json, os, sqlite3, sys, time, urllib.parse, urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
API_KEY = os.environ.get("TMDB_API_KEY")
if not API_KEY:
    sys.exit("Falta TMDB_API_KEY.")

BASE = "https://api.themoviedb.org/3"
IMG  = "https://image.tmdb.org/t/p/w342"  # 342px ancho — bueno para tarjetas
PAUSA = 0.26  # ~4 req/seg, bien por debajo del límite


def buscar_por_imdb_id(tconst):
    url = f"{BASE}/find/{tconst}?api_key={API_KEY}&external_source=imdb_id&language=es-AR"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("movie_results", [])
        if resultados:
            m = resultados[0]
            poster = IMG + m["poster_path"] if m.get("poster_path") else None
            sinopsis = m.get("overview") or None
            # Si no hay sinopsis en español, buscar en inglés
            if not sinopsis:
                url_en = f"{BASE}/find/{tconst}?api_key={API_KEY}&external_source=imdb_id&language=en"
                with urllib.request.urlopen(url_en, timeout=10) as r:
                    data_en = json.loads(r.read())
                res_en = data_en.get("movie_results", [])
                if res_en:
                    sinopsis = res_en[0].get("overview") or None
            return poster, sinopsis
    except Exception as e:
        print(f"  [!] Error {tconst}: {e}")
    return None, None


def main():
    con = sqlite3.connect(DB)

    # Agregar columnas si no existen
    cols = [r[1] for r in con.execute("PRAGMA table_info(peliculas)")]
    if "poster_url" not in cols:
        con.execute("ALTER TABLE peliculas ADD COLUMN poster_url TEXT")
    if "sinopsis" not in cols:
        con.execute("ALTER TABLE peliculas ADD COLUMN sinopsis TEXT")
    con.commit()

    # Solo las confirmadas visibles en AR sin datos todavía
    tconsts = [r[0] for r in con.execute("""
        SELECT DISTINCT p.tconst FROM peliculas p
        JOIN coincidencias co ON co.tconst = p.tconst
        JOIN videos v ON v.video_id = co.video_id
        WHERE co.estado = 'confirmada'
          AND v.activo = 1
          AND (co.verificado_ar != 'bloqueado' OR co.verificado_ar IS NULL)
          AND p.poster_url IS NULL
        ORDER BY p.votos DESC
    """)]

    print(f"{len(tconsts):,} películas sin póster. Consultando TMDb...\n")

    con_poster = 0
    con_sinopsis = 0

    for i, tconst in enumerate(tconsts):
        poster, sinopsis = buscar_por_imdb_id(tconst)
        con.execute(
            "UPDATE peliculas SET poster_url=?, sinopsis=? WHERE tconst=?",
            (poster, sinopsis, tconst)
        )
        if (i + 1) % 50 == 0:
            con.commit()
            print(f"  {i+1:>4}/{len(tconsts)} — {con_poster} pósters, {con_sinopsis} sinopsis")
        if poster: con_poster += 1
        if sinopsis: con_sinopsis += 1
        time.sleep(PAUSA)

    con.commit()
    con.close()

    print(f"\nListo.")
    print(f"  Con póster:   {con_poster:,}")
    print(f"  Con sinopsis: {con_sinopsis:,}")
    print(f"  Sin datos:    {len(tconsts) - con_poster:,}")

if __name__ == "__main__":
    main()
