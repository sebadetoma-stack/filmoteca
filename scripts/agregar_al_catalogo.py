#!/usr/bin/env python3
"""
Agrega películas específicas al catálogo desde los datasets de IMDb,
usando los tconst de un JSON de coincidencias.
No re-hace todo el catálogo — solo inserta las que faltan.

Uso:
  python3 agregar_al_catalogo.py tconst_limpios.json
"""
import csv, gzip, json, sqlite3, sys
from pathlib import Path

DB   = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
IMDB = Path(__file__).resolve().parent.parent / "datos" / "imdb"


def main():
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit("Falta archivo JSON")
    entradas = json.loads(ruta.read_text(encoding="utf-8"))
    
    # Extraer tconsts que faltan en la base
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = OFF")
    
    tconsts_json = {e["tconst"] for e in entradas}
    existentes = {r[0] for r in con.execute(
        f"SELECT tconst FROM peliculas WHERE tconst IN ({','.join('?'*len(tconsts_json))})",
        list(tconsts_json)
    )}
    faltan = tconsts_json - existentes
    print(f"{len(tconsts_json)} en el JSON, {len(existentes)} ya en catálogo, {len(faltan)} para agregar\n")
    
    if not faltan:
        print("Nada que agregar.")
        con.close()
        return

    # Leer title.basics para los que faltan
    print("Buscando en title.basics...")
    pelis = []
    with gzip.open(IMDB / "title.basics.tsv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["tconst"] not in faltan:
                continue
            try:
                anio = int(r["startYear"])
            except ValueError:
                continue
            dur = None
            if r["runtimeMinutes"] != "\\N":
                try: dur = int(r["runtimeMinutes"])
                except: pass
            precode = 1 if 1930 <= anio <= 1933 else (2 if anio == 1934 else 0)
            pelis.append((
                r["tconst"], r["originalTitle"], r["primaryTitle"], anio, dur,
                None if r["genres"] == "\\N" else r["genres"],
                None, 0, (anio // 10) * 10, precode,
            ))

    con.executemany("""
        INSERT OR IGNORE INTO peliculas
        (tconst, titulo_orig, titulo_primario, anio, duracion_min, generos,
         rating, votos, decada, es_precode)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, pelis)
    con.commit()
    print(f"  {len(pelis)} películas insertadas en el catálogo")

    # Agregar sus títulos alternativos
    print("Agregando títulos alternativos...")
    import unicodedata, re
    def normalizar(s):
        if not s: return ""
        s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    ids = {p[0] for p in pelis}
    alt = []
    vistos = set()
    for p in pelis:
        for t in (p[1], p[2]):
            k = (p[0], normalizar(t))
            if k not in vistos and t:
                vistos.add(k)
                alt.append((p[0], t, None, None, normalizar(t)))

    with gzip.open(IMDB / "title.akas.tsv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["titleId"] not in ids:
                continue
            n = normalizar(r["title"])
            k = (r["titleId"], n)
            if not n or k in vistos:
                continue
            vistos.add(k)
            alt.append((r["titleId"], r["title"],
                        None if r["region"] == "\\N" else r["region"],
                        None if r["language"] == "\\N" else r["language"], n))

    con.executemany(
        "INSERT OR IGNORE INTO titulos_alt (tconst, titulo, region, idioma, norm) VALUES (?,?,?,?,?)",
        alt)
    con.commit()
    print(f"  {len(alt)} títulos alternativos agregados")

    con.execute("PRAGMA foreign_keys = ON")
    con.close()
    print("\nListo. Ahora corré:")
    print("  python3 agregar_coincidencias.py tconst_limpios.json")


if __name__ == "__main__":
    main()
