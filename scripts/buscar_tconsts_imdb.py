"""
buscar_tconsts_imdb.py
Filmoteca Clásica — Busca tconsts en IMDb para películas identificadas por IA.

Busca en title.basics (título primario y original) Y en title.akas (títulos
alternativos en todos los idiomas, incluido español).

Uso:
    python buscar_tconsts_imdb.py

Archivos:
    Entrada:  datos/para_buscar_en_imdb.json
    IMDb:     datos/imdb/title.basics.tsv.gz + title.akas.tsv.gz
    Salida:   datos/tconsts_encontrados.json
"""

import gzip
import json
import sqlite3
from pathlib import Path
from collections import defaultdict

BASE       = Path(__file__).resolve().parent.parent / "datos"
JSON_ENTR  = BASE / "para_buscar_en_imdb.json"
TSV_BASICS = BASE / "imdb" / "title.basics.tsv.gz"
TSV_AKAS   = BASE / "imdb" / "title.akas.tsv.gz"
JSON_SAL   = BASE / "tconsts_encontrados.json"
DB_PATH    = BASE / "filmoteca.db"

# ── Cargar y deduplicar películas a buscar ────────────────────────────────────

with open(JSON_ENTR, encoding="utf-8") as f:
    data = json.load(f)

vistas = {}
for r in data:
    key = (r["titulo_pelicula"].lower().strip(), r["anio"])
    if key not in vistas:
        vistas[key] = r
    elif r["confianza"] == "alta" and vistas[key]["confianza"] != "alta":
        vistas[key] = r

peliculas = list(vistas.values())
print(f"Películas a buscar: {len(peliculas)}")

# ── Cargar tconsts ya en la DB ────────────────────────────────────────────────

con = sqlite3.connect(DB_PATH)
# tconsts que ya tienen coincidencia confirmada (tienen video)
ya_con_video = {r[0] for r in con.execute(
    "SELECT tconst FROM coincidencias WHERE estado='confirmada'"
).fetchall()}
# tconsts que existen en peliculas (para poder hacer el join con akas)
todos_tconsts = {r[0] for r in con.execute("SELECT tconst FROM peliculas").fetchall()}
tconst_anio = {r[0]: r[1] for r in con.execute("SELECT tconst, anio FROM peliculas").fetchall()}
con.close()
print(f"Tconsts en DB: {len(todos_tconsts)}")
print(f"Tconsts con video confirmado: {len(ya_con_video)}")
print()

# ── Indexar basics por título + año ──────────────────────────────────────────

print("Indexando title.basics...")
indice = defaultdict(list)  # (titulo_lower, anio) -> [(tconst, titulo_prim, tipo)]
tconst_info = {}            # tconst -> (titulo_prim, tipo, anio)

with gzip.open(TSV_BASICS, "rt", encoding="utf-8") as f:
    next(f)
    for linea in f:
        partes = linea.rstrip("\n").split("\t")
        if len(partes) < 9:
            continue
        tconst, tipo, titulo_prim, titulo_orig, _, anio, _, _, _ = partes[:9]
        if tipo not in ("movie", "tvMovie"):
            continue
        if anio == r"\N":
            continue
        try:
            anio_int = int(anio)
        except ValueError:
            continue
        if anio_int < 1928 or anio_int > 1979:
            continue
        tconst_info[tconst] = (titulo_prim, tipo, anio_int)
        indice[(titulo_prim.lower(), anio_int)].append((tconst, titulo_prim, tipo))
        if titulo_orig != titulo_prim:
            indice[(titulo_orig.lower(), anio_int)].append((tconst, titulo_prim, tipo))

print(f"  {len(indice):,} entradas en basics")

# ── Indexar akas por título + año ─────────────────────────────────────────────

print("Indexando title.akas (puede tardar)...")
akas_count = 0

with gzip.open(TSV_AKAS, "rt", encoding="utf-8") as f:
    next(f)
    for linea in f:
        partes = linea.rstrip("\n").split("\t")
        if len(partes) < 3:
            continue
        tconst = partes[0]
        titulo_aka = partes[2]
        if tconst not in tconst_info:
            continue
        titulo_prim, tipo, anio_int = tconst_info[tconst]
        key = (titulo_aka.lower(), anio_int)
        if key not in indice:
            indice[key].append((tconst, titulo_prim, tipo))
            akas_count += 1

print(f"  {akas_count:,} entradas adicionales desde akas")
print(f"  Total índice: {len(indice):,} entradas")
print()

# ── Buscar cada película ───────────────────────────────────────────────────────

encontrados = []
no_encontrados = []

for peli in peliculas:
    titulo = peli["titulo_pelicula"].strip()
    anio   = int(peli["anio"])

    candidatos = []
    for delta in [0, 1, -1]:
        key = (titulo.lower(), anio + delta)
        if key in indice:
            candidatos.extend(indice[key])

    # Deduplicar candidatos
    vistos = set()
    candidatos_unicos = []
    for c in candidatos:
        if c[0] not in vistos:
            vistos.add(c[0])
            candidatos_unicos.append(c)

    if not candidatos_unicos:
        no_encontrados.append(peli)
        print(f"  ✗ {titulo} ({anio}) — no encontrado")
        continue

    con_video = [(t, tt, tp) for t, tt, tp in candidatos_unicos if t in ya_con_video]
    sin_video  = [(t, tt, tp) for t, tt, tp in candidatos_unicos if t not in ya_con_video]

    if con_video:
        print(f"  = {titulo} ({anio}) — ya tiene video: {con_video[0][0]} [{con_video[0][1]}]")
        continue

    nuevos = sin_video

    if not nuevos:
        no_encontrados.append(peli)
        print(f"  ✗ {titulo} ({anio}) — candidatos pero todos ya tienen video")
        continue

    tconst, titulo_imdb, tipo = nuevos[0]
    encontrados.append({
        "tconst":         tconst,
        "titulo_imdb":    titulo_imdb,
        "titulo_buscado": titulo,
        "anio":           anio,
        "director":       peli["director"],
        "video_id":       peli["video_id"],
        "titulo_video":   peli["titulo_video"],
        "confianza":      peli["confianza"],
        "multiples":      len(nuevos) > 1,
    })
    extras = f" (+{len(nuevos)-1} más)" if len(nuevos) > 1 else ""
    print(f"  ✓ {titulo} ({anio}) → {tconst} [{titulo_imdb}]{extras}")

# ── Resumen ───────────────────────────────────────────────────────────────────

print()
print("─" * 60)
print(f"Encontrados y nuevos: {len(encontrados)}")
print(f"No encontrados:       {len(no_encontrados)}")

if no_encontrados:
    print()
    print("No encontrados:")
    for p in no_encontrados:
        print(f"  {p['titulo_pelicula']} ({p['anio']}) — {p['director']}")

with open(JSON_SAL, "w", encoding="utf-8") as f:
    json.dump(encontrados, f, ensure_ascii=False, indent=2)

print()
print(f"Guardado en: {JSON_SAL}")
print(f"Siguiente paso: revisar tconsts_encontrados.json y correr agregar_al_catalogo.py + agregar_coincidencias.py")
