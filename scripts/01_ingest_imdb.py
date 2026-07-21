#!/usr/bin/env python3
"""
Etapa 1: catálogo base desde los datasets de IMDb.

Descargá antes (se refrescan a diario):
  cd datos/imdb
  wget https://datasets.imdbws.com/title.basics.tsv.gz
  wget https://datasets.imdbws.com/title.akas.tsv.gz
  wget https://datasets.imdbws.com/title.crew.tsv.gz
  wget https://datasets.imdbws.com/title.principals.tsv.gz
  wget https://datasets.imdbws.com/title.ratings.tsv.gz
  wget https://datasets.imdbws.com/name.basics.tsv.gz

Licencia IMDb: uso PERSONAL y NO COMERCIAL. Si esto se publica,
hay que re-derivar desde TMDb o Wikidata.

Uso:  python3 01_ingest_imdb.py [--min-votos 100]
"""
import argparse
import csv
import gzip
import sys
from pathlib import Path

from nucleo import BASE, DB, conectar, normalizar

IMDB = BASE / "datos" / "imdb"

ANIO_MIN, ANIO_MAX = 1930, 1970

# Regiones cuyos títulos alternativos nos interesan para las búsquedas.
REGIONES = {"AR", "ES", "MX", "US", "GB", "VE", "CL", "CO", "\\N"}

# El Código Hays se empezó a aplicar el 1 de julio de 1934 (creación de la PCA).
# Con IMDb solo tenemos el AÑO, así que 1934 es zona gris irresoluble: se marca 2.
PRECODE_DESDE, PRECODE_HASTA = 1930, 1933
PRECODE_GRIS = 1934


def abrir(nombre):
    p = IMDB / nombre
    if not p.exists():
        sys.exit(f"Falta {p}. Bajalo de https://datasets.imdbws.com/")
    return gzip.open(p, "rt", encoding="utf-8", newline="")


