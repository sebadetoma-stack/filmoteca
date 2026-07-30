#!/usr/bin/env python3
"""
agregar_70s.py
Agrega peliculas de 1971-1979 a la DB sin tocar nada existente.
Lee los archivos TSV de datos/imdb/ (sin comprimir).

Uso:
    cd C:\\Users\\sebad\\Downloads\\filmoteca\\scripts\\
    python agregar_70s.py
"""
import csv
import sqlite3
import unicodedata
import re
from pathlib import Path

ANIO_MIN, ANIO_MAX = 1971, 1979
MIN_VOTOS    = 100
MIN_DURACION = 55

DB_PATH  = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
IMDB_DIR = Path(__file__).resolve().parent.parent / "datos" / "imdb"

REGIONES = {"AR", "ES", "MX", "US", "GB", "VE", "CL", "CO", "\\N"}

def normalizar(s):
    if not s:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def abrir_tsv(nombre):
    p = IMDB_DIR / nombre
    if not p.exists():
        # Intentar con .gz
        p = IMDB_DIR / (nombre + ".gz")
        if p.exists():
            import gzip
            return gzip.open(p, "rt", encoding="utf-8", newline="")
        raise FileNotFoundError(f"No encontrado: {IMDB_DIR / nombre}")
    return open(p, "r", encoding="utf-8", newline="")

def leer(nombre):
    with abrir_tsv(nombre) as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  Agregando peliculas {ANIO_MIN}-{ANIO_MAX} a filmoteca.db")
print(f"{'='*55}\n")

con = sqlite3.connect(DB_PATH)

# Verificar cuántas hay antes
antes = con.execute("SELECT COUNT(*) FROM peliculas").fetchone()[0]
print(f"  Peliculas en DB antes: {antes:,}\n")

# 1. Ratings
print("Leyendo ratings...")
ratings = {}
for r in leer("title.ratings.tsv"):
    ratings[r["tconst"]] = (float(r["averageRating"]), int(r["numVotes"]))
print(f"  → {len(ratings):,} titulos con rating")

# 2. Basics — solo 1971-1979
print(f"Filtrando peliculas {ANIO_MIN}-{ANIO_MAX}...")
pelis = []
for r in leer("title.basics.tsv"):
    if r["titleType"] != "movie":
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
    if dur is not None and dur < MIN_DURACION:
        continue

    rating, votos = ratings.get(r["tconst"], (None, 0))
    if votos < MIN_VOTOS:
        continue

    pelis.append((
        r["tconst"], r["originalTitle"], r["primaryTitle"], anio, dur,
        None if r["genres"] == "\\N" else r["genres"],
        rating, votos, (anio // 10) * 10, 0,  # es_precode=0
    ))

print(f"  → {len(pelis):,} peliculas candidatas")

# 3. Insertar en peliculas — INSERT OR IGNORE para no tocar existentes
con.executemany("""
    INSERT OR IGNORE INTO peliculas
    (tconst, titulo_orig, titulo_primario, anio, duracion_min, generos,
     rating, votos, decada, es_precode)
    VALUES (?,?,?,?,?,?,?,?,?,?)
""", pelis)
con.commit()

ids = {p[0] for p in pelis}
nuevas = con.execute(
    f"SELECT COUNT(*) FROM peliculas WHERE anio BETWEEN {ANIO_MIN} AND {ANIO_MAX}"
).fetchone()[0]
print(f"  → {nuevas:,} peliculas en DB para {ANIO_MIN}-{ANIO_MAX}\n")

# 4. Titulos alternativos para las nuevas
print("Cargando titulos alternativos...")
alt, vistos = [], set()

# Titulo orig y primario
for p in pelis:
    for t in (p[1], p[2]):
        k = (p[0], normalizar(t))
        if k not in vistos and t:
            vistos.add(k)
            alt.append((p[0], t, None, None, normalizar(t)))

# akas
for r in leer("title.akas.tsv"):
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
    alt.append((tc, t,
                None if r["region"] == "\\N" else r["region"],
                None if r["language"] == "\\N" else r["language"],
                norm))

con.executemany(
    "INSERT OR IGNORE INTO titulos_alt (tconst, titulo, region, idioma, norm) VALUES (?,?,?,?,?)",
    alt)
con.commit()
print(f"  → {len(alt):,} titulos alternativos agregados")

# 5. Directores
print("Cargando directores...")
creditos, gente = [], set()
for r in leer("title.crew.tsv"):
    if r["tconst"] not in ids or r["directors"] == "\\N":
        continue
    for i, nc in enumerate(r["directors"].split(",")):
        if nc:
            creditos.append((r["tconst"], nc, "director", i))
            gente.add(nc)

# 6. Reparto
print("Cargando reparto...")
for r in leer("title.principals.tsv"):
    if r["tconst"] not in ids:
        continue
    if r["category"] not in ("actor", "actress"):
        continue
    orden = int(r["ordering"])
    if orden > 6:
        continue
    creditos.append((r["tconst"], r["nconst"], "actor", orden))
    gente.add(r["nconst"])

# 7. Nombres
print("Cargando nombres...")
personas = []
for r in leer("name.basics.tsv"):
    if r["nconst"] in gente:
        personas.append((r["nconst"], r["primaryName"]))

con.executemany("INSERT OR IGNORE INTO personas VALUES (?,?)", personas)
con.executemany("""
    INSERT OR IGNORE INTO creditos (tconst, nconst, rol, orden)
    VALUES (?,?,?,?)
""", creditos)
con.commit()
print(f"  → {len(personas):,} personas, {len(creditos):,} creditos\n")

# Resumen final
despues = con.execute("SELECT COUNT(*) FROM peliculas").fetchone()[0]
print(f"{'='*55}")
print(f"  Peliculas antes:  {antes:,}")
print(f"  Peliculas despues: {despues:,}")
print(f"  Nuevas agregadas:  {despues - antes:,}")
print()
print("  Por año (1971-1979):")
for anio, cnt in con.execute(
    f"SELECT anio, COUNT(*) FROM peliculas WHERE anio BETWEEN {ANIO_MIN} AND {ANIO_MAX} GROUP BY anio ORDER BY anio"
):
    print(f"    {anio}: {cnt:,} peliculas")

con.close()
print(f"\n{'='*55}")
print("  Listo. Ahora corré el matcher para procesar los nuevos titulos.")
print(f"{'='*55}")
