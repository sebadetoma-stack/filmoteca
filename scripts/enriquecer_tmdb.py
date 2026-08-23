#!/usr/bin/env python3
"""
Obtiene pósters, sinopsis y título en español desde TMDb para las películas confirmadas.

Uso:
  export TMDB_API_KEY=tu-clave
  python3 enriquecer_tmdb.py

- poster_url: siempre actualiza si no tiene
- titulo_es: solo escribe si no tiene todavía
- sinopsis: solo reemplaza si la actual está en inglés
"""
import json, os, sqlite3, sys, time, urllib.request
from pathlib import Path

try:
    from langdetect import detect
except ImportError:
    sys.exit("Falta langdetect. Corré: pip install langdetect")

DB      = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
API_KEY = os.environ.get("TMDB_API_KEY")
if not API_KEY:
    sys.exit("Falta TMDB_API_KEY.")

BASE  = "https://api.themoviedb.org/3"
IMG   = "https://image.tmdb.org/t/p/w342"
PAUSA = 0.26


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


def buscar_en_tmdb(tconst, titulo_primario, titulo_orig):
    """Devuelve (poster, titulo_es, sinopsis_es). Cada uno puede ser None."""
    url = f"{BASE}/find/{tconst}?api_key={API_KEY}&external_source=imdb_id&language=es-AR"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("movie_results", [])
        if not resultados:
            return None, None, None

        m = resultados[0]
        poster   = IMG + m["poster_path"] if m.get("poster_path") else None
        titulo   = m.get("title") or None
        sinopsis = m.get("overview") or None

        # titulo_es: solo si TMDb devolvió uno en español
        titulo_es = None
        if titulo and not titulo_sigue_en_ingles(titulo, titulo_orig, titulo_primario):
            titulo_es = titulo

        # sinopsis: si TMDb no trajo una en español, buscar en inglés
        sinopsis_es = None
        if sinopsis and not es_ingles(sinopsis):
            sinopsis_es = sinopsis
        elif not sinopsis:
            url_en = f"{BASE}/find/{tconst}?api_key={API_KEY}&external_source=imdb_id&language=en"
            with urllib.request.urlopen(url_en, timeout=10) as r:
                data_en = json.loads(r.read())
            res_en = data_en.get("movie_results", [])
            if res_en:
                sinopsis_es = res_en[0].get("overview") or None  # puede ser en inglés, ok

        return poster, titulo_es, sinopsis_es

    except Exception as e:
        print(f"  [!] Error {tconst}: {e}")
        return None, None, None


def main():
    con = sqlite3.connect(DB)

    # Asegurar columnas
    cols = [r[1] for r in con.execute("PRAGMA table_info(peliculas)")]
    for col in ["poster_url", "sinopsis", "titulo_es"]:
        if col not in cols:
            con.execute(f"ALTER TABLE peliculas ADD COLUMN {col} TEXT")
    con.commit()

    # Procesar: sin poster O sin titulo_es
    filas = con.execute("""
        SELECT DISTINCT p.tconst, p.titulo_primario, p.titulo_orig,
                        p.poster_url, p.titulo_es, p.sinopsis
        FROM peliculas p
        JOIN coincidencias co ON co.tconst = p.tconst
        JOIN videos v ON v.video_id = co.video_id
        WHERE co.estado = 'confirmada'
          AND v.activo = 1
          AND (co.verificado_ar != 'bloqueado' OR co.verificado_ar IS NULL)
          AND (p.poster_url IS NULL OR p.titulo_es IS NULL OR p.titulo_es = '')
        ORDER BY p.votos DESC
    """).fetchall()

    total = len(filas)
    print(f"{total:,} películas a procesar. Consultando TMDb...\n")

    cnt_poster   = 0
    cnt_titulo   = 0
    cnt_sinopsis = 0

    for i, (tconst, titulo_primario, titulo_orig, poster_actual,
            titulo_es_actual, sinopsis_actual) in enumerate(filas, 1):

        poster, titulo_es, sinopsis = buscar_en_tmdb(tconst, titulo_primario, titulo_orig)

        # poster: solo si no tiene
        nuevo_poster = poster if poster and not poster_actual else poster_actual

        # titulo_es: solo si no tiene todavía
        nuevo_titulo_es = titulo_es if titulo_es and not titulo_es_actual else titulo_es_actual

        # sinopsis: solo reemplazar si la actual está en inglés
        sinopsis_actual_str = sinopsis_actual or ""
        if sinopsis and es_ingles(sinopsis_actual_str):
            nuevo_sinopsis = sinopsis
        else:
            nuevo_sinopsis = sinopsis_actual

        con.execute(
            "UPDATE peliculas SET poster_url=?, titulo_es=?, sinopsis=? WHERE tconst=?",
            (nuevo_poster, nuevo_titulo_es, nuevo_sinopsis, tconst)
        )

        if (i % 50) == 0:
            con.commit()
            print(f"  {i:>4}/{total} — {cnt_poster} pósters, {cnt_titulo} títulos ES, {cnt_sinopsis} sinopsis")

        if poster and not poster_actual: cnt_poster += 1
        if titulo_es and not titulo_es_actual: cnt_titulo += 1
        if sinopsis and (es_ingles(sinopsis_actual_str) or not sinopsis_actual_str): cnt_sinopsis += 1

        time.sleep(PAUSA)

    con.commit()
    con.close()

    print(f"\nListo.")
    print(f"  Pósters nuevos:    {cnt_poster:,}")
    print(f"  Títulos ES nuevos: {cnt_titulo:,}")
    print(f"  Sinopsis updates:  {cnt_sinopsis:,}")

if __name__ == "__main__":
    main()