def leer(nombre):
    with abrir(nombre) as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-votos", type=int, default=100,
                    help="Piso de votos. Bajo = más rescates olvidados, más ruido.")
    ap.add_argument("--min-duracion", type=int, default=55)
    args = ap.parse_args()

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = conectar()
    con.executescript((Path(__file__).parent / "esquema.sql").read_text(encoding="utf-8"))

    # Estas tablas se reconstruyen enteras en cada corrida (si no, se duplican).
    # peliculas y personas usan INSERT OR REPLACE, así que no hace falta.
    # coincidencias y videos NO se tocan: sobreviven a la re-ingesta.
    con.execute("DELETE FROM titulos_alt")
    con.execute("DELETE FROM creditos")
    con.commit()

    # ---------- ratings (chico, va entero a memoria) ----------
    print("Leyendo ratings...")
    ratings = {
        r["tconst"]: (float(r["averageRating"]), int(r["numVotes"]))
        for r in leer("title.ratings.tsv.gz")
    }
    print(f"  {len(ratings):,} títulos con rating")

    # ---------- basics: el filtro grueso ----------
    print(f"Filtrando películas {ANIO_MIN}-{ANIO_MAX}...")
    pelis, n = [], 0
    for r in leer("title.basics.tsv.gz"):
        n += 1
        if r["titleType"] != "movie":       # fuera TV, cortos, series
            continue
        if r["isAdult"] == "1":
            continue
        try:
            anio = int(r["startYear"])
        except ValueError:
            continue
        if not (ANIO_MIN <= anio <= ANIO_MAX):
            continue

        dur = None
        if r["runtimeMinutes"] != "\\N":
            try:
                dur = int(r["runtimeMinutes"])
            except ValueError:
                pass
        # Un largometraje clásico dura 55'+. Lo que dura menos es corto.
        if dur is not None and dur < args.min_duracion:
            continue

        rating, votos = ratings.get(r["tconst"], (None, 0))
        if votos < args.min_votos:
            continue

        if PRECODE_DESDE <= anio <= PRECODE_HASTA:
            precode = 1
        elif anio == PRECODE_GRIS:
            precode = 2      # zona gris: el Código entró en vigor a mitad de año
        else:
            precode = 0

        pelis.append((
            r["tconst"], r["originalTitle"], r["primaryTitle"], anio, dur,
            None if r["genres"] == "\\N" else r["genres"],
            rating, votos, (anio // 10) * 10, precode,
        ))
        if n % 2_000_000 == 0:
            print(f"  ...{n:,} filas leídas, {len(pelis):,} candidatas")

    con.executemany(
        """INSERT OR REPLACE INTO peliculas
           (tconst, titulo_orig, titulo_primario, anio, duracion_min, generos,
            rating, votos, decada, es_precode)
           VALUES (?,?,?,?,?,?,?,?,?,?)""", pelis)
    con.commit()
    ids = {p[0] for p in pelis}
    print(f"  -> {len(ids):,} películas en el catálogo")

    # ---------- akas: títulos alternativos (clave para buscar y matchear) ----------
    print("Cargando títulos alternativos...")
    alt, vistos = [], set()
    for p in pelis:   # el título original y el primario también son "títulos conocidos"
        for t in (p[1], p[2]):
            k = (p[0], normalizar(t))
            if k not in vistos and t:
                vistos.add(k)
                alt.append((p[0], t, None, None, normalizar(t)))

    for r in leer("title.akas.tsv.gz"):
        tc = r["titleId"]
        if tc not in ids:
            continue
        if r["region"] not in REGIONES:
            continue
        t = r["title"]
        norm = normalizar(t)
        k = (tc, norm)
        if not norm or k in vistos:
            continue
        vistos.add(k)
        alt.append((tc, t, None if r["region"] == "\\N" else r["region"],
                    None if r["language"] == "\\N" else r["language"], norm))

    con.executemany(
        "INSERT INTO titulos_alt (tconst, titulo, region, idioma, norm) VALUES (?,?,?,?,?)",
        alt)
    con.commit()
    print(f"  -> {len(alt):,} títulos ({len(alt)/max(len(ids),1):.1f} por película)")

    # ---------- crew: directores ----------
    print("Cargando directores...")
    creditos, gente = [], set()
    for r in leer("title.crew.tsv.gz"):
        if r["tconst"] not in ids or r["directors"] == "\\N":
            continue
        for i, nc in enumerate(r["directors"].split(",")):
            if nc:
                creditos.append((r["tconst"], nc, "director", i))
                gente.add(nc)

    # ---------- principals: reparto principal ----------
    print("Cargando reparto...")
    for r in leer("title.principals.tsv.gz"):
        if r["tconst"] not in ids:
            continue
        if r["category"] not in ("actor", "actress"):
            continue
        orden = int(r["ordering"])
        if orden > 6:          # solo los principales
            continue
        creditos.append((r["tconst"], r["nconst"], "actor", orden))
        gente.add(r["nconst"])

    # ---------- names ----------
    print("Cargando nombres...")
    personas = [
        (r["nconst"], r["primaryName"])
        for r in leer("name.basics.tsv.gz") if r["nconst"] in gente
    ]
    con.executemany("INSERT OR REPLACE INTO personas VALUES (?,?)", personas)
    con.executemany(
        "INSERT OR REPLACE INTO creditos (tconst, nconst, rol, orden) VALUES (?,?,?,?)",
        creditos)
    con.commit()
    print(f"  -> {len(personas):,} personas, {len(creditos):,} créditos")

    # ---------- resumen ----------
    print("\nCatálogo por década:")
    for d, c, v in con.execute(
        "SELECT decada, COUNT(*), CAST(AVG(votos) AS INT) "
        "FROM peliculas GROUP BY decada ORDER BY decada"
    ):
        print(f"  {d}s: {c:>6,} películas   (media {v:,} votos)")
    pc = con.execute("SELECT COUNT(*) FROM peliculas WHERE es_precode=1").fetchone()[0]
    gris = con.execute("SELECT COUNT(*) FROM peliculas WHERE es_precode=2").fetchone()[0]
    print(f"\n  Pre-Code (1930-33): {pc:,}   |   zona gris (1934): {gris:,}")
    con.close()


if __name__ == "__main__":
    main()
